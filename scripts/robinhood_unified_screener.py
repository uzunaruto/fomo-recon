#!/usr/bin/env python3
"""
Robinhood Unified Screener — merge 2 sumber:
  1. CHAIN SCAN (blockscout + rpc + dexscreener) → base candidates + coverage luas
  2. FOMOSCAN THESIS → confirmation signal: token yang di-call whale dapat bonus score

Output: 1 list ranking gabungan. Chain scan = primary, thesis = multiplier.
"""
import os, sys, json, urllib.request, urllib.parse, time, argparse

KEY = os.environ.get("FOMOSCAN_KEY", "")
DS  = "https://api.dexscreener.com"
BS  = "https://robinhoodchain.blockscout.com/api/v2"
FB  = "https://api.fomoscan.sh"
RPC = "http://127.0.0.1:8098/rpc"
UNI_V3_FACTORY = "0xcaf681a66d020601342297493863e78c959e5cb2"

def fmt(n,d=0):
    try: return f"{n:,.{d}f}"
    except: return "?"

def blockscout(path):
    try:
        req=urllib.request.Request(BS+path,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=20) as r: return json.loads(r.read().decode())
    except: return {}

def rpc(method,params=[],retries=2):
    body=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode()
    for i in range(retries):
        try:
            req=urllib.request.Request(RPC,data=body,headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(req,timeout=20) as r:
                return json.loads(r.read().decode()).get("result")
        except Exception:
            if i<retries-1: time.sleep(1)
    return None

def fomo(path):
    try:
        req=urllib.request.Request(FB+path,headers={"User-Agent":"Mozilla/5.0","Authorization":f"Bearer {KEY}"})
        with urllib.request.urlopen(req,timeout=20) as r: return json.loads(r.read().decode())
    except: return {}

def dex_token(tok):
    try:
        req=urllib.request.Request(f"{DS}/latest/dex/tokens/{tok}",headers={"User-Agent":"Mozilla/5.0"})
        return json.loads(urllib.request.urlopen(req,timeout=15).read()).get("pairs",[])
    except: return []

def dex_profiles():
    try:
        req=urllib.request.Request(f"{DS}/token-profiles/latest/v1",headers={"User-Agent":"Mozilla/5.0"})
        return json.loads(urllib.request.urlopen(req,timeout=15).read())
    except: return []

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--max-mc",type=float,default=5_000_000)
    ap.add_argument("--min-liq",type=float,default=50_000)
    ap.add_argument("--pages",type=int,default=3)
    ap.add_argument("--json",action="store_true")
    args=ap.parse_args()

    print("🔍 ROBINHOOD UNIFIED SCREENER — chain scan + thesis whale confirmation")
    print("="*74)

    # ========== SOURCE 1: CHAIN SCAN ==========
    tokens=[]; seen=set()
    # blockscout
    nxt=""
    for _ in range(args.pages):
        d=blockscout(f"/tokens?type=ERC-20&limit=50{nxt}")
        if "error" in d or not isinstance(d.get("items"),list): break
        for t in d.get("items",[]):
            a=(t.get("address_hash") or "").lower()
            if a and a not in seen:
                seen.add(a)
                tokens.append({"addr":a,"sym":t.get("symbol") or "?","holders":int(t.get("holders_count") or 0),"source":"chain"})
        npp=d.get("next_page_params") or {}
        if not npp: break
        nxt="&"+urllib.parse.urlencode(npp); time.sleep(0.4)
    # dexscreener profiles
    try:
        for p in dex_profiles():
            if p.get("chainId")=="robinhood":
                a=p.get("tokenAddress","").lower()
                if a and a not in seen:
                    seen.add(a); tokens.append({"addr":a,"sym":p.get("symbol") or "?","holders":0,"source":"chain"})
    except: pass
    # rpc pools
    latest=rpc("eth_blockNumber")
    if latest:
        latest=int(latest,16); frm=max(latest-5000,0)
        logs=rpc("eth_getLogs",[{"address":UNI_V3_FACTORY,"fromBlock":hex(frm),"toBlock":hex(latest),
              "topics":["0x783f586f5a4b9e5bc1b9f0d0bcb6e5e83c4005cd9f3e0e5b960e8e0d0b68f41"]}])
        if logs and isinstance(logs,list):
            for log in logs:
                ts=log.get("topics") or []
                if len(ts)>=4:
                    for i in (1,2):
                        a="0x"+ts[i][-40:].lower()
                        if a and a not in seen and a!="0xc778417e063141139fce010982780140aa0cd5ab":
                            seen.add(a); tokens.append({"addr":a,"sym":"?","holders":0,"source":"chain"})
    print(f"📡 [1] chain scan: {len(tokens)} token robinhood")

    # ========== SOURCE 2: FOMOSCAN THESIS ==========
    thesis_by_tok={}
    before=None
    for _ in range(15):
        d=fomo("/v2/thesis"+("?nextBefore="+before if before else ""))
        if not d or not d.get("items"): break
        for it in d.get("items",[]):
            net=(it.get("tokenNetwork") or "").lower()
            if net!="robinhood": continue
            tok=it.get("tokenAddress","").lower()
            e=thesis_by_tok.setdefault(tok,{"callers":[],"holdings":0,"pnl":0,"theses":[]})
            h=it.get("authorHandle") or "?"
            if h not in e["callers"]: e["callers"].append(h)
            e["holdings"]+=float(it.get("holdingsUsd") or 0)
            e["pnl"]+=float(it.get("realizedPnlUsd") or 0)
            e["theses"].append(str(it.get("thesis") or "")[:100])
        before=d.get("nextBefore")
        if not d.get("hasMore"): break
        time.sleep(0.3)
    print(f"📡 [2] fomoscan thesis: {len(thesis_by_tok)} token robinhood di-call whale")

    # ========== MERGE + DEX DATA ==========
    for a in thesis_by_tok:
        if a not in seen:
            seen.add(a); tokens.append({"addr":a,"sym":"?","holders":0,"source":"thesis"})

    # enrich dengan DexScreener
    results=[]
    for i in range(0,len(tokens),25):
        batch=tokens[i:i+25]
        addrs=[t["addr"] for t in batch]
        pairs=dex_token(",".join(addrs))
        by={}
        for p in pairs: by.setdefault(p.get("baseToken",{}).get("address","").lower(),[]).append(p)
        for t in batch:
            a=t["addr"]
            ps=by.get(a,[])
            best=max(ps,key=lambda x:float(x.get("liquidity",{}).get("usd") or 0)) if ps else None
            th=thesis_by_tok.get(a)
            if best:
                mc=float(best.get("marketCap") or 0); liq=float(best.get("liquidity",{}).get("usd") or 0)
                vol=float(best.get("volume",{}).get("h24") or 0)
                px1=float(best.get("priceChange",{}).get("h1") or 0)
                px6=float(best.get("priceChange",{}).get("h6") or 0)
                px24=float(best.get("priceChange",{}).get("h24") or 0)
                sym=best.get("baseToken",{}).get("symbol") or t["sym"]
                tx=best.get("txns",{}).get("h24",{}) or {}
                results.append({"addr":a,"sym":sym,"mc":mc,"liq":liq,"vol":vol,"px1":px1,"px6":px6,
                    "px24":px24,"holders":t["holders"],"buy":tx.get("buys") or 0,"sell":tx.get("sells") or 0,
                    "callers":(th["callers"] if th else []),"hold":(th["holdings"] if th else 0),
                    "pnl":(th["pnl"] if th else 0),"theses":(th["theses"] if th else []),
                    "source":"thesis+chain" if th else "chain",
                    "url":f"https://dexscreener.com/robinhood/{best.get('pairAddress')}"})
        time.sleep(0.8)

    # ========== FILTER + SCORE ==========
    cand=[r for r in results if 0<r["mc"]<=args.max_mc and r["liq"]>=args.min_liq]
    for r in cand:
        vmc=r["vol"]/r["mc"] if r["mc"]>0 else 0
        sc=0
        sc+=min(20,min(20,(5_000_000-r["mc"])/1_000_000))   # earlier
        sc+=min(15,vmc*8)                                     # volume
        sc+=min(15,r["px6"]/6) if r["px6"]>0 else 0           # momentum
        sc+=min(10,r["liq"]/100_000)                          # liq depth
        sc+=min(8,r["holders"]/500)                           # holders
        # THESIS BONUS (whale backing)
        if r["callers"]:
            sc+=min(15,len(r["callers"])*8)                   # smart wallet count
            sc+=min(12,r["hold"]/400)                          # real money in
            sc+=min(10,r["pnl"]/300)                           # proven pnl
        r["score"]=round(sc,1); r["vmc"]=round(vmc,2)
    cand.sort(key=lambda r:-r["score"])

    print("\n"+"="*116)
    print(f"🎯 UNIFIED RANKING — MC≤${fmt(args.max_mc)} | liq≥${fmt(args.min_liq)} | {len(cand)} kandidat (bonus: whale-backed)")
    print("="*116)
    if not cand:
        print("  (tidak ada yang lolos — longgarkan filter)"); sys.exit(0)
    print(f" {'#':<3} {'sym':<12} {'sc':<5} {'MC($)':<10} {'liq($)':<9} {'vol24($)':<11} {'v/mc':<5} {'6h':>7} {'24h':>7} {'callers':<14} {'whale$':<8}")
    print("-"*116)
    for i,r in enumerate(cand[:15],1):
        wb=f"${fmt(r['hold'])}" if r["callers"] else "-"
        print(f" {i:<3} {r['sym'][:12]:<12} {r['score']:<5} {fmt(r['mc']):<10} {fmt(r['liq']):<9} {fmt(r['vol']):<11} {r['vmc']:<5.1f} {r['px6']:>+7.1f}% {r['px24']:>+7.1f}% {','.join(r['callers'][:3])[:14]:<14} {wb:<8}")

    print("\n🔍 DETAIL TOP 5:")
    for r in cand[:5]:
        tag="🐋 WHALE-BACKED" if r["callers"] else "📡 chain only"
        x3ok="✅" if r["liq"]>=50_000 and r["mc"]*3<=50_000_000 else "⚠️"
        pot3x=15_000_000/r["mc"] if r["mc"]>0 else 0
        print(f"\n  ● {r['sym']} — score {r['score']} {tag}")
        print(f"    MC ${fmt(r['mc'])} → 3x=${fmt(r['mc']*3)} {x3ok} | liq ${fmt(r['liq'])} | vol24 ${fmt(r['vol'])} (v/mc {r['vmc']:.1f}x)")
        print(f"    1h {r['px1']:+.1f}% | 6h {r['px6']:+.1f}% | 24h {r['px24']:+.1f}% | holders {r['holders']} | buy/sell {r['buy']}/{r['sell']}")
        if r["callers"]:
            print(f"    🐋 callers: {','.join(r['callers'])} | holdings ${fmt(r['hold'])} | pnl ${fmt(r['pnl'])}")
        if r["theses"]: print(f"    thesis: {r['theses'][0][:90]}")
        print(f"    CA: {r['addr']}  |  {r['url']}")

    if args.json: print("\n"+json.dumps({"candidates":cand[:15]},indent=2))

if __name__=="__main__":
    main()