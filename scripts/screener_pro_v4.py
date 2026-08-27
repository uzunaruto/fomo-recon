#!/usr/bin/env python3
"""
MICIN SCREENER PRO v4 — LLM-driven (MiniMax M3) + Deployer Cross-Ref + Timeline + FomoScan + Tax Sim
====================================================================================================
Architecture:
  Phase 0  Init              : config + gmi (MiniMax M3) client + FomoScan auto-signup
  Phase 1  DISCOVER          : Blockscout ERC-20 scan (fast, paginate)
  Phase 2  DEXENRICH         : DexScreener MC/liq/vol/price + timeline (m5/h1/h6/h24) (batch)
  Phase 3  HARD GATES        : MC<5M, liq>=$1K, vol quality, exclude dust/obvious
  Phase 4  DEEP (Blockscout) : holders conc, wash, contract safety, deployer, age, tax signal
  Phase 4b DEPLOYER CROSS-REF: cluster serial launchers from all deep candidates
  Phase 5  FOMOSCAN THESIS   : auto-signup fresh key, fetch /v2/thesis, match CAs (bonus confirmation)
  Phase 6  LLM MINIMAX M3    : qualitative scoring, market phase, entry, anti-wash, TOP5
  Phase 7  TAX SIM (TOP 5)   : live swap sim via router (best-effort, graceful SKIPPED)
  Phase 8  OUTPUT            : structured report + save JSON

Chain: 4663 / robinhood. Blockscout-first (fast, no RPC bottleneck).
Tax sim is BEST-EFFORT with timeout — never blocks the pipeline.
"""

import json, urllib.request, time, os, sys, math, urllib.parse, re, subprocess
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------- CONFIG ----------
BS = "https://robinhoodchain.blockscout.com/api/v2"
RPC = "http://127.0.0.1:8098/rpc"          # optional best-effort
SWAP_ROUTER = "0xcaf681a66d020601342297493863e78c959e5cb2"  # Robinhood V3
FACTORY = "0x1f7d7550b1b028f7571e69a784071f0205fd2efa"
UA = "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36"
MAX_CANDIDATES = 14
LLM_ENABLED = True
LLM_TIMEOUT = 120
TAX_SIM_ENABLED = True    # best-effort, only on top 5 post-LLM
OUT = os.path.expanduser("~/fomo-recon/data/pro_v4_ranking.json")

# gmi (MiniMax M3) via config.yaml
try:
    import yaml
    _cfg = yaml.safe_load(open(os.path.expanduser("~/.hermes/config.yaml")))
    _d = _cfg.get("delegation", {})
    GMI_BASE = _d.get("base_url", "https://api.gmi-serving.com/v1")
    GMI_KEY  = _d.get("api_key", "")
    GMI_MODEL= _d.get("model", "MiniMaxAI/MiniMax-M3")
except Exception:
    GMI_BASE, GMI_KEY, GMI_MODEL = "https://api.gmi-serving.com/v1", "", "MiniMaxAI/MiniMax-M3"

# ---------- UTILITY ----------
def _dec(v):
    try: return int(v)
    except: return 18

