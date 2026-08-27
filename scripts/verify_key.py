import urllib.request, json
KEY="[REDACTED]"
BASE="https://api.fomoscan.sh"
UA={"User-Agent":"Mozilla/5.0","Authorization":f"Bearer {KEY}"}

def get(path):
    req=urllib.request.Request(BASE+path, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode(errors="ignore")[:800]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore")[:400]
    except Exception as e:
        return 0, str(e)[:100]

print("=== VERIFY API KEY ON api.fomoscan.sh ===")
for p in ["/v2/me","/v2/user/me","/v2/leaderboard/traders?window=24h&limit=3",
          "/v2/user/handle/Quanterty","/v2/thesis?limit=2","/v2/leaderboard/tokens/trending?limit=3"]:
    c,b=get(p)
    print(f"\n[{c}] {p}")
    print("  ", b[:300].replace("\n"," "))
