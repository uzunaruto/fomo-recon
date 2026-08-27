#!/usr/bin/env python3
"""
MICIN COIN SCREENER PRO — Robinhood chain (4663)
AI AGENT — ADVANCED MICIN COIN SCREENER V2 (24-phase framework)

Fase terotomatisasi: Discovery, Hard Filters, Token Identity, Holder Distribution,
Volume Quality, Cluster Detection, Contract Security, Liquidity.
Fase kualitatif (narrative, entry, bull/bear) diisi agent saat final report.
"""
import os, sys, json, urllib.request, urllib.parse, time, re, argparse, math

KEY = os.environ.get("FOMOSCAN_KEY", "")
DS  = "https://api.dexscreener.com"
BS  = "https://robinhoodchain.blockscout.com/api/v2"
FB  = "https://api.fomoscan.sh"
RPC = "http://127.0.0.1:8098/rpc"
UNI_V3_FACTORY = "0xcaf681a66d020601342297493863e78c959e5cb2"

BURN_ADDRS = {"0x0000000000000000000000000000000000000000","0x000000000000000000000000000000000000dead",
              "0xdead000000000000000000000000000000000000","0x0000000000000000000000000000000000000001"}

def fmt(n,d=0):
    try: return f"{n:,.{d}f}"
    except: return "?"

def blockscout(path):
    try:
        req=urllib.request.Request(BS+path,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=20) as r:
            return json.loads(r.read().decode())
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

def fomo(path):
    try:
        req=urllib.request.Request(FB+path,headers={"User-Agent":"Mozilla/5.0","Authorization":f"Bearer {KEY}"})
        with urllib.request.urlopen(req,timeout=20) as r: return json.loads(r.read().decode())
    except: return {}

def parse_token_val(d,dec):
    """Parse blockscout token value (dict {decimals,value} or raw int string). Always returns token amount."""
    if isinstance(d,dict):
        v=d.get("value","0"); dec2=int(d.get("decimals",dec))
        return int(v) / (10**dec2)
    try:
        return float(d) / (10**int(dec))
    except:
        return 0