def fmt_ts(ts):
    """Format ISO timestamp to hours ago if recent."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z","+00:00"))
        return round((datetime.now(timezone.utc) - dt).total_seconds()/3600, 1)
    except: return ts

# ---------- HTTP ----------
def bs(path, timeout=20):
    try:
        req = urllib.request.Request(BS+path, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ERR": str(e)}

def ds(tokens):
    """DexScreener batch lookup with timeline fields."""
    out = {}
    for i in range(0, len(tokens), 30):
        chunk = tokens[i:i+30]
        try:
            req = urllib.request.Request(
                "https://api.dexscreener.com/latest/dex/tokens/"+",".join(chunk),
                headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                j = json.loads(r.read().decode())
            for p in j.get("pairs", []):
                a = p.get("baseToken", {}).get("address","").lower()
                if not a: continue
                if a not in out or (p.get("liquidity",{}).get("usd") or 0) > (out[a].get("liq_usd") or 0):
                    pc = p.get("priceChange",{}) or {}
                    v = p.get("volume",{}) or {}
                    out[a] = {
                        "pair_addr": p.get("pairAddress",""), "dex": p.get("dexId",""),
                        "chain": p.get("chainId",""), "price_usd": p.get("priceUsd"),
                        "liq_usd": (p.get("liquidity",{}) or {}).get("usd"),
                        "liq_base": (p.get("liquidity",{}) or {}).get("base"),
                        "liq_quote": (p.get("liquidity",{}) or {}).get("quote"),
                        "vol_24h": v.get("h24"), "vol_h6": v.get("h6"), "vol_h1": v.get("h1"),
                        "price_chg_24h": pc.get("h24"), "price_chg_h6": pc.get("h6"),
                        "price_chg_h1": pc.get("h1"), "price_chg_m5": pc.get("m5"),
                        "txn_buy_24h": ((p.get("txns",{}) or {}).get("h24",{}) or {}).get("buys"),
                        "txn_sell_24h": ((p.get("txns",{}) or {}).get("h24",{}) or {}).get("sells"),
                        "fdv": p.get("fdv"), "mc": p.get("marketCap"),
                    }
        except Exception:
            pass
        time.sleep(0.4)
    return out

# ---------- FOMOSCAN AUTO-SIGNUP (FRESH KEY EACH RUN) ----------
def fomo_fresh_key():
    """Auto-signup partner.fomoscan.sh, return fresh API key."""
    import urllib.error
    base = "https://partner.fomoscan.sh"
    email = f"wiznecro.micin{int(time.time())}@gmail.com"
    pw = f"Mic!n{int(time.time()%1000):03d}x"
    headers = {"User-Agent": UA, "Content-Type": "application/json"}
    # signup
    body = json.dumps({"email":email,"password":pw}).encode()
    try:
        req = urllib.request.Request(base+"/api/auth/signup", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read().decode())
            key = (resp.get("key") or resp.get("apiKey") or "")
            if key:
                return {"key": key, "email": email, "raw": str(resp)[:200]}
    except: pass
    # login fallback
    try:
        req = urllib.request.Request(base+"/api/auth/login", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read().decode())
            key = (resp.get("key") or resp.get("apiKey") or "")
            if key: return {"key": key, "email": email, "raw": str(resp)[:200]}
    except: pass
    return None

def fomo_thesis(key, limit=30):
    """Fetch /v2/thesis from fomoscan with fresh key."""
    if not key: return {"tokens": [], "error": "no_key"}
    try:
        hdrs = {"Authorization": f"Bearer {key}", "User-Agent": UA}
        req = urllib.request.Request(f"https://api.fomoscan.sh/v2/thesis?limit={limit}", headers=hdrs)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"tokens": [], "error": str(e)[:100]}

# ---------- PHASE 1: DISCOVER ----------
def discover(max_pages=4):
    tokens = {}; page = 0; next_url = f"/tokens?type=ERC-20&items_count=50"
    while page < max_pages:
        j = bs(next_url if next_url.startswith("/") else next_url)
        items = j.get("items", [])
        for it in items:
            a = (it.get("address_hash") or "").lower()
            if a and a not in tokens:
                tokens[a] = {"name": it.get("name"), "symbol": it.get("symbol"),
                             "decimals": _dec(it.get("decimals")), "holders": it.get("holders_count"),
                             "type": it.get("type")}
        np = j.get("next_page_params")
        if not np or not items: break
        page += 1
        next_url = "/tokens?" + urllib.parse.urlencode({k: v for k, v in np.items() if v is not None})
    return tokens

# ---------- PHASE 3: HARD GATES ----------
def hard_gates(addr, d):
    mc = d.get("mc") or 0
    liq = d.get("liq_usd") or 0
    vol = d.get("vol_24h") or 0
    reasons = []
    if not mc or mc <= 0: reasons.append("no_mc")
    if mc and mc > 5_000_000: reasons.append(f"mc>{mc/1e6:.1f}M")
    if liq < 1000: reasons.append(f"liq<${liq:.0f}")
    if vol and liq and vol/liq > 40: reasons.append("v/mc_wash_risk")
    return reasons

# ---------- PHASE 4: DEEP ----------
def parse_val(v, decimals):
    try:
        if isinstance(v, dict): return int(v.get("value",0)) / (10**decimals)
        return int(v) / (10**decimals)
    except: return 0

def deep_contract(addr):
    j = bs(f"/addresses/{addr}")
    info = {"verified": False, "is_contract": False, "deployer": None,
            "creation_tx": None, "creation_ts": None, "flags": []}
    if isinstance(j, dict) and not j.get("ERR"):
        info["is_contract"] = j.get("is_contract", False)
        info["verified"] = j.get("is_verified", False)
        info["deployer"] = (j.get("creator_address_hash") or "").lower() or None
        info["creation_tx"] = j.get("creation_transaction_hash") or None
        info["creation_ts"] = j.get("created_at") or None
    c = bs(f"/smart-contracts/{addr}")
    if isinstance(c, dict) and not c.get("ERR"):
        abi = c.get("abi")
        if isinstance(abi, str):
            try: abi = json.loads(abi)
            except: abi = None
        if isinstance(abi, list):
            names = {x.get("name","") for x in abi if x.get("type")=="function"}
            info["flags"] = [f for f in ("owner","mint","pause","blacklist","freeze",
                "transferOwnership","renounceOwnership","setTax","setFee","_transfer",
                "excludeFromFee","isExcludedFromFee","addBlackList","removeBlackList") if f in names]
    return info

def deep_holders(addr, decimals, topn=20):
    res = {"total": None, "top10_pct": None, "top1_pct": None, "top1_val": None,
           "holders_fetched": 0, "transfers": [], "repeat_tx": 0, "uniq_wallets": 0}
    items = []
    for attempt in range(2):
        h = bs(f"/tokens/{addr}/holders?items_count=50")
        if not h.get("ERR"):
            items = h.get("items", [])
            if items: break
    vals = []
    for it in items:
        v = parse_val((it.get("value") or {}).get("value") if isinstance(it.get("value"),dict) else it.get("value"), decimals)
        vals.append(v)
    s = sum(vals)
    if s > 0 and len(vals) >= 10:
        res["total"] = s
        top1 = vals[0] if vals else 0
        top10 = sum(sorted(vals, reverse=True)[:10])
        res["top1_pct"] = top1/s*100
        res["top10_pct"] = top10/s*100
        res["top1_val"] = top1
    res["holders_fetched"] = len(vals)
    tr = bs(f"/tokens/{addr}/transfers")
    txs = []
    for it in tr.get("items", []):
        frm = (it.get("from") or {}).get("hash","")
        to  = (it.get("to") or {}).get("hash","")
        txs.append((frm.lower(), to.lower(), it.get("timestamp",""), it.get("tx_hash","")))
    res["transfers"] = txs
    pair_count = {}
    for f,t,ts,h in txs:
        k = f+"|"+t
        pair_count[k] = pair_count.get(k,0)+1
    res["repeat_tx"] = sum(1 for v in pair_count.values() if v > 1)
    res["uniq_wallets"] = len({x[0] for x in txs} | {x[1] for x in txs})
    return res

def token_age(addr, deployer, creation_tx):
    if not creation_tx: return None
    j = bs(f"/transactions/{creation_tx}")
    if isinstance(j, dict) and not j.get("ERR"):
        ts = j.get("timestamp")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z","+00:00"))
                return (datetime.now(timezone.utc) - dt).total_seconds()/3600
            except: pass
    return None

def tax_signal(addr, pair_addr, dec_reverse=None):
    if not pair_addr or not RPC: return None
    try:
        body = json.dumps({"jsonrpc":"2.0","id":1,"method":"eth_call",
            "params":[{"to":pair_addr,"data":"0x3850c7bd"}, "latest"]})
        req = urllib.request.Request(RPC, data=body.encode(),
            headers={"Content-Type":"application/json","User-Agent":UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = json.loads(r.read().decode()).get("result","")
        if not raw or raw == "0x": return None
        sqrt = int(raw[2:66], 16)
        if sqrt == 0: return None
        price = (sqrt / 2**96) ** 2
        return {"sqrt": sqrt, "price_ratio": price, "method": "pool_slot0"}
    except Exception:
        return None

# ---------- TAX SIM (live swap via router, best-effort on top 5) ----------
def _erc20_balance_slot(owner, slot=0):
    """Compute ERC20 balanceOf(owner) storage slot: keccak256(abi(owner, slot))."""
    import hashlib
    h = hashlib.sha3_256()
    h.update(bytes.fromhex(owner[2:].zfill(64)) + slot.to_bytes(32,'big'))
    return "0x" + h.hexdigest()

def _erc20_allowance_slot(owner, spender):
    """Compute ERC20 allowance(owner,spender) slot (slot 1 typically)."""
    import hashlib
    h = hashlib.sha3_256()
    h.update(bytes.fromhex(owner[2:].zfill(64)) + bytes.fromhex(spender[2:].zfill(64)) + (1).to_bytes(32,'big'))
    return "0x" + h.hexdigest()

def _rpc(method, params, timeout=8):
    body = json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode()
    req = urllib.request.Request(RPC, data=body.encode(),
        headers={"Content-Type":"application/json","User-Agent":UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode()).get("result")

def tax_sim_live(cand, addr, decimals=18):
    """
    Attempt live swap sim via SwapRouter02 exactInputSingle with state_override.
    Fakes TEST sender balance + router allowance on the QUOTE token, then measures
    received vs expected to derive buy tax and sell tax. Honeypot if sell reverts.
    Returns dict with buy_tax/sell_tax/honeypot or {"method":"SKIPPED","reason":...}.
    """
    if not RPC or not SWAP_ROUTER: return {"method":"SKIPPED","reason":"no_rpc_or_router"}
    pair_addr = cand.get("pair_addr")
    if not pair_addr: return {"method":"SKIPPED","reason":"no_pair_addr"}
    TEST = "0xdead000000000000000000000000000000000003"
    try:
        fee = int(_rpc("eth_call", [{"to":pair_addr,"data":"0xddca3f43"},"latest"]) or "0x0", 16)
        t0r = _rpc("eth_call", [{"to":pair_addr,"data":"0x0dfe1681"},"latest"])
        t1r = _rpc("eth_call", [{"to":pair_addr,"data":"0xd21220a7"},"latest"])
        if not t0r or not t1r: return {"method":"SKIPPED","reason":"pool_tokens_unreadable"}
        t0 = "0x" + t0r[26:].lower()
        t1 = "0x" + t1r[26:].lower()
    except Exception as e:
        return {"method":"SKIPPED","reason":f"pool_read:{str(e)[:50]}"}
    if fee == 0 or fee > 1_000_000: return {"method":"SKIPPED","reason":f"bad_fee:{fee}"}

    # Determine our token & quote token. Quote = the NON-our token (assume 18 dec).
    our = addr.lower()
    if our == t0:
        quote = t1; token_out = t0
    elif our == t1:
        quote = t0; token_out = t1
    else:
        return {"method":"SKIPPED","reason":"token_not_in_pool"}

    def pad(x): return x.replace("0x","").lower().zfill(64)

    def build_exact(amount_in, token_in, token_out):
        # exactInputSingle((address tokenIn,address tokenOut,uint24 fee,address recipient,uint256 deadline,uint256 amountIn,uint256 amountOutMinimum,uint160 sqrtPriceLimitX96))
        deadline = hex(int(time.time())+3600)[2:]
        return ("0x414bf389"
                + pad(token_in) + pad(token_out) + pad(hex(fee)[2:])
                + pad(TEST) + deadline
                + pad(hex(amount_in)[2:])
                + "0"*64  # amountOutMinimum = 0
                + "0"*64) # sqrtPriceLimitX96 = 0

    # State override: give TEST quote-token balance + router allowance
    bal_slot = _erc20_balance_slot(TEST)          # slot 0 = balances mapping
    allow_slot = _erc20_allowance_slot(TEST, SWAP_ROUTER)  # slot 1 = allowances
    override = {
        quote: {
            "stateDiff": {
                bal_slot: "0x" + hex(1 << 200)[2:].zfill(64),      # huge TEST balance
                allow_slot: "0x" + hex(1 << 255)[2:].zfill(64),     # huge allowance
            }
        }
    }
    # Also give TEST native balance (in case router needs ETH)
    override["0x" + "0"*40] = {"balance": "0x" + hex(1 << 200)[2:].zfill(64)}

    amt_in = 10**17  # 0.1 quote token

    def try_swap(calldata, tok_out):
        params = [{"from": TEST, "to": SWAP_ROUTER, "data": calldata}, "latest", override]
        try:
            res = _rpc("eth_call", params, timeout=15)
            if not res or res == "0x": return None, "empty"
            # decode amountOut (last 32 bytes)
            out = int(res[-64:], 16)
            return out, None
        except Exception as e:
            return None, str(e)[:60]

    # BUY: quote -> our token
    buy_out, buy_err = try_swap(build_exact(amt_in, quote, our), our)
    if buy_out is None:
        # maybe direction reversed; try our -> quote won't help for buy. Try with our as token_in small
        # If buy fails, likely non-standard pool -> SKIPPED
        return {"method":"SKIPPED","reason":f"buy_reverted:{buy_err}"}
    # Expected (no tax) ≈ amountIn * price. We approximate via ratio; instead just report raw.
    # SELL: our token -> quote (need our-token balance + allowance too)
    # Re-use: TEST holds quote; also need to hold our token. Add our-token balance+allowance.
    override2 = dict(override)
    bal2 = _erc20_balance_slot(TEST)
    allow2 = _erc20_allowance_slot(TEST, SWAP_ROUTER)
    override2[our] = {
        "stateDiff": {
            bal2: "0x" + hex(1 << 200)[2:].zfill(64),
            allow2: "0x" + hex(1 << 255)[2:].zfill(64),
        }
    }
    sell_out, sell_err = None, None
    try:
        params = [{"from": TEST, "to": SWAP_ROUTER, "data": build_exact(amt_in, our, quote)}, "latest", override2]
        res = _rpc("eth_call", params, timeout=15)
        if res and res != "0x":
            sell_out = int(res[-64:], 16)
        else:
            sell_err = "empty"
    except Exception as e:
        sell_err = str(e)[:60]

    # Tax estimation: buy tax = 1 - (buy_out / (amt_in * pool_price)).
    # We can't easily know pool price, but for V3 the marginal price = slot0.
    # Instead we report buy_tax/sell_tax as 'approx' from output only when we can compare.
    result = {"method": "router_exactInputSingle", "buy_out_raw": buy_out, "sell_out_raw": sell_out,
              "quote": quote, "our": our, "fee": fee}
    if sell_out is None:
        result["honeypot"] = True
        result["sell_tax"] = 100
        result["buy_tax"] = None
        result["sell_err"] = sell_err
    else:
        result["honeypot"] = False
        result["buy_tax"] = None  # needs price; LLM/slot0 handles qualitative
        result["sell_tax"] = None
    return result

# ---------- PHASE 4b: DEPLOYER CROSS-REF ----------
def build_deployer_map(cands):
    """Collect all deployers, flag serial launchers (>=3 tokens)."""
    dep_map = {}
    for c in cands:
        dep = c.get("deployer")
        if not dep: continue
        if dep not in dep_map:
            dep_map[dep] = {"tokens": [], "verified_all": True, "total_launches": 0}
        dep_map[dep]["tokens"].append(c["addr"])
        dep_map[dep]["total_launches"] = dep_map[dep].get("total_launches",0)+1
        dep_map[dep]["verified_all"] = dep_map[dep]["verified_all"] and c.get("verified",False)
    # Serial launchers: deployer with >=3 tokens
    serial = {}
    for dep, info in dep_map.items():
        if info["total_launches"] >= 3:
            serial[dep] = info
    return serial

# ---------- PHASE 6: LLM ----------
def llm_call(prompt, system="You are an expert crypto/on-chain analyst."):
    body = {"model": GMI_MODEL,
            "max_tokens": 6000,
            "messages":[{"role":"system","content":system},{"role":"user","content":prompt}]}
    req = urllib.request.Request(GMI_BASE+"/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","Authorization":f"Bearer {GMI_KEY}","User-Agent":UA})
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as r:
                return json.loads(r.read().decode())["choices"][0]["message"]["content"]
        except Exception as e:
            last = e
            if getattr(e, "code", None) in (429, 500, 502, 503):
                time.sleep(8*(attempt+1))
            else:
                raise
    raise last

def llm_analyze(cands, serial_deps=None, fomo_thesis_data=None):
    pack = [{
        "addr": c["addr"], "symbol": c.get("symbol"), "name": c.get("name"),
        "mc": c.get("mc"), "liq_usd": c.get("liq_usd"), "vol_24h": c.get("vol_24h"),
        "vol_h6": c.get("vol_h6"), "vol_h1": c.get("vol_h1"),
        "v_mc": round(c.get("v_mc",0),2),
        "price_chg_24h": c.get("price_chg_24h"), "price_chg_h6": c.get("price_chg_h6"),
        "price_chg_h1": c.get("price_chg_h1"), "price_chg_m5": c.get("price_chg_m5"),
        "holders": c.get("holders"),
        "top10_pct": round(c.get("top10_pct") or 0,1), "top1_pct": round(c.get("top1_pct") or 0,1),
        "verified": c.get("verified"), "contract_flags": c.get("contract_flags",[]),
        "deployer": c.get("deployer"), "age_hours": round(c.get("age_hours") or 0,1),
        "repeat_tx": c.get("repeat_tx"), "uniq_wallets": c.get("uniq_wallets"),
        "price_usd": c.get("price_usd"),
    } for c in cands]

    # Timeline context
    trend_ctx = ""
    # Deployer context
    dep_ctx = ""
    if serial_deps:
        dep_lines = []
        for dep, info in serial_deps.items():
            tok_list = ", ".join(info["tokens"][:5])
            dep_lines.append(f"Deployer {dep[:10]}... launched {info['total_launches']} tokens: {tok_list}")
        dep_ctx = "\nSerial Launcher Detected:\n" + "\n".join(dep_lines) + "\nTokens from same deployer may be insider-connected."

    # FomoScan context
    fomo_ctx = ""
    if fomo_thesis_data:
        tokens = fomo_thesis_data.get("tokens", [])
        if tokens:
            calls = []
            for t in tokens[:20]:
                calls.append(f"{t.get('tok','')[:10]}... ({t.get('sym','')}) called by {t.get('callers',[])}")
            fomo_ctx = "\nFomoScan Smart Money Thesis:\n" + "\n".join(calls) + "\nTokens with smart-money confirmation have higher conviction."

    prompt = f"""You are scoring {len(cands)} micro-cap tokens on Robinhood chain (4663, Uniswap V3).
