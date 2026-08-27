import urllib.request, json, re, time
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0","Content-Type":"application/json"}

def req(url, method="GET", data=None, cookies=None):
    h=dict(UA)
    if cookies: h["Cookie"]=cookies
    body=json.dumps(data).encode() if data is not None else None
    r=urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return resp.status, resp.read().decode(errors="ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore")
    except Exception as e:
        return 0, str(e)[:100]

# re-login to get fresh cookie
BASE="https://partner.fomoscan.sh"
email="wiznecro.test1787822158@gmail.com"
pw="TestPass!2026x"
_,_=req(BASE+"/api/auth/signup","POST",{"email":email,"password":pw})
c,b=req(BASE+"/api/auth/login","POST",{"email":email,"password":pw})
# login returns Set-Cookie; capture via fresh signup-response approach
# instead re-request with cookie jar: do a POST that sets cookie
import http.cookiejar
cj=http.cookiejar.CookieJar()
op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
def reqj(url, method="GET", data=None):
    h=dict(UA)
    body=json.dumps(data).encode() if data is not None else None
    r=urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with op.open(r, timeout=15) as resp:
            return resp.status, resp.read().decode(errors="ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore")
    except Exception as e:
        return 0, str(e)[:100]
reqj(BASE+"/api/auth/login","POST",{"email":email,"password":pw})
c,acct=reqj(BASE+"/account")
sess_str="; ".join(f"{ck.name}={ck.value}" for ck in cj)

# fetch account + billing pages
c,acct=req(BASE+"/account", cookies=sess_str)
open("/data/data/com.termux/files/home/partner_recon/acct_authed.html","w").write(acct)
print("account:", c, len(acct))

# extract all text content — strip tags
text=re.sub(r'<script[^>]*>.*?</script>','',acct,flags=re.S)
text=re.sub(r'<style[^>]*>.*?</style>','',text,flags=re.S)
text=re.sub(r'<[^>]+>',' ',text)
text=re.sub(r'\s+',' ',text)
print("\n=== ACCOUNT PAGE TEXT ===")
print(text[:2500])

print("\n\n=== API endpoints in account page flight data ===")
# flight data
nf=re.findall(r'self\.__next_f\.push\(\[1,"([^"]*)"\]\)', acct)
print("flight chunks:", len(nf))
full="".join(nf)
# look for interesting patterns
for m in re.finditer(r'(api|key|token|plan|quota|usage|limit|tier|billing|credits|subscribe)[^"]{0,80}', full, re.I):
    print("  ", m.group(0)[:120])
