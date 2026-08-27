#!/usr/bin/env python3
"""
FOMO Robinhood Early Screener v2 — cari coin robinhood chain dengan:
  ✅ MC < $5M (early)
  ✅ Smart wallet banyak (multi-caller thesis)
  ✅ Thesis kuat (scoring teks)
  ✅ Volume bagus (vol24 vs MC ratio) — TAPI tolak dust-liq / wash volume
  ✅ Potensi 3x+ (room to 15M dengan liq cukup)

v2 fix: anti-trap — ambil pair liquidity TERTINGGI (bukan asal), tolak token
yang volume-nya dari dust-liq pair (< min-liq), pilih pair utama by liquidity.
"""
import os, sys, json, time, urllib.request, argparse, re

KEY = os.environ.get("FOMOSCAN_KEY", "")
FB  = "https://api.fomoscan.sh"
DS  = "https://api.dexscreener.com/latest/dex/tokens"
MAX_PAGES = 30

POS_WORDS = ["100x","50x","10x","moon","ath","send it","road to","launch","buy","long",
             "gem","fire","rip","breakout","listing","coinbase","airdrop","earn","hold",
             "million","mc","up only","bounce","bidding","entry","fomo","pump","so early"]
NEG_WORDS = ["rug","scam","dead","dumping","sell","exit","fade","rekt","over","skip",
             "warning","honeypot","sniped","slow","no vol","boring"]

def fomo(path):
    req=urllib.request.Request(FB+path,headers={"User-Agent":"Mozilla/5.0","Authorization":f"Bearer {KEY}"})
    try:
        with urllib.request.urlopen(req,timeout=20) as r: return r.status,json.loads(r.read().decode())
    except urllib.error.HTTPError as e: return e.code,{}
    except Exception: return 0,{}

def dex(tokens):
    q=",".join(tokens[:30])
    try:
        req=urllib.request.Request(f"{DS}/{q}",headers={"User-Agent":"Mozilla/5.0"})
        return json.loads(urllib.request.urlopen(req,timeout=20).read()).get("pairs",[])
    except Exception: return []

def thesis_strength(text):
    t=(text or "").lower()
    pos=sum(1 for w in POS_WORDS if w in t)
    neg=sum(1 for w in NEG_WORDS if w in t)
    has_num=bool(re.search(r'\d+[xkm]',t))
    sc=min(20,pos*4)+ (8 if has_num else 0) - neg*10
    return max(0,sc)