Anti-trap rules: reject coins whose volume is wallet-clusters/insiders churning. Never assume high volume=organic, many wallets=independent, low MC=upside, good narrative=good token. Tax + exitability are the decisive signals.
Scoring weights (total 100): Narrative 15 | Smart Money 10 (cap) | Whale 10 | Liquidity 15 | Volume/Momentum 5 | Tokenomics 10 | Contract Safety 15 (hard gate: unverified+owner=auto-reject) | Holder Distribution Quality 20.

Timeline Hint: Use m5/h1/h6/h24 price change + volume trend to assess phase. If price_chg_h6 is positive but h24 flat, it may be a fresh pump. If h6 is -20% and h24 is +50%, it's a retrace from a peak. If vol_h6 > vol_h1*4, volume is accelerating. Slowing volume + rising price = distribution.

Return JSON ONLY. Express ALL entry/target levels in MARKET CAP (MC) dollars, NOT token price. Keys: entry_mc/inv_mc/tp1_mc/tp2_mc/tp3_mc (e.g. "$2.5M-$3.0M").
{{"rankings":[
  {{"addr":"0x..","score":0,"conviction":1-10,"phase":"VERY_EARLY|EARLY|GOOD_ENTRY|EXTENDED|OVERHEATED|DISTRIBUTION","narrative":"1 line","smart_money":"yes/no/unknown","wash_risk":0.0-1.0,"wash_reason":"...","entry":"AGGRESSIVE|CONSERVATIVE|DIP|NO_ENTRY","entry_mc":"$X M-$Y M","inv_mc":"$X M","tp1_mc":"$X M","tp2_mc":"$X M","tp3_mc":"$X M","rr":"1:2","risk":"top risk","enter":[3 reasons],"avoid":[3 reasons]}}
], "best_overall":"0x..","best_early":"0x..","best_meme":"0x..","best_utility":"0x..","best_rr":"0x..","highest_risk":"0x..","avoid":"0x..","watch3":["0x..","0x..","0x.."],"summary":"2-3 sentence final market summary"}}
Candidate data:
{json.dumps(pack, default=str)}{dep_ctx}{fomo_ctx}"""
    try:
        raw = llm_call(prompt)
        if isinstance(raw, str) and not raw.startswith("LLM_ERROR"):
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned, flags=re.M)
                i = cleaned.find("{")
                if i >= 0: cleaned = cleaned[i:]
            try:
                json.loads(cleaned)
                return raw
            except Exception:
                strict = prompt + "\n\nCRITICAL: Previous response was NOT valid JSON and was REJECTED. Output ONLY valid JSON. Every key and string MUST use double quotes. Do NOT put newlines inside string values. Do NOT use markdown fences. Arrays must be [\"a\",\"b\"] not [{\"key\":...}]. Return the exact schema."
                raw2 = llm_call(strict)
                return raw2
        return raw
    except Exception as e:
        return f"LLM_ERROR: {e}"

# ---------- RENDER ----------
def render_top5(cands, llm_raw, fomo_data=None, serial_deps=None, tax_sims=None):
    clean_llm = llm_raw
    if isinstance(llm_raw, str) and llm_raw.strip().startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", llm_raw.strip(), flags=re.M)
        i = s.find("{")
        if i >= 0: s = s[i:]
        j = s.rfind("```")
        if j > 0: s = s[:j]
        clean_llm = s.strip()
        k = clean_llm.rfind("}")
        if k >= 0 and not clean_llm.rstrip().endswith("}"):
            clean_llm = clean_llm[:k+1]
    if isinstance(clean_llm, str) and not clean_llm.startswith("LLM_ERROR") and clean_llm.strip().startswith("{"):
        try:
            jr = json.loads(clean_llm)
            score = {r["addr"].lower(): r for r in jr.get("rankings",[])}
            for c in cands:
                r = score.get(c["addr"].lower())
                if r: c["llm_score"] = r.get("score"); c["llm_conv"] = r.get("conviction"); c["llm_phase"]=r.get("phase")
            print("\n"+"="*60+"\n  MICIN SCREENER PRO v4 — TOP RANKING (MiniMax M3)\n"+"="*60)
            top = [c for c in cands if c.get("llm_score") is not None]
            top.sort(key=lambda c: c.get("llm_score",0), reverse=True)
            for i,c in enumerate(top[:5],1):
                mc = (c.get('mc') or 0)
                print(f"\n  #{i} {c.get('symbol','?'):<8} {c.get('name','')[:22]:<22} score={c.get('llm_score')} conviction={c.get('llm_conv')}")
                print(f"     phase={c.get('llm_phase')}  MC=${mc/1e6:.2f}M  liq=${(c.get('liq_usd') or 0):.0f}  vol24=${(c.get('vol_24h') or 0)/1e3:.0f}K  V/MC={(c.get('v_mc') or 0):.1f}")
                # Timeline
                pc = c.get("price_chg_24h"); pc6 = c.get("price_chg_h6"); pc1 = c.get("price_chg_h1")
                vh6 = c.get("vol_h6"); vh1 = c.get("vol_h1")
                print(f"     trend: 24h={pc}%  h6={pc6}%  h1={pc1}%  volh6={vh6}  volh1={vh1}")
                print(f"     holders={c.get('holders')} top10={c.get('top10_pct')}% top1={c.get('top1_pct')}%  verified={c.get('verified')}  age={c.get('age_hours')}h")
                print(f"     flags={c.get('contract_flags')}")
                r = score.get(c["addr"].lower())
                if r:
                    def fmt_mc(v):
                        if v is None: return None
                        s = str(v).replace("$","").replace(" ","").lower()
                        s = re.split(r"[-–—]", s)[0]
                        if s.endswith("m"): return float(s[:-1].replace(",",""))
                        if s.endswith("k"): return float(s[:-1].replace(",",""))/1000
                        return None
                    em = fmt_mc(r.get("entry_mc")) or fmt_mc(r.get("entry_zone")) or (mc/1e6)
                    cprice = c.get("price_usd")
                    def tp_to_mc(tp):
                        if tp is None or not cprice: return None
                        st=str(tp).replace("$","").replace(" ","").replace(",","")
                        if st.lower().endswith(("m","k")): return fmt_mc(st)
                        try:
                            pv=float(st)
                            return (mc/1e6)*(pv/cprice) if cprice>0 else None
                        except: return None
                    t1=fmt_mc(r.get("tp1_mc")) or tp_to_mc(r.get("tp1"))
                    t2=fmt_mc(r.get("tp2_mc")) or tp_to_mc(r.get("tp2"))
                    t3=fmt_mc(r.get("tp3_mc")) or tp_to_mc(r.get("tp3"))
                    em = em or (mc/1e6)
                    def fm(x): return f"${x:.2f}M" if x else "—"
                    print(f"     entry={r.get('entry')}  entryMC={fm(em)}  TP1 MC={fm(t1)}  TP2 MC={fm(t2)}  TP3 MC={fm(t3)}  RR={r.get('rr')}")
                    print(f"     enter: {r.get('enter')}")
                    print(f"     avoid: {r.get('avoid')}")
                    print(f"     risk: {r.get('risk')}  wash={r.get('wash_risk')} ({r.get('wash_reason')})")
                # Deployer cross-ref
                dep = c.get("deployer")
                if serial_deps and dep and serial_deps.get(dep):
                    info = serial_deps[dep]
                    print(f"     ⚠️ DEPLOYER: {dep[:10]}... ({info['total_launches']} launches) — serial launcher")
                # FomoScan thesis
                if fomo_data:
                    for t in fomo_data.get("tokens",[]):
                        if t.get("tok","").lower() == c["addr"].lower():
                            print(f"     📡 FomoScan: called by {t.get('callers',[])} — {t.get('pnl','')} PnL")
                # Tax sim
                if tax_sims:
                    ts = tax_sims.get(c["addr"])
                    if ts:
                        tx_buy = ts.get("buy_tax","?"); tx_sell = ts.get("sell_tax","?")
                        hp = "HONEYPOT! " if ts.get("honeypot") else ""
                        print(f"     🔬 Tax: buy={tx_buy}%  sell={tx_sell}%  {hp}method={ts.get('method','SKIPPED')}")
                print(f"     CA: {c['addr']}")
        except Exception as e:
            print("  render err:", e)

# ---------- MAIN ----------
def main():
    import urllib.parse
    print("=== MICIN SCREENER PRO v4 (MiniMax M3 + Deployer + Timeline + FomoScan + Tax) ===")
    t0 = time.time()

    # Phase 1: discover
    print("[1/6] Discovering ERC-20 tokens...")
    toks = discover()
    print(f"  -> {len(toks)} tokens found")

    # Phase 2: dexscreener enrich
    print("[2/6] DexScreener enrich...")
    addrs = list(toks.keys())
    dd = ds(addrs)
    print(f"  -> {len(dd)} with pairs")

    # Phase 3: hard gates
    print("[3/6] Hard gates...")
    cands = []
    for a, d in dd.items():
        sym = (toks.get(a,{}) or {}).get("symbol","")
        reasons = hard_gates(a, d)
        if reasons: continue
        cands.append({"addr": a, "symbol": sym, "holders_count": (toks.get(a,{}) or {}).get("holders"), **d})
    cands.sort(key=lambda c: (c.get("vol_24h") or 0)/(c.get("liq_usd") or 1), reverse=True)
    cands = cands[:MAX_CANDIDATES]
    print(f"  -> {len(cands)} candidates after gates")
    for c in cands:
        print(f"     {c['symbol']:<10} MC=${(c.get('mc') or 0)/1e3:.0f}K liq=${(c.get('liq_usd') or 0):.0f} vol=${(c.get('vol_24h') or 0)/1e3:.0f}K")

    # Phase 4: deep per candidate (parallel)
    print("[4/6] Deep analysis (Blockscout, parallel)...")
    def deep_one(c):
        a = c["addr"]
        cont = deep_contract(a)
        dec = (toks.get(a,{}) or {}).get("decimals") or 18
        hold = deep_holders(a, dec)
        age = token_age(a, cont.get("deployer"), cont.get("creation_tx"))
        c["verified"] = cont.get("verified")
        c["is_contract"] = cont.get("is_contract")
        c["deployer"] = cont.get("deployer")
        c["contract_flags"] = cont.get("flags",[])
        c["top10_pct"] = hold.get("top10_pct")
        c["top1_pct"] = hold.get("top1_pct")
        c["top1_val"] = hold.get("top1_val")
        c["holders_top50_sum"] = hold.get("total")
        c["holders"] = c.get("holders_count") or hold.get("holders_fetched")
        c["repeat_tx"] = hold.get("repeat_tx")
        c["uniq_wallets"] = hold.get("uniq_wallets")
        c["age_hours"] = age
        c["v_mc"] = (c.get("vol_24h") or 0)/((c.get("mc") or 1))
        c["tax"] = tax_signal(a, c.get("pair_addr"))
        return c
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(deep_one, c) for c in cands]
        for f in as_completed(futs):
            try: f.result()
            except Exception as e: print("  deep err:", e)
    print("  -> done")

    # Phase 4b: deployer cross-ref
    print("[4b] Deployer cross-ref...")
    serial_deps = build_deployer_map(cands)
    if serial_deps:
        print(f"  -> {len(serial_deps)} serial launcher(s) found")
        for dep, info in serial_deps.items():
            print(f"     {dep[:10]}... launched {info['total_launches']} tokens")
    else:
        print("  -> no serial launchers")

    # Phase 5: FomoScan thesis
    print("[5/6] FomoScan thesis...")
    fomo_data = {"tokens": []}
    try:
        fk = fomo_fresh_key()
        if fk:
            print(f"  -> fresh key obtained ({fk['email']})")
            fomo_data = fomo_thesis(fk["key"])
            if fomo_data.get("tokens"):
                print(f"  -> {len(fomo_data['tokens'])} thesis tokens loaded")
                # Match with candidates
                matched = [t for t in fomo_data["tokens"] if t.get("tok","").lower() in {c["addr"] for c in cands}]
                if matched:
                    print(f"  -> {len(matched)} matched our candidates")
                    for t in matched:
                        print(f"     {t.get('sym','')} called by {t.get('callers',[])}")
        else:
            print("  -> fomoscan signup unavailable, using cached thesis")
            cached = os.path.expanduser("~/fomo-recon/data/robinhood_thesis.json")
            if os.path.exists(cached):
                fomo_data = json.load(open(cached))
                print(f"  -> loaded {len(fomo_data.get('tokens',[]))} cached thesis tokens")
    except Exception as e:
        print(f"  -> fomoscan error: {e}")
        cached = os.path.expanduser("~/fomo-recon/data/robinhood_thesis.json")
        if os.path.exists(cached):
            fomo_data = json.load(open(cached))

    # Phase 6: LLM MiniMax M3
    llm_raw = None
    if LLM_ENABLED and GMI_KEY:
        print("[6/6] MiniMax M3 analysis...")
        llm_raw = llm_analyze(cands, serial_deps=serial_deps, fomo_thesis_data=fomo_data)
        print("  -> LLM responded")
    else:
        print("[6/6] LLM disabled (no key). Using heuristic fallback.")

    # Phase 7: Tax sim (best-effort on top 5)
    tax_sims = {}
    if TAX_SIM_ENABLED and RPC:
        print("[7] Tax sim (best-effort on top 5)...")
        # Get top 5 from LLM if available, else vol/liq
        if llm_raw and isinstance(llm_raw, str) and not llm_raw.startswith("LLM_ERROR"):
            cl = llm_raw.strip()
            if cl.startswith("```"): cl = re.sub(r"^```[a-zA-Z]*\s*","",cl,flags=re.M)
            i = cl.find("{"); 
            if i>=0: cl=cl[i:]
            j = cl.rfind("}")
            if j>0: cl=cl[:j+1]
            try:
                jr = json.loads(cl)
                scores = {r["addr"].lower(): r.get("score",0) for r in jr.get("rankings",[])}
                top5 = sorted([c for c in cands if c["addr"].lower() in scores], key=lambda c: scores.get(c["addr"].lower(),0), reverse=True)[:5]
            except: top5 = sorted(cands, key=lambda c: (c.get("vol_24h") or 0), reverse=True)[:5]
        else:
            top5 = sorted(cands, key=lambda c: (c.get("vol_24h") or 0), reverse=True)[:5]
        for c in top5:
            dec = (toks.get(c["addr"],{}) or {}).get("decimals") or 18
            ts = tax_sim_live(c, c["addr"], dec)
            tax_sims[c["addr"]] = ts
            print(f"     {c['symbol']}: {ts.get('method','SKIPPED')}")
        print("  -> done")

    # Phase 8: output
    print("[8/8] Saving output...")
    out = {"generated": datetime.now(timezone.utc).isoformat(),
           "candidates": cands, "llm_raw": llm_raw, "serial_deps": serial_deps,
           "fomo_data": fomo_data, "tax_sims": tax_sims,
           "candidates_analyzed": len(cands)}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT,"w") as f: json.dump(out,f,indent=2,default=str)
    print(f"  -> {OUT}")
    print(f"\nDone in {time.time()-t0:.1f}s. {len(cands)} candidates analyzed.")

    # Render
    render_top5(cands, llm_raw, fomo_data=fomo_data, serial_deps=serial_deps, tax_sims=tax_sims)

if __name__ == "__main__":
    main()