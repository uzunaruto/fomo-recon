import urllib.request, json, re, time
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0","Content-Type":"application/json"}

def req(url, method="GET", data=None, cookies=None):
    h=dict(UA)
    if cookies: h["Cookie"]=cookies
    body=json.dumps(data).encode() if data is not None else None
    r=urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            hdrs=dict(resp.headers)
            return resp.status, resp.read().decode(errors="ignore"), hdrs.get("Set-Cookie","")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore"), ""
    except Exception as e:
        return 0, str(e)[:100], ""

BASE="https://partner.fomoscan.sh"
email=f"wiznecro.test{int(time.time())}@gmail.com"
pw="TestPass!2026x"

print("1. SIGNUP:", email)
c,b,cookies=req(BASE+"/api/auth/signup","POST",{"email":email,"password":pw})
print("   ->", c, b[:200], "| cookies:", cookies[:100])

print("\n2. LOGIN:")
c,b,cookies=req(BASE+"/api/auth/login","POST",{"email":email,"password":pw})
print("   ->", c, b[:200], "| Set-Cookie:", cookies[:200] if cookies else "(none)")

# extract session cookie
sess=None
if cookies:
    m=re.search(r'([A-Za-z0-9_]+)=([^;]+)', cookies)
    if m: sess=cookies.split(";")[0].strip()

print("\n3. GET /account with cookie:", sess[:30] if sess else "NO COOKIE")
c,b,_=req(BASE+"/account", cookies=sess)
print("   ->", c, "len", len(b))

# check for flight data/redirect to login
if "login" in b.lower()[:500] or c==307:
    print("   -> REDIRECTED TO LOGIN (auth required)")

# probe other protected routes
print("\n4. Protected routes probe:")
for p in ["/account","/billing","/signup","/api/auth/logout"]:
    c,b,_=req(BASE+p, cookies=sess)
    red = "-> login" if "location: /login" in b.lower()[:200] else ""
    print(f"   [{c}] {p} {red} len={len(b)}")

# check what /account returns (content or redirect)
print("\n5. /account content snippet:")
print("   ", b[:400].replace("\n"," "))