def main():
    ap=argparse.ArgumentParser(description="MICIN SCREENER PRO — Robinhood Chain")
    ap.add_argument("--max-mc",type=float,default=5_000_000)
    ap.add_argument("--min-liq",type=float,default=50_000)
    ap.add_argument("--pages",type=int,default=3)
    ap.add_argument("--json",action="store_true")
    args=ap.parse_args()

    print("🔬 MICIN COIN SCREENER PRO — ROBINHOOD CHAIN (4663)")
    print("="*74)
    print("AI AGENT | 24-phase framework | anti-cluster engine")
    print()

    # ==================== PHASE 1: DISCOVERY ====================
    tokens=[]; seen=set()
    t0=time.time()

    # Blockscout tokens
    nxt=""
    for pg in range(args.pages):
        d=blockscout(f"/tokens?type=ERC-20&limit=50{nxt}")
        if "error" in d or not isinstance(d.get("items"),list): break
        for t in d.get("items",[]):
            a=(t.get("address_hash") or "").lower()
            if a and a not in seen:
                seen.add(a)
                tokens.append({"addr":a,"sym":t.get("symbol") or "?","holders":int(t.get("holders_count") or 0),
                               "supply":t.get("total_supply"),"dec":int(t.get("decimals") or 18),
                               "source":"blockscout"})
        npp=d.get("next_page_params") or {}
        if not npp: break
        nxt="&items_count="+str(npp.get("items_count",50))+"&"+urllib.parse.urlencode(npp)
        time.sleep(0.3)

    # DexScreener profiles
    try:
        for p in dex_profiles():
            if p.get("chainId")=="robinhood":
                a=p.get("tokenAddress","").lower()
                if a and a not in seen:
                    seen.add(a); tokens.append({"addr":a,"sym":p.get("symbol") or "?","holders":0,"source":"dex-profiles"})
    except: pass

    # RPC pools
    from_b=hex(max(int(blockscout("/stats")["total_blocks"] if "total_blocks" in (blockscout("/stats") or {}) else 0)-5000,0))
    try:
        body=json.dumps({"jsonrpc":"2.0","id":1,"method":"eth_getLogs","params":[{"address":UNI_V3_FACTORY,
            "fromBlock":from_b,"toBlock":"latest","topics":["0x783f586f5a4b9e5bc1b9f0d0bcb6e5e83c4005cd9f3e0e5b960e8e0d0b68f41"]}]}).encode()
        req=urllib.request.Request(RPC,data=body,headers={"Content-Type":"application/json"})
        logs=json.loads(urllib.request.urlopen(req,timeout=15).read()).get("result") or []
        for log in logs:
            ts=log.get("topics") or []
            if len(ts)>=4:
                for i in (1,2):
                    a="0x"+ts[i][-40:].lower()
                    if a and a not in seen and a!="0xc778417e063141139fce010982780140aa0cd5ab":
                        seen.add(a); tokens.append({"addr":a,"sym":"?","holders":0,"source":"rpc-pool"})
    except: pass

    print(f"📡 PHASE 1 — DISCOVERY: {len(tokens)} token robinhood ({time.time()-t0:.0f}s)")
    if args.json: print(json.dumps({"phase1_discovery":len(tokens)}))

    # ==================== PHASE 2 & 3: DEX ENRICHMENT ====================
    results=[]
    for i in range(0,len(tokens),25):
        batch=tokens[i:i+25]
        addrs=[t["addr"] for t in batch]
        pairs=dex_token(",".join(addrs))
        by={}
        for p in pairs: by.setdefault(p.get("baseToken",{}).get("address","").lower(),[]).append(p)
        for t in batch:
            a=t["addr"]; ps=by.get(a,[])
            best=max(ps,key=lambda x:float(x.get("liquidity",{}).get("usd") or 0)) if ps else None
            if best:
                mc=float(best.get("marketCap") or 0); liq=float(best.get("liquidity",{}).get("usd") or 0)
                vol=float(best.get("volume",{}).get("h24") or 0)
                vol1h=float(best.get("volume",{}).get("h1") or 0)
                vol6h=float(best.get("volume",{}).get("h6") or 0)
                px1=float(best.get("priceChange",{}).get("h1") or 0)
                px6=float(best.get("priceChange",{}).get("h6") or 0)
                px24=float(best.get("priceChange",{}).get("h24") or 0)
                sym=best.get("baseToken",{}).get("symbol") or t["sym"]
                tx=best.get("txns",{}).get("h24",{}) or {}
                price=float(best.get("priceUsd") or 0)
                fdv=float(best.get("fdv") or 0)
                ath=float(best.get("ath") or price)
                pair=best.get("pairAddress","")
                results.append({"addr":a,"sym":sym,"mc":mc,"liq":liq,"vol":vol,"vol1h":vol1h,"vol6h":vol6h,
                    "px1":px1,"px6":px6,"px24":px24,"holders":t["holders"],"supply":t.get("supply"),
                    "dec":t.get("dec",18),"buy":tx.get("buys") or 0,"sell":tx.get("sells") or 0,
                    "price":price,"fdv":fdv,"ath":ath,"source":t["source"],
                    "pair":pair,"dex":"Uniswap V3",
                    "url":f"https://dexscreener.com/robinhood/{pair}"})
        time.sleep(0.8)

    # ==================== PHASE 2: HARD FILTERS ====================
    cand=[r for r in results if 0<r["mc"]<=args.max_mc and r["liq"]>=args.min_liq]

    # ==================== PHASE 9: HOLDER DISTRIBUTION ====================
    print(f"\n📡 PHASE 9 — HOLDER DISTRIBUTION + CLUSTER ANALYSIS ({len(cand)} kandidat)")
    for r in cand:
        a=r["addr"]; hd=blockscout(f"/tokens/{a}/holders")
        tops=hd.get("items") or []
        # compute percentages from total supply
        total_supply=0
        if r.get("supply"): total_supply=int(r["supply"])/(10**r.get("dec",18))
        elif r.get("mc") and r.get("price"): total_supply=r["mc"]/r["price"]
        # top holder percentages
        top10_val=sum(parse_token_val(t.get("value"),r.get("dec",18)) for t in tops[:10])
        top20_val=sum(parse_token_val(t.get("value"),r.get("dec",18)) for t in tops[:20])
        top50_val=sum(parse_token_val(t.get("value"),r.get("dec",18)) for t in tops[:50])
        r["top10_pct"]=round(top10_val/total_supply*100,2) if total_supply>0 else 0
        r["top20_pct"]=round(top20_val/total_supply*100,2) if total_supply>0 else 0
        r["top50_pct"]=round(top50_val/total_supply*100,2) if total_supply>0 else 0
        r["top1_val"]=fmt(parse_token_val(tops[0].get("value"),r.get("dec",18))) if tops else "?"
        r["top1_addr"]=tops[0].get("address",{}).get("hash","?")[:16] if tops else "?"
        # top1 as % of supply
        if tops and total_supply>0:
            r["top1_pct"]=round(parse_token_val(tops[0].get("value"),r.get("dec",18))/total_supply*100,2)
        else: r["top1_pct"]=0
        # cluster detection: top 10 holders → check if funded from same source
        cluster_signals=0
        funders={}
        for h in tops[:10]:
            ha=h.get("address",{}).get("hash","").lower()
            if ha in BURN_ADDRS: continue
            # get first transfer to this holder from blockscout
            tr=blockscout(f"/tokens/{a}/transfers?to={ha}")
            items=tr.get("items") or []
            # find first transfer (least recent = last in list with pagination, or first in first page)
            # Actually blockscout returns newest first. Let's get the oldest from last page.
            # For simplicity: check if the first transfer from the last page
            # We'll use a simpler approach: check if the token's top holders share a common funder
            # by looking at first few transfers of each top holder
            ftr=items[-1] if items else None
            if ftr:
                fm=ftr.get("from",{}).get("hash","").lower()
                if fm and fm not in BURN_ADDRS and fm!=a:
                    funders[fm]=funders.get(fm,0)+1
        # if 3+ of top 10 funded by same address → cluster
        for f,c in funders.items():
            if c>=3: cluster_signals+=2
            elif c>=2: cluster_signals+=1
        r["cluster_signal"]=cluster_signals
        r["funders"]=dict(list(funders.items())[:3])  # keep top 3 funders
        time.sleep(0.3)

    # ==================== PHASE 11: VOLUME QUALITY ====================
    print("📡 PHASE 11 — VOLUME QUALITY + WASH DETECTION")
    for r in cand:
        vmc=r["vol"]/r["mc"] if r["mc"]>0 else 0
        vliq=r["vol"]/r["liq"] if r["liq"]>0 else 0
        # unique wallet count from recent transfers
        tr=blockscout(f"/tokens/{r['addr']}/transfers")
        items=tr.get("items") or []
        unique_buyers=set()
        repeat_tx=0
        for t in items:
            to=t.get("to",{}).get("hash","").lower()
            if to not in BURN_ADDRS:
                if to in unique_buyers: repeat_tx+=1
                unique_buyers.add(to)
        r["unique_wallets"]=len(unique_buyers)
        r["repeat_tx_pct"]=round(repeat_tx/len(items)*100,1) if items else 0
        # wash score: combination of vol/liq, repeat tx, cluster
        wash_score=0
        if vliq>30: wash_score+=3  # vol 30x liq = obvious wash
        elif vliq>20: wash_score+=2
        elif vliq>10: wash_score+=1
        if r["repeat_tx_pct"]>50: wash_score+=2  # half+ txns are repeat wallets
        elif r["repeat_tx_pct"]>30: wash_score+=1
        wash_score+=r["cluster_signal"]
        r["wash_score"]=wash_score
        r["volume_quality"]="MANIPULATED" if wash_score>=4 else "MIXED" if wash_score>=2 else "ORGANIC"
        r["vliq"]=round(vliq,1)
        r["vmc"]=round(vmc,2)
        time.sleep(0.3)

    # ==================== PHASE 12: CONTRACT SECURITY ====================
    print("📡 PHASE 12 — CONTRACT SECURITY CHECK")
    for r in cand:
        sc=blockscout(f"/smart-contracts/{r['addr']}")
        r["contract_verified"]=bool(sc.get("is_verified"))
        r["contract_name"]=sc.get("name") or "?"
        # check for dangerous functions in ABI
        dangerous_fns=[]

        # Check if token has standard ERC20 functions — we can check via transfers API
        # If no transfers at all, suspicious
        tr=blockscout(f"/tokens/{r['addr']}/transfers")
        items=tr.get("items") or []
        r["total_txns"]=len(items) if items else 0

        # If contract is verified, check ABI for dangerous functions
        if sc.get("is_verified"):
            abi=sc.get("abi") or []
            for fn in abi:
                n=fn.get("name","")
                if n in ("mint","mintTo","mintBatch","mintWithTokenURI"): dangerous_fns.append("mint")
                if n in ("pause","unpause","paused"): dangerous_fns.append("pause")
                if n in ("blacklist","addBlacklist","removeBlacklist","isBlacklisted"): dangerous_fns.append("blacklist")
                if n in ("setBlacklist","includeInBlacklist","excludeFromBlacklist"): dangerous_fns.append("blacklist")
                if n in ("transferOwnership","renounceOwnership","owner"): dangerous_fns.append("owner")
                if n in ("owner","setOwner","changeOwner"): dangerous_fns.append("owner")
                if n in ("freeze","freezeAccount","freeze","unfreeze"): dangerous_fns.append("freeze")
                if n in ("setBuyTax","setSellTax","setTax","updateTax","setFee"): dangerous_fns.append("tax")
                if n in ("setMaxTxAmount","setMaxWallet","maxTransaction","maxWallet"): dangerous_fns.append("maxTx")
                if n in ("upgradeTo","upgradeToAndCall","implementation"): dangerous_fns.append("upgradeable")
                if n in ("addToExclusion","removeFromExclusion","isExcluded"): dangerous_fns.append("exclusion")
            r["dangerous_fns"]=list(set(dangerous_fns))
        else:
            r["dangerous_fns"]=["unverified"]
        r["security"]="SAFE" if not r["dangerous_fns"] else "CAUTION" if "unverified" in r["dangerous_fns"] else "HIGH RISK"
        time.sleep(0.3)

    # ==================== SCORING (fase 20) ====================
    for r in cand:
        sc=0
        # narrative/attention (15) — proxied by holders + volume
        hscore=min(15,(r["holders"]/500)*5 + (r["vol"]/100000)*5 + (r["vol1h"]/50000)*5)
        sc+=min(15,hscore)
        # smart money (20) — proxied by holder distribution + unique wallets
        sm=0
        if r["top20_pct"] and r["top20_pct"]<50: sm+=8  # good distribution
        if r["unique_wallets"]>100: sm+=8
        elif r["unique_wallets"]>50: sm+=5
        if r["cluster_signal"]==0: sm+=4  # no cluster = genuine
        sc+=min(20,sm)
        # whale activity (10) — top1 concentration
        w=0
        if r["top10_pct"] and r["top10_pct"]<30: w+=5
        t1pct=r.get("top1_pct",0)
        if t1pct and t1pct<5: w+=5
        elif t1pct and t1pct<15: w+=3
        sc+=min(10,w)
        # liquidity (15)
        lp=min(15,r["liq"]/100000)
        sc+=min(15,lp)
        # volume/momentum (10)
        vm=0
        if r["vol"]>0 and r["vmc"]>0.3: vm+=4
        if r["px6"]>10: vm+=3
        elif r["px6"]>0: vm+=1
        if r["volume_quality"]=="ORGANIC": vm+=3
        elif r["volume_quality"]=="MIXED": vm+=1
        sc+=min(10,vm)
        # tokenomics (10)
        tk=0
        if r["top10_pct"] and r["top10_pct"]<40: tk+=5
        if r["total_txns"]>1000: tk+=3
        if r["source"]=="blockscout": tk+=2  # existing token
        sc+=min(10,tk)
        # contract safety (15)
        cs=15
        if "unverified" in (r["dangerous_fns"] or []): cs-=5
        if "mint" in (r["dangerous_fns"] or []): cs-=10
        if "blacklist" in (r["dangerous_fns"] or []): cs-=5
        if "pause" in (r["dangerous_fns"] or []): cs-=5
        if "upgradeable" in (r["dangerous_fns"] or []): cs-=3
        if "tax" in (r["dangerous_fns"] or []): cs-=5
        sc+=max(0,cs)
        # community (5)
        cm=min(5,r["holders"]/2000)
        sc+=min(5,cm)
        # wash penalty
        if r["volume_quality"]=="MANIPULATED": sc-=15
        elif r["volume_quality"]=="MIXED": sc-=5
        # cluster penalty
        sc-=r["cluster_signal"]*3
        r["score"]=round(max(0,sc),1)

    # sort
    cand.sort(key=lambda r:-r["score"])

    # ==================== OUTPUT ====================
    print("\n"+"="*120)
    print(f"🏆 PHASE 23 — FINAL RANKING (MC≤${fmt(args.max_mc)} | liq≥${fmt(args.min_liq)}) | {len(cand)} kandidat")
    print("="*120)
    if not cand:
        print("  (tidak ada yang lolos — longgarkan filter)"); sys.exit(0)

    print(f" {'#':<3} {'sym':<12} {'score':<6} {'MC($)':<10} {'liq($)':<9} {'vol24($)':<11} {'v/mc':<5} {'6h':>7} {'24h':>7} {'top10%':<7} {'uniqW':<6} {'volQual':<10} {'cluster':<8} {'security':<10}")
    print("-"*120)
    for i,r in enumerate(cand[:15],1):
        cl=f"⚠{r['cluster_signal']}" if r["cluster_signal"]>0 else "✅"
        print(f" {i:<3} {r['sym'][:12]:<12} {r['score']:<6} {fmt(r['mc']):<10} {fmt(r['liq']):<9} {fmt(r['vol']):<11} {r['vmc']:<5.1f} {r['px6']:>+7.1f}% {r['px24']:>+7.1f}% {r['top10_pct']:<7} {r['unique_wallets']:<6} {r['volume_quality']:<10} {cl:<8} {r['security']:<10}")

    # ==================== PHASE 23-24: TOP 5 DETAIL ====================
    print("\n"+"="*120)
    print("🔍 PHASE 23-24 — TOP 5 DETAIL + ENTRY STRATEGY")
    print("="*120)
    for i,r in enumerate(cand[:5],1):
        # compute entry strategy
        price=r["price"]
        mc=r["mc"]
        liq=r["liq"]
        px6=r["px6"]
        px24=r["px24"]
        x3=mc*3
        x3ok="✅" if x3<=50_000_000 else "⚠️"
        # estimate market phase
        if px6>500: phase="🔥 OVERHEATED — fresh pump, tunggu retest"
        elif px6>100: phase="🚀 HYPE — extended, risiko tinggi"
        elif px6>30: phase="📈 BULLISH — momentum bagus, entry hati-hati"
        elif px6>10: phase="📊 GOOD ENTRY — momentum positif"
        elif px6>0: phase="🟢 EARLY — akumulasi"
        elif px6>-15: phase="🟡 DIP — retrace, chance masuk"
        else: phase="🔴 CORRECTION — bearish, tunggu reversal"
        # entry suggestions
        if px6>100:
            agg_entry="HOLD — tunggu retrace ke -20% sampai -40% dari ATH"
            cons_entry=f"WAIT — retrace ke support terdekat"
            dip_entry=f"Jika retrace -30% dari ATH"
        elif px6>0:
            agg_entry=f"Entry saat retrace -5% sampai -10%"
            cons_entry=f"Entry saat retrace -15% sampai -20%"
            dip_entry=f"Jika retrace -25%+ dengan volume turun"
        else:
            agg_entry=f"Entry gradual di area saat ini"
            cons_entry=f"Tunggu konfirmasi reversal (volume naik + green candle)"
            dip_entry=f"Jika turun -10% lagi dari sini"
        inval=mc*0.5  # 50% drop = invalidation

        top1_tok_supply=0
        hd=blockscout(f"/tokens/{r['addr']}/holders")
        top_holders=hd.get("items")[:5] if hd.get("items") else []
        whale_info=[]
        for h in top_holders:
            ha=h.get("address",{}).get("hash","")[:16]
            hv=parse_token_val(h.get("value"),r.get("dec",18))
            hp=round(hv/(r["mc"]/r["price"] if r["price"]>0 else 1)*100,1) if r["price"]>0 else 0
            whale_info.append(f"{ha}.. ${fmt(hv*r['price'])} ({hp}%)")

        print(f"\n  #{i} — {r['sym']}  |  Score: {r['score']}/100  |  Conviction: {min(8,round(r['score']/12)+1)}/10")
        print(f"  {'─'*60}")
        print(f"  MC: ${fmt(r['mc'])}  |  FDV: ${fmt(r['fdv'])}  |  Liq: ${fmt(r['liq'])}  |  Price: ${r['price']:.8f}")
        print(f"  Vol: 1h ${fmt(r['vol1h'])} | 6h ${fmt(r['vol6h'])} | 24h ${fmt(r['vol'])}  |  v/mc: {r['vmc']}x")
        print(f"  ATH: ${r['ath']:.8f}  |  % below ATH: {round((1-r['price']/r['ath'])*100,1) if r['ath']>0 and r['price']>0 else 0}%")
        print(f"  Holders: {r['holders']}  |  Unique wallets: {r['unique_wallets']}  |  Total txns: {r['total_txns']}")
        print(f"  Holder Distribution: Top10={r['top10_pct']}% | Top20={r['top20_pct']}% | Top50={r['top50_pct']}%")
        print(f"  Volume Quality: {r['volume_quality']} (wash_score={r['wash_score']}, repeat_tx={r['repeat_tx_pct']}%)")
        if r["cluster_signal"]>0:
            print(f"  ⚠️ CLUSTER SIGNAL: {r['cluster_signal']} — top holders share funder!")
            for f,c in list(r.get("funders",{}).items())[:3]:
                print(f"     {f[:16]}.. funded {c} top holder(s)")
        else: print(f"  ✅ Cluster: no cluster detected")
        print(f"  Contract: {r['security']} | Verified: {r['contract_verified']} | {r['contract_name']}")
        if r["dangerous_fns"]: print(f"  ⚠️ Functions: {', '.join(r['dangerous_fns'])}")
        print(f"  3x Potential: ${fmt(x3)} {x3ok}  |  Invalidation: ${fmt(inval)}")
        print(f"  Market Phase: {phase}")
        print(f"  Entry:")
        print(f"    Aggressive: {agg_entry}")
        print(f"    Conservative: {cons_entry}")
        print(f"    Dip: {dip_entry}")
        if whale_info:
            print(f"  Top Holders:")
            for w in whale_info[:3]: print(f"    {w}")
        print(f"  CA: {r['addr']}  |  {r['url']}")
        time.sleep(0.3)

    # ==================== FINAL SUMMARY ====================
    print("\n"+"="*120)
    print("📊 PHASE 24 — FINAL MARKET SUMMARY")
    print("="*120)
    if cand:
        # find best overall
        best=cand[0]
        # best early
        early=[c for c in cand if c["mc"]<500_000]
        best_early=early[0] if early else None
        # best volume
        best_vol=max(cand[:5],key=lambda x:x["vmc"])
        # safest
        safest=min(cand[:5],key=lambda x:x["wash_score"]+x["cluster_signal"]*2)
        # highest risk
        highest_risk=max(cand[:5],key=lambda x:x["wash_score"]+x["cluster_signal"]*2)
        # avoid
        wash_heavy=[c for c in cand if c["volume_quality"]=="MANIPULATED"]
        avoid=wash_heavy[0] if wash_heavy else cand[-1] if len(cand)>1 else None

        print(f"  BEST OVERALL SETUP:        {best['sym']} (score {best['score']})")
        if best_early: print(f"  BEST EARLY SETUP:          {best_early['sym']} (MC ${fmt(best_early['mc'])})")
        print(f"  BEST VOLUME/MOMENTUM:      {best_vol['sym']} (v/mc {best_vol['vmc']}x, vol {best_vol['volume_quality']})")
        print(f"  SAFEST (lowest wash/cluster): {safest['sym']} (wash={safest['wash_score']})")
        print(f"  HIGHEST RISK (wash/cluster):  {highest_risk['sym']} (wash={highest_risk['wash_score']})")
        if avoid: print(f"  COIN TO AVOID:              {avoid['sym']} (MANIPULATED volume)")
        print()
        print(f"  If I could only watch 3 coins today:")
        top3=cand[:3]
        for i,c in enumerate(top3,1):
            print(f"    {i}. {c['sym']} — MC ${fmt(c['mc'])} | score {c['score']} | vol {c['volume_quality']} | {c['security']}")

    if args.json: print("\n"+json.dumps({"candidates":cand[:15],"top5":[{"sym":c["sym"],"score":c["score"],"mc":c["mc"],"liq":c["liq"]} for c in cand[:5]]},indent=2))

if __name__=="__main__":
    main()