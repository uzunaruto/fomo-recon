import urllib.request, json, re
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"}
def probe(url, method="GET", body=None, headers=None):
    h=dict(UA)
    if headers: h.update(headers)
    data=None
    if body is not None:
        data=json.dumps(body).encode()
        h["Content-Type"]="application/json"
    req=urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.status, r.read()[:600]
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:600]
    except Exception as e:
        return 0, str(e)[:80]

routes=["/","/login","/signup","/register","/keys","/api-keys","/apikeys","/api","/docs","/dashboard","/overview","/account","/profile","/settings","/billing","/usage","/plans","/pricing","/onboarding","/me","/traders","/leaderboard","/terminal","/thesis","/wallet","/invite","/referral","/admin"]
print("=== PARTNER ROUTE MAP ===")
for p in routes:
    c,_=probe("https://partner.fomoscan.sh"+p)
    print(f"[{c}] {p}")

print("\n=== SIGNUP endpoint probe ===")
for ep in ["/api/signup","/api/register","/api/auth/register","/api/auth/signup","/api/user","/api/me","/api/keys","/api/api-keys","/api/auth/me","/api/session"]:
    c,b=probe("https://partner.fomoscan.sh"+ep, "POST" if "signup" in ep or "register" in ep else "GET", {} if ("signup" in ep or "register" in ep) else None)
    print(f"[{c}] {ep}: {b[:150]}")

print("\n=== ADMIN api probe ===")
for ep in ["/api/keys","/api/api-keys","/api/me","/api/users","/api/session","/api/status","/api/health"]:
    c,b=probe("https://admin.fomoscan.sh"+ep)
    print(f"[{c}] {ep}: {b[:150]}")
