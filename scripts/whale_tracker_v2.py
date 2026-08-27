#!/usr/bin/env python3
"""
FOMO Whale Tracker v2 — rekomendasi coin early yang dibeli smart money.
Berdasarkan thesis feed: siapa yang call token + berapa uang mereka di situ.

Score logic:
  - HoldingsUsd (berapa $ yang dipertaruhkan) → bobot besar
  - Realized PnL (udah profit brp) → smart money signal
  - Jumlah author beda yang call token → conviction
  - DexScreener MC/liq → early + aman
  - AuthorIsDev flag → avoid dev-pump
"""
import os, sys, json, time, urllib.request, argparse, datetime

KEY = os.environ.get("FOMOSCAN_KEY", "")

TRACKED_WHALES = {
    "ether_monk":"WHALE pnl 2.0M","Aurelius0121":"WHALE pnl 1.5M",
    "change":"WHALE vol 22M","unipcs":"WHALE pnl 1.9M",
    "DumbCrayonEater":"WHALE pnl 2.0M","PoorGoat_":"WHALE flw 485K",
    "Quanterty":"WHALE flw 235K",
}

def fomo(path):
    req=urllib.request.Request("https://api.fomoscan.sh"+path,headers={"User-Agent":"Mozilla/5.0","Authorization":f"Bearer {KEY}"})
    try:
        with urllib.request.urlopen(req,timeout=20) as r: return r.status,json.loads(r.read().decode())
    except urllib.error.HTTPError as e: return e.code,{}
    except Exception: return 0,{}

def dex(tokens):
    q=",".join(tokens[:30])
    try:
        req=urllib.request.Request(f"https://api.dexscreener.com/latest/dex/tokens/{q}",headers={"User-Agent":"Mozilla/5.0"})
        return json.loads(urllib.request.urlopen(req,timeout=20).read()).get("pairs",[])
    except Exception: return []