def fmt(n,d=0):
    try: return f"{n:,.{d}f}"
    except: return "?"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--max-mc",type=float,default=5_000_000)
    ap.add_argument("--min-liq",type=float,default=50_000)   # anti-wash: butuh liq solid
    ap.add_argument("--min-callers",type=int,default=1)
    ap.add_argument("--min-vol-ratio",type=float,default=0.3)
    ap.add_argument("--json",action="store_true")
    args=ap.parse_args()

    all_items={}; before=None
    for _ in range(MAX_PAGES):
        c,d=fomo("/v2/thesis"+("?nextBefore="+before if before else ""))
        if c!=200: break
        items=d.get("items") or []
        if not items: break
        for it in items:
            tok=it.get("tokenAddress")
            if tok and tok not in all_items: all_items[tok]=it
        before=d.get("nextBefore")
        if not d.get("hasMore"): break
        time.sleep(0.25)

    rh=[it for it in all_items.values() if (it.get("tokenNetwork") or "").lower()=="robinhood"]
    print(f"📡 thesis: {len(all_items)} unik, robinhood: {len(rh)}")
    if not rh:
        print("  (tidak ada thesis robinhood saat ini)"); sys.exit(0)

    bytok={}
    for it in rh:
        tok=it["tokenAddress"]
        e=bytok.setdefault(tok,{"sym":it.get("tokenSymbol"),"callers":[],"holdings":0,"pnl":0,"dev_calls":0,"theses":[]})
        a=it.get("authorHandle") or "?"
        if a not in e["callers"]: e["callers"].append(a)
        e["holdings"]+=float(it.get("holdingsUsd") or 0)
        e["pnl"]+=float(it.get("realizedPnlUsd") or 0)
        if it.get("authorIsDev"): e["dev_calls"]+=1
        e["theses"].append(str(it.get("thesis") or "")[:120])

    pairs=dex(list(bytok.keys()))
    bypair={}
    for p in pairs: bypair.setdefault(p.get("baseToken",{}).get("address",""),[]).append(p)

    rows=[]
    for tok,e in bytok.items():
        ps=bypair.get(tok,[])
        if not ps: continue
        # ANTI-TRAP: pilih pair liquidity TERTINGGI sebagai sumber data
        p=max(ps,key=lambda x:float(x.get("liquidity",{}).get("usd") or 0))
        mc=float(p.get("marketCap") or 0)
        liq=float(p.get("liquidity",{}).get("usd") or 0)
        vol=float(p.get("volume",{}).get("h24") or 0)
        px24=float(p.get("priceChange",{}).get("h24") or 0)
        px6=float(p.get("priceChange",{}).get("h6") or 0)
        px1=float(p.get("priceChange",{}).get("h1") or 0)
        sym=p.get("baseToken",{}).get("symbol") or e["sym"]
        tx24=p.get("txns",{}).get("h24",{}) or {}
        buys=tx24.get("buys") or 0; sells=tx24.get("sells") or 0
        url=f"https://dexscreener.com/robinhood/{p.get('pairAddress')}"

        tsc=sum(thesis_strength(t) for t in e["theses"])/max(1,len(e["theses"]))
        n_callers=len(e["callers"]); vol_ratio=vol/mc if mc>0 else 0

        if e["dev_calls"]>0 and n_callers==1: continue   # dev-only = rug risk
        if not (0<mc<=args.max_mc): continue
        if liq<args.min_liq: continue                     # anti-wash trap
        if n_callers<args.min_callers: continue
        if vol_ratio<args.min_vol_ratio and vol<args.min_liq*2: continue

        pot3x=(15_000_000/mc) if mc>0 else 0
        sc=0
        sc+=min(25,n_callers*8)
        sc+=min(20,tsc)
        sc+=min(15,min(15,(5_000_000-mc)/1_000_000))
        sc+=min(10,e["holdings"]/500)
        sc+=min(15,px6/6) if px6>0 else 0
        sc+=min(10,vol_ratio*5)
        sc=round(sc,1)

        rows.append({"tok":tok,"sym":sym,"mc":mc,"liq":liq,"vol":vol,"vol_ratio":vol_ratio,
                     "px24":px24,"px6":px6,"px1":px1,"score":sc,"callers":e["callers"],
                     "holdings":e["holdings"],"pnl":e["pnl"],"tstrength":round(tsc,1),
                     "pot3x":pot3x,"buys":buys,"sells":sells,"url":url,"theses":e["theses"]})

    rows.sort(key=lambda r:-r["score"])
    print("\n"+"="*106)
    print(f"🎯 ROBINHOOD EARLY SCREENER v2 — MC≤${fmt(args.max_mc)} | liq≥${fmt(args.min_liq)} | anti-wash")
    print("="*106)
    if not rows:
        print("  (tidak ada yang lolos — robinhood feed tipis; coba lagi / longgarkan min-liq)")
        sys.exit(0)

    print(f" {'#':<2} {'sym':<10} {'score':<6} {'MC($)':<10} {'liq($)':<9} {'vol24($)':<11} {'v/mc':<5} {'6h':>6} {'24h':>7} {'callers'}")
    print("-"*106)
    for i,r in enumerate(rows[:15],1):
        print(f" {i:<2} {r['sym'][:10]:<10} {r['score']:<6} {fmt(r['mc']):<10} {fmt(r['liq']):<9} {fmt(r['vol']):<11} {r['vol_ratio']:<5.1f} {r['px6']:>+6.1f}% {r['px24']:>+7.1f}% {','.join(r['callers'][:4])}")

    print("\n🔍 DETAIL TOP 5 (3x check):")
    for r in rows[:5]:
        x3ok="✅" if r["liq"]>=50_000 and r["mc"]*3<=50_000_000 else "⚠️"
        print(f"\n  ● {r['sym']} — score {r['score']} — MC ${fmt(r['mc'])} → 3x=${fmt(r['mc']*3)} {x3ok}")
        print(f"    liq ${fmt(r['liq'])} | vol24 ${fmt(r['vol'])} (v/mc {r['vol_ratio']:.1f}x) | buy/sell {r['buys']}/{r['sells']}")
        print(f"    1h {r['px1']:+.1f}% | 6h {r['px6']:+.1f}% | 24h {r['px24']:+.1f}%")
        print(f"    thesis-str {r['tstrength']}/20 | holdings ${fmt(r['holdings'])} | pnl ${fmt(r['pnl'])} | callers: {','.join(r['callers'])}")
        print(f"    potensi ke 15M: {r['pot3x']:.1f}x")
        if r["theses"]: print(f"    thesis: {r['theses'][0][:100]}")
        print(f"    {r['url']}")

    if args.json:
        print("\n"+json.dumps({"candidates":rows[:15]},indent=2))

if __name__=="__main__":
    main()
