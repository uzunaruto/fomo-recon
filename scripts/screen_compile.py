import json, urllib.request, time
KEY="[REDACTED]"
BASE="https://api.fomoscan.sh"
UA={"User-Agent":"Mozilla/5.0","Authorization":f"Bearer {KEY}"}
def get(path):
    req=urllib.request.Request(BASE+path, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error":str(e)}

# load 3 windows
data={}
for w in ["24h","7d","all"]:
    try:
        data[w]=json.load(open(f"/data/data/com.termux/files/home/partner_recon/lb_{w}.json"))["entries"]
    except Exception as e:
        data[w]=[]
        print("load err", w, e)

print("=== TOP 15 TRADER per window ===")
for w in ["24h","7d","all"]:
    print(f"\n--- {w} ---")
    for e in data[w][:15]:
        print(f"  #{e['rank']:>3} {e['handle']:<22} pnl=${e['pnl']:>12,.0f} vol=${e['volume']:>12,.0f} tr={e['numTrades']:>5} flw={e['followers']}")

# resolve wallets for top 10 by followers across windows (union)
seen={}
for w in ["24h","7d","all"]:
    for e in data[w][:20]:
        h=e["handle"]
        if h not in seen and len(seen)<12:
            seen[h]=e
print("\n=== RESOLVE WALLETS (top handles) ===")
profiles={}
for h in seen:
    d=get(f"/v2/user/handle/{h}")
    if "error" not in d:
        sol=d.get("solanaAddress"); evm=d.get("evmAddress")
        profiles[h]={"solana":(sol[:6]+"..."+sol[-4:]) if sol else None,
                     "evm":(evm[:6]+"..."+evm[-4:]) if evm else None,
                     "name":d.get("name"),"bio":(d.get("bio") or "")[:40]}
        print(f"  {h:<22} sol={profiles[h]['solana']} evm={profiles[h]['evm']}")
    else:
        print(f"  {h:<22} ERR")
    time.sleep(0.3)

# save consolidated
out={"leaderboard":{w:[e for e in data[w]] for w in data}, "profiles":profiles}
json.dump(out, open("/data/data/com.termux/files/home/partner_recon/screening_data.json","w"), indent=1)
print("\nsaved screening_data.json:", len(data["all"]), "traders (all window) +", len(profiles), "profiles")
