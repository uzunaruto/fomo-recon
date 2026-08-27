#!/usr/bin/env python3
"""
FOMO Whale Holdings — tarik posisi token SOLANAfull dari whale tracked.
1. Resolve full wallet address whale (api.fomoscan.sh/v2/user/handle/)
2. Tarik token accounts via Solana RPC (getTokenAccountsByOwner)
3. Cross-check MC/liq via DexScreener
4. Rekomendasi coin early yang whale pegang
"""
import os, sys, json, time, urllib.request, urllib.parse, argparse, base64

KEY = os.environ.get("FOMOSCAN_KEY", "")
FB  = "https://api.fomoscan.sh"
DS  = "https://api.dexscreener.com/latest/dex"
RPC = "https://api.mainnet-beta.solana.com"   # public RPC, gratis

TRACKED = ["ether_monk","Aurelius0121","change","unipcs","DumbCrayonEater",
           "PoorGoat_","loganlim_x","theveeman","Quanterty","brrrgrrrz",
           "0xleo","Salem1299534"]

def fomo(path):
    req = urllib.request.Request(FB+path, headers={"User-Agent":"Mozilla/5.0","Authorization":f"Bearer {KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e: return e.code, {}
    except Exception: return 0, {}

def solana(method, params):
    body=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode()
    req=urllib.request.Request(RPC, data=body, headers={"User-Agent":"Mozilla/5.0","Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return json.loads(r.read().decode())
    except Exception: return {}

def dex(tokens):
    q=",".join(tokens[:30])
    try:
        req=urllib.request.Request(f"{DS}/tokens/{q}", headers={"User-Agent":"Mozilla/5.0"})
        return json.loads(urllib.request.urlopen(req,timeout=20).read()).get("pairs",[])
    except Exception: return []

def fmt(n,d=0):
    try: return f"{n:,.{d}f}"
    except: return "?"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--max-mc",type=float,default=50_000_000)
    ap.add_argument("--min-liq",type=float,default=5_000)
    ap.add_argument("--json",action="store_true")
    args=ap.parse_args()

    print("🔍 FOMO Whale Holdings — posisi token whale tracked (on-chain)")
    # 1. resolve wallets
    addrs={}
    for h in TRACKED:
        c,d=fomo(f"/v2/user/handle/{h}")
        if c==200 and d.get("solanaAddress"):
            addrs[h]=d["solanaAddress"]
        elif c==402:
            print("  ⚠️ quota habis pas resolve, pakai cache"); break
        time.sleep(0.3)
    print(f"  ✅ resolve {len(addrs)}/{len(TRACKED)} wallet solana")

    # merge dengan cache (kalau ada)
    cache_p=os.path.join(os.path.dirname(__file__),"../data/screening_data.json")
    if os.path.exists(cache_p):
        cache=json.load(open(cache_p)).get("profiles",{})
        for h,p in cache.items():
            if h not in addrs and p.get("solana"):
                addrs[h]=p["solana"]
    print(f"  → total wallet {len(addrs)} (dengan cache)")

    # 2. tarik token accounts on-chain
    positions={}   # mint -> {amount, owners:[]}
    for h,addr in addrs.items():
        r=solana("getTokenAccountsByOwner", [addr, {"programId":"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}])
        res=r.get("result") or {}
        for acc in res.get("value",[]):
            try:
                data=base64.b64decode(acc["account"]["data"][0])
                mint=data[0:32]
                amt=int.from_bytes(data[64:72],"little")
                if amt<=0: continue
                mint58=base58(mint)
                e=positions.setdefault(mint58,{"amount":0,"owners":[]})
                e["amount"]+=amt
                if h not in e["owners"]: e["owners"].append(h)
            except Exception: pass
        time.sleep(0.2)
    print(f"  ✅ {len(positions)} token positions dari whale")

    # 3. cross-check MC via DexScreener
    print("  📈 cek MC/liq via DexScreener...")
    pairs=dex(list(positions.keys()))
    bytok={}
    for p in pairs: bytok.setdefault(p.get("baseToken",{}).get("address",""),[]).append(p)

    rows=[]
    for mint,e in positions.items():
        ps=bytok.get(mint,[])
        if not ps: continue
        p=max(ps,key=lambda x:float(x.get("liquidity",{}).get("usd") or 0))
        mc=float(p.get("marketCap") or 0); liq=float(p.get("liquidity",{}).get("usd") or 0)
        vol=float(p.get("volume",{}).get("h24") or 0)
        if not (0<mc<=args.max_mc and liq>=args.min_liq): continue
        sym=p.get("baseToken",{}).get("symbol") or mint[:6]
        rows.append({"mint":mint,"sym":sym,"mc":mc,"liq":liq,"vol":vol,
                     "whales":e["owners"],"url":f"https://dexscreener.com/solana/{mint}"})
    rows.sort(key=lambda r:-r["mc"])

    print("\n"+"="*100)
    print(f"🐋 COIN YANG DI PEGANG WHALE TRACKED — MC ≤ ${fmt(args.max_mc)} (early)")
    print("="*100)
    if not rows:
        print("  (tidak ada yang lolos — whale mungkin pegang token tanpa liq/MC, atau posisi kosong)")
    for i,r in enumerate(rows[:25],1):
        print(f" {i:<2} {r['sym'][:10]:<10} MC=${fmt(r['mc']):<10} liq=${fmt(r['liq']):<9} vol24=${fmt(r['vol']):<9} whale={','.join(r['whales'])}")
        print(f"    {r['url']}")

    if args.json:
        print("\n"+json.dumps({"wallets":addrs,"positions":rows[:25]},indent=2))

def base58(b):
    alpha="123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n=int.from_bytes(b,"big"); s=""
    while n: n,r=divmod(n,58); s=alpha[r]+s
    pad=0
    for c in b:
        if c==0: pad+=1
        else: break
    return "1"*pad+s

if __name__=="__main__":
    main()