def fmt(n,d=0):
    try: return f"{n:,.{d}f}"
    except: return "?"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--max-mc",type=float,default=30_000_000)
    ap.add_argument("--min-liq",type=float,default=5_000)
    ap.add_argument("--json",action="store_true")
    args=ap.parse_args()

    c,d=fomo("/v2/thesis")
    if c!=200: print("❌ thesis gagal, cek key/quota"); sys.exit(1)
    items=d.get("data") or d.get("items") or (d if isinstance(d,list) else [])
    print(f"📡 thesis: {len(items)} entries")

    # group by token
    bytok={}
    for it in items:
        tok=it.get("tokenAddress") or ""; sym=it.get("tokenSymbol") or ""
        if not tok: continue
        a=it.get("authorHandle") or "?"
        e=bytok.setdefault(tok,{"symbol":sym,"network":it.get("tokenNetwork"),"callers":[],"totalHoldings":0,"totalPnl":0,"authorSet":set()})
        if a not in e["authorSet"]:
            e["authorSet"].add(a)
            h=float(it.get("holdingsUsd") or 0); p=float(it.get("realizedPnlUsd") or 0)
            e["totalHoldings"]+=h; e["totalPnl"]+=p
            e["callers"].append({"handle":a,"holdings":h,"pnl":p,"dev":it.get("authorIsDev"),
                                 "text":(it.get("thesis") or "")[:80]})

    print(f"  → {len(bytok)} token unik dengan thesis call")

    # fetch DexScreener for all tokens
    pairs=dex(list(bytok.keys()))
    bypair={}
    for p in pairs: bypair.setdefault(p.get("baseToken",{}).get("address",""),[]).append(p)

    rows=[]
    for tok,e in bytok.items():
        ps=bypair.get(tok,[])
        p=max(ps,key=lambda x:float(x.get("liquidity",{}).get("usd") or 0)) if ps else None
        mc=float(p.get("marketCap") or 0) if p else 0
        liq=float(p.get("liquidity",{}).get("usd") or 0) if p else 0
        vol=float(p.get("volume",{}).get("h24") or 0) if p else 0
        px5=float(p.get("priceChange",{}).get("m5") or 0) if p else 0
        px1=float(p.get("priceChange",{}).get("h1") or 0) if p else 0
        sym=(p.get("baseToken",{}).get("symbol") or e["symbol"]) if p else e["symbol"]
        chain=(p.get("chainId") or e.get("network") or "?") if p else e.get("network") or "?"
        url=f"https://dexscreener.com/{chain}/{tok}" if p else ""

        # smart money score
        sc=0
        sc+=min(30, e["totalHoldings"]/10)          # $ holdings = bobot
        sc+=min(20, e["totalPnl"]/5) if e["totalPnl"]>0 else 0
        sc+=min(15, len(e["callers"])*5)             # multiple callers = conviction
        sc+=max(0, 20-(mc/1_000_000)*2) if mc>0 else 0  # early bonus
        sc+=min(10, vol/mc*2) if mc>0 else 0         # volume aktivitas
        sc+=10 if any(c["handle"] in TRACKED_WHALES for c in e["callers"]) else 0
        tracked=[c for c in e["callers"] if c["handle"] in TRACKED_WHALES]
        sc=round(sc,1)

        if mc>0 and mc<=args.max_mc and liq>=args.min_liq:
            rows.append({"tok":tok,"sym":sym,"chain":chain,"mc":mc,"liq":liq,"vol":vol,
                         "5m":px5,"1h":px1,"score":sc,"url":url,
                         "callers":e["callers"],"totalHoldings":e["totalHoldings"],
                         "totalPnl":e["totalPnl"],"tracked":tracked})

    rows.sort(key=lambda r:-r["score"])

    print("\n"+"="*100)
    print(f"🎯 EARLY SMART-MONEY COINS — live dari thesis feed (MC ≤ ${fmt(args.max_mc)})")
    print("="*100)
    if not rows:
        print("  (tidak ada yang lolos filter)")
        return
    print(f" {'#':<2} {'sym':<10} {'score':<6} {'MC($)':<11} {'liq($)':<9} {'vol24($)':<10} {'5m':>6} {'1h':>7}  callers")
    print("-"*100)
    for i,r in enumerate(rows[:20],1):
        w="🔒" if r["tracked"] else " "
        print(f" {i:<2}{w} {r['sym'][:10]:<10} {r['score']:<6} {fmt(r['mc']):<11} {fmt(r['liq']):<9} {fmt(r['vol']):<10} {r['5m']:>+6.1f}% {r['1h']:>+7.1f}%  {','.join(c['handle'] for c in r['callers'][:5])}")

    print("\n🔍 DETAIL TOP 5:")
    for r in rows[:5]:
        w="🔒WHALE" if r["tracked"] else "—"
        print(f"\n  ● {r['sym']} ({r['chain']}) — score {r['score']} — MC ${fmt(r['mc'])} | liq ${fmt(r['liq'])} | vol24 ${fmt(r['vol'])}")
        print(f"    5m {r['5m']:+.1f}% | 1h {r['1h']:+.1f}% | holdings: ${fmt(r['totalHoldings'])} | pnl: ${fmt(r['totalPnl'])}")
        if r['url']: print(f"    {r['url']}")
        # caller details
        for c in r["callers"][:3]:
            pnl_tag=f"pnl_r=${fmt(c['pnl'])}" if c['pnl'] else ""
            holdings_tag=f"hold=${fmt(c['holdings'])}" if c['holdings'] else ""
            tag="🔒" if c['handle'] in TRACKED_WHALES else "·"
            print(f"    [{tag} {c['handle']}] {pnl_tag} {holdings_tag} — {c['text'][:60]}")

    if args.json:
        print("\n"+json.dumps({"candidates":rows[:20]},indent=2))

if __name__=="__main__":
    main()