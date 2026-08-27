import urllib.request, json, re
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"}
def get(url):
    req=urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode(errors="ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore")[:400]
    except Exception as e:
        return 0, str(e)[:80]

for p in ["/signup","/account","/billing"]:
    c,b=get("https://partner.fomoscan.sh"+p)
    fn=f"page_{p.strip('/')}.html"
    open("/data/data/com.termux/files/home/partner_recon/"+fn,"w").write(b)
    print(f"{p}: {c} len {len(b)} saved {fn}")
    # extract scripts
    srcs=re.findall(r'src="([^"]+\.js[^"]*)"', b)
    for s in srcs[:15]: print("   ", s)

print("\n=== AUTH ENDPOINT PROBE ===")
def post(url, data):
    req=urllib.request.Request(url, data=json.dumps(data).encode(), headers={"User-Agent":"Mozilla/5.0","Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.status, r.read().decode(errors="ignore")[:400]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore")[:400]
    except Exception as e:
        return 0, str(e)[:80]

for ep in ["/api/auth/signup","/api/auth/login","/api/auth","/api/auth/logout"]:
    for data in [{"email":"test@test.com","password":"password123"},{"email":"test@test.com","password":"password123","name":"test"},{}]:
        c,b=post("https://partner.fomoscan.sh"+ep, data)
        print(f"  POST {ep} {list(data.keys())}: [{c}] {b[:120]}")
        break  # only one payload per endpoint to save time
