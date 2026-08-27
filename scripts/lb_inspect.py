import urllib.request, json
KEY="[REDACTED]"
BASE="https://api.fomoscan.sh"
UA={"User-Agent":"Mozilla/5.0","Authorization":f"Bearer {KEY}"}
def get(path):
    req=urllib.request.Request(BASE+path, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read().decode(errors="ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore")
    except Exception as e:
        return 0, str(e)[:100]

# inspect lb_all.json for total & pagination hints
d=json.load(open("/data/data/com.termux/files/home/partner_recon/lb_all.json"))
print("top-level keys:", list(d.keys()))
print("count:", d.get("count"))
print("capturedAt:", d.get("capturedAt"))
print("hasMore:", d.get("hasMore"))
print("next:", d.get("next") or d.get("nextAfter") or d.get("cursor"))
e0=d["entries"][0]
print("\nentry keys:", list(e0.keys()))
print("sample entry:", json.dumps({k:e0[k] for k in list(e0.keys())[:12]}, indent=1)[:800])

# try pagination
for q in ["&offset=100","&page=2","&after=100","&cursor=100","&start=100","&limit=200","&limit=500"]:
    c,b=get(f"/v2/leaderboard/traders?window=all&limit=50{q}")
    try:
        dd=json.loads(b)
        print(f"  [{c}] {q}: count={dd.get('count')} entries={len(dd.get('entries',[]))}")
    except Exception as e:
        print(f"  [{c}] {q}: err")
