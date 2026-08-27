import urllib.request, json
KEY="[REDACTED]"
BASE="https://api.fomoscan.sh"
UA={"User-Agent":"Mozilla/5.0","Authorization":f"Bearer {KEY}"}

def get(path, retries=3):
    for i in range(retries):
        req=urllib.request.Request(BASE+path, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.status, r.read().decode(errors="ignore")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="ignore")
        except Exception as e:
            if i==retries-1: return 0, str(e)[:100]
            import time; time.sleep(2)
    return 0,""

# full leaderboard - try large limit
for window in ["24h","7d","all"]:
    c,b=get(f"/v2/leaderboard/traders?window={window}&limit=1000")
    try:
        d=json.loads(b)
        n=len(d.get("entries",[]))
        print(f"window={window}: [{c}] count={d.get('count')} entries={n}")
        fn=f"lb_{window}.json"
        open("/data/data/com.termux/files/home/partner_recon/"+fn,"w").write(b)
        print("   saved", fn)
    except Exception as ex:
        print(f"window={window}: [{c}] parse err {ex} | {b[:150]}")

# also get Quanterty full profile (wallet)
c,b=get("/v2/user/handle/Quanterty")
try:
    d=json.loads(b)
    print("\nQuanterty profile keys:", list(d.keys()))
    if 'solanaAddress' in d: print("  solana:", d['solanaAddress'][:6]+"..."+d['solanaAddress'][-4:])
    if 'evmAddress' in d: print("  evm:", d['evmAddress'][:6]+"..."+d['evmAddress'][-4:])
except Exception as e:
    print("Quanterty err", e)
