#!/usr/bin/env python3
"""
Robinhood Chain Scanner — scan langsung chain 4663 buat nemuin coin baru.
Sumber: Blockscout API (token baru) + DexScreener (trending) + RPC (Uniswap V3 pool baru).

Chain: 4663 (Robinhood), pake Uniswap V3 router 0xcaf681a66d020601342297493863e78c959e5cb2
"""
import os, sys, json, urllib.request, urllib.parse, time, re, argparse

DS = "https://api.dexscreener.com"
BS = "https://robinhoodchain.blockscout.com/api/v2"
RPC = "http://127.0.0.1:8098/rpc"   # curl proxy untuk robinhood RPC
UNI_V3_FACTORY = "0xcaf681a66d020601342297493863e78c959e5cb2"  # Uniswap V3
WETH = "0xc778417e063141139fce010982780140aa0cd5ab"  # WETH on Robinhood

def fmt(n,d=0):
    try: return f"{n:,.{d}f}"
    except: return "?"

def blockscout(path):
    """Fetch from Blockscout API"""
    try:
        req=urllib.request.Request(BS+path,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=20) as r:
            return json.loads(r.read().decode())
    except Exception as e: return {"error":str(e)}

def rpc(method,params=[],retries=2):
    """JSON-RPC via curl proxy"""
    body=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode()
    for i in range(retries):
        try:
            req=urllib.request.Request(RPC,data=body,headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(req,timeout=20) as r:
                return json.loads(r.read().decode()).get("result")
        except Exception as e:
            if i<retries-1: time.sleep(1)
    return None

def dex_search(query):
    """Search DexScreener"""
    try:
        req=urllib.request.Request(f"{DS}/latest/dex/search?q={query}",headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=15) as r:
            return json.loads(r.read().decode()).get("pairs",[])
    except: return []

def dex_token(tok):
    """Token pairs on DexScreener"""
    try:
        req=urllib.request.Request(f"{DS}/latest/dex/tokens/{tok}",headers={"User-Agent":"Mozilla/5.0"})
        return json.loads(urllib.request.urlopen(req,timeout=15).read()).get("pairs",[])
    except: return []

def dex_profiles():
    """Latest token profiles (new listings)"""
    try:
        req=urllib.request.Request(f"{DS}/token-profiles/latest/v1",headers={"User-Agent":"Mozilla/5.0"})
        return json.loads(urllib.request.urlopen(req,timeout=15).read())
    except: return []

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--max-mc",type=float,default=5_000_000)
    ap.add_argument("--min-liq",type=float,default=50_000)
    ap.add_argument("--max-pages",type=int,default=3)
    ap.add_argument("--json",action="store_true")
    args=ap.parse_args()

    print("🔍 Robinhood Chain Scanner — cari coin baru (chain 4663)")
    print("="*70)

    # 1. Blockscout — token ERC-20 (default sort, paginate via next_page_params)
    tokens=[]
    next_params=""
    for pg in range(args.max_pages):
        data=blockscout(f"/tokens?type=ERC-20&limit=50{next_params}")
        if "error" in data or not isinstance(data.get("items"),list): break
        items=data.get("items") or []
        for t in items:
            addr=(t.get("address_hash") or t.get("address") or "").lower()
            sym=t.get("symbol") or "?"
            name=t.get("name") or "?"
            holders=int(t.get("holders_count") or 0)
            if addr and addr not in {x["addr"] for x in tokens}:
                tokens.append({"addr":addr,"sym":sym,"name":name,"holders":holders,"source":"blockscout"})
        npp=data.get("next_page_params") or {}
        if not npp: break
        next_params="&"+urllib.parse.urlencode(npp)
        time.sleep(0.5)
    print(f"📡 blockscout: {len(tokens)} token ERC-20")

    # 2. DexScreener token-profiles — filter robinhood
    try:
        pro=dex_profiles()
        for p in pro:
            if p.get("chainId")=="robinhood":
                addr=p.get("tokenAddress","").lower()
                if addr not in {x["addr"] for x in tokens}:
                    tokens.append({"addr":addr,"sym":p.get("symbol") or "?","name":"?","holders":0,"source":"dex-profiles"})
    except: pass
    print(f"📡 + dexscreener profiles: {len(tokens)} total token robinhood")

    # 3. RPC — cek pool Uniswap V3 terbaru (event PoolCreated)
    # Approach: scan recent blocks for PoolCreated events from factory
    latest_block=rpc("eth_blockNumber")
    if latest_block:
        latest=int(latest_block,16)
        step=1000
        # scan last 5000 blocks for new pools
        pool_addresses=set()
        from_block=max(latest-5000, 0)
        logs=rpc("eth_getLogs",[{
            "address":UNI_V3_FACTORY,
            "fromBlock":hex(from_block),
            "toBlock":hex(latest),
            "topics":["0x783f586f5a4b9e5bc1b9f0d0bcb6e5e83c4005cd9f3e0e5b960e8e0d0b68f41"]  # PoolCreated event
        }])
        if logs and isinstance(logs,list):
            for log in logs:
                topics=log.get("topics") or []
                if len(topics)>=4:
                    # token0=topics[1], token1=topics[2], pool=topics[3]
                    t0="0x"+topics[1][-40:].lower()
                    t1="0x"+topics[2][-40:].lower()
                    pool="0x"+topics[3][-40:].lower()
                    for t in [t0,t1]:
                        if t!=WETH.lower() and t not in {x["addr"] for x in tokens}:
                            tokens.append({"addr":t,"sym":"?","name":"?","holders":0,"source":"rpc-pool"})
        print(f"📡 + rpc pools (last {latest-from_block} blocks): {len(tokens)} total")

    # 4. Dedupe + check DexScreener untuk MC/liq/vol
    seen=set(); unique=[]
    for t in tokens:
        if t["addr"] not in seen:
            seen.add(t["addr"]); unique.append(t)
    tokens=unique
    print(f"\n📡 total unique: {len(tokens)} token robinhood")

    # Ambil DexScreener data untuk semua token
    batch_size=25
    enriched=[]
    for i in range(0,len(tokens),batch_size):
        batch=tokens[i:i+batch_size]
        addrs=[t["addr"] for t in batch]
        pair_data=dex_token(",".join(addrs))
        pairs_by={}
        for p in pair_data: pairs_by.setdefault(p.get("baseToken",{}).get("address","").lower(),[]).append(p)
        for t in batch:
            a=t["addr"]
            ps=pairs_by.get(a,[])
            # pick highest liquidity pair
            best=max(ps,key=lambda x:float(x.get("liquidity",{}).get("usd") or 0)) if ps else None
            if best:
                mc=float(best.get("marketCap") or 0)
                liq=float(best.get("liquidity",{}).get("usd") or 0)
                vol=float(best.get("volume",{}).get("h24") or 0)
                px24=float(best.get("priceChange",{}).get("h24") or 0)
                px6=float(best.get("priceChange",{}).get("h6") or 0)
                px1=float(best.get("priceChange",{}).get("h1") or 0)
                sym=best.get("baseToken",{}).get("symbol") or t["sym"]
                tx24=best.get("txns",{}).get("h24",{}) or {}
                pair_url=f"https://dexscreener.com/robinhood/{best.get('pairAddress')}"
                enriched.append({"addr":a,"sym":sym,"mc":mc,"liq":liq,"vol":vol,"px24":px24,"px6":px6,
                                 "px1":px1,"tx24":tx24,"holders":t["holders"],"source":t["source"],
                                 "url":pair_url})
            else:
                enriched.append({"addr":a,"sym":t["sym"],"mc":0,"liq":0,"vol":0,"holders":t["holders"],
                                 "source":t["source"],"url":""})
        time.sleep(1)

    # 5. Filter: MC < max (ada data), liq >= min
    candidates=[r for r in enriched if 0<r["mc"]<=args.max_mc and r["liq"]>=args.min_liq]
    candidates.sort(key=lambda r: -r["mc"])

    print("\n"+"="*108)
    print(f"🎯 ROBINHOOD CHAIN SCAN — MC ≤ ${fmt(args.max_mc)} | liq ≥ ${fmt(args.min_liq)} | {len(candidates)} kandidat")
    print("="*108)
    if not candidates:
        print("  (tidak ada yang lolos filter)")
        print("\n📋 Full scan (semua token yang ada datanya di DexScreener):")
        print(f" {'#':<2} {'sym':<12} {'MC($)':<10} {'liq($)':<10} {'vol24($)':<11} {'v/mc':<5} {'6h':>6} {'24h':>7} {'source':<12}")
        print("-"*108)
        for i,r in enumerate(sorted(enriched,key=lambda x:-x["mc"])[:30],1):
            if r["mc"]==0 and r["liq"]==0: continue
            vmc=r["vol"]/r["mc"] if r["mc"]>0 else 0
            print(f" {i:<2} {r['sym'][:12]:<12} {fmt(r['mc']):<10} {fmt(r['liq']):<10} {fmt(r['vol']):<11} {vmc:<5.1f} {r['px6']:>+6.1f}% {r['px24']:>+7.1f}% {r['source']:<12}")
        sys.exit(0)

    # 6. Score & ranking
    for r in candidates:
        vmc=r["vol"]/r["mc"] if r["mc"]>0 else 0
        sc=0
        sc+=min(20,min(20,(5_000_000-r["mc"])/1_000_000))  # earlier = better
        sc+=min(15,vmc*8)                                   # volume active
        sc+=min(15,r["px6"]/6) if r["px6"]>0 else 0         # momentum
        sc+=min(10,r["liq"]/100_000)                         # liquidity depth
        sc+=min(5,r["holders"]/100) if r["holders"] else 0  # holders
        r["score"]=round(sc,1); r["vmc"]=round(vmc,2)

    candidates.sort(key=lambda r:-r["score"])

    print(f" {'#':<2} {'sym':<12} {'score':<6} {'MC($)':<10} {'liq($)':<10} {'vol24($)':<11} {'v/mc':<5} {'6h':>6} {'24h':>7} {'source':<12}")
    print("-"*108)
    for i,r in enumerate(candidates[:15],1):
        print(f" {i:<2} {r['sym'][:12]:<12} {r['score']:<6} {fmt(r['mc']):<10} {fmt(r['liq']):<10} {fmt(r['vol']):<11} {r['vmc']:<5.1f} {r['px6']:>+6.1f}% {r['px24']:>+7.1f}% {r['source']:<12}")

    print("\n🔍 DETAIL TOP 5:")
    for r in candidates[:5]:
        x3ok="✅" if r["liq"]>=50_000 and r["mc"]*3<=50_000_000 else "⚠️"
        pot3x=15_000_000/r["mc"] if r["mc"]>0 else 0
        print(f"\n  ● {r['sym']} — score {r['score']} — MC ${fmt(r['mc'])} → 3x=${fmt(r['mc']*3)} {x3ok}")
        print(f"    liq ${fmt(r['liq'])} | vol24 ${fmt(r['vol'])} (v/mc {r['vmc']:.1f}x) | 1h {r['px1']:+.1f}% | 6h {r['px6']:+.1f}% | 24h {r['px24']:+.1f}%")
        print(f"    holders {r['holders']} | source: {r['source']}")
        print(f"    potensi 3x ke 15M: {pot3x:.1f}x")
        print(f"    CA: {r['addr']}  |  {r['url']}")

    if args.json: print("\n"+json.dumps({"candidates":candidates[:15]},indent=2))

if __name__=="__main__":
    main()