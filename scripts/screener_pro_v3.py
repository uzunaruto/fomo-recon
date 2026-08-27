#!/usr/bin/env python3
"""
MICIN SCREENER PRO v3 — LLM-driven (MiniMax M3)
================================================
Architecture:
  Phase 0  Init            : config + gmi (MiniMax M3) client
  Phase 1  DISCOVER        : Blockscout ERC-20 scan (fast, paginate)
  Phase 2  DEXENRICH       : DexScreener MC/liq/vol/price (batch)
  Phase 3  HARD GATES      : MC<5M, liq, vol quality, exclude dust/obvious
  Phase 4  DEEP (Blockscout): holders conc, wash, contract safety, deployer, age, tax
  Phase 5  LLM MINIMAX M3  : qualitative scoring, market phase, entry, anti-wash, TOP5
  Phase 6  OUTPUT          : structured report + save JSON

Chain: 4663 / robinhood. Blockscout-first (fast, no RPC bottleneck).
RPC (swap sim / tax) is BEST-EFFORT with timeout — never blocks the pipeline.
"""
import json, urllib.request, time, os, sys, math, urllib.parse
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------- CONFIG ----------
BS = "https://robinhoodchain.blockscout.com/api/v2"
RPC = "http://127.0.0.1:8098/rpc"          # optional best-effort
FACTORY = "0x1f7d7550b1b028f7571e69a784071f0205fd2efa"
UA = "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36"
MAX_CANDIDATES = 14        # deep-analyze this many
LLM_ENABLED = True
LLM_TIMEOUT = 120
OUT = os.path.expanduser("~/fomo-recon/data/pro_v3_ranking.json")

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

# ---------- HTTP ----------
def _dec(v):
    try: return int(v)
    except Exception: return 18

def bs(path, timeout=20):
    try:
        req = urllib.request.Request(BS+path, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ERR": str(e)}

def ds(tokens):
    """DexScreener batch lookup. tokens: list of addr (max 30/call)."""
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
                    out[a] = {
                        "pair_addr": p.get("pairAddress",""),
                        "dex": p.get("dexId",""), "chain": p.get("chainId",""),
                        "price_usd": p.get("priceUsd"),
                        "liq_usd": (p.get("liquidity",{}) or {}).get("usd"),
                        "liq_base": (p.get("liquidity",{}) or {}).get("base"),
                        "liq_quote": (p.get("liquidity",{}) or {}).get("quote"),
                        "vol_24h": (p.get("volume",{}) or {}).get("h24"),
                        "txn_buy_24h": ((p.get("txns",{}) or {}).get("h24",{}) or {}).get("buys"),
                        "txn_sell_24h": ((p.get("txns",{}) or {}).get("h24",{}) or {}).get("sells"),
                        "price_chg_24h": (p.get("priceChange",{}) or {}).get("h24"),
                        "fdv": p.get("fdv"), "mc": p.get("marketCap"),
                    }
        except Exception:
            pass
        time.sleep(0.4)
    return out

# ---------- PHASE 1: DISCOVER ----------
def discover(max_pages=4):
    """Blockscout ERC-20 tokens, most recent created first."""
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
        # Blockscout next_page_params already contains full filter set
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

# ---------- PHASE 4: DEEP (Blockscout) ----------
def parse_val(v, decimals):
    try:
        if isinstance(v, dict): return int(v.get("value",0)) / (10**decimals)
        return int(v) / (10**decimals)
    except Exception: return 0

def deep_contract(addr):
    """Verified + ABI owner/mint/freeze/blacklist detection."""
    j = bs(f"/addresses/{addr}")
    info = {"verified": False, "is_contract": False, "deployer": None,
            "creation_tx": None, "creation_ts": None, "flags": []}
    if isinstance(j, dict) and not j.get("ERR"):
        info["is_contract"] = j.get("is_contract", False)
        info["verified"] = j.get("is_verified", False)
        info["deployer"] = (j.get("creator_address_hash") or "").lower() or None
        info["creation_tx"] = j.get("creation_transaction_hash") or None
    # ABI-based owner/mint detection via smart-contract endpoint
    c = bs(f"/smart-contracts/{addr}")
    if isinstance(c, dict) and not c.get("ERR"):
        abi = c.get("abi")
        if isinstance(abi, str):
            try: abi = json.loads(abi)
            except Exception: abi = None
        if isinstance(abi, list):
            names = {x.get("name","") for x in abi if x.get("type")=="function"}
            info["flags"] = [f for f in ("owner","mint","pause","blacklist","freeze","transferOwnership","renounceOwnership","setTax","setFee","_transfer","excludeFromFee","isExcludedFromFee","addBlackList","removeBlackList") if f in names]
    return info

def deep_holders(addr, decimals, topn=20):
    """Top-N holder concentration + wash detection via transfers."""
    res = {"total": None, "top10_pct": None, "top1_pct": None, "top1_val": None,
           "holders_fetched": 0, "transfers": [], "repeat_tx": 0, "uniq_wallets": 0}
    # holders
    h = bs(f"/tokens/{addr}/holders?items_count=50")
    items = h.get("items", [])
    total_supply = parse_val((h.get("total_supply") if isinstance(h.get("total_supply"),dict) else None), decimals) or None
    # fallback: use sum
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
    # transfers - wash analysis (default 50 items; items_count param unsupported)
    tr = bs(f"/tokens/{addr}/transfers")
    txs = []
    for it in tr.get("items", []):
        frm = (it.get("from") or {}).get("hash","")
        to  = (it.get("to") or {}).get("hash","")
        txs.append((frm.lower(), to.lower(), it.get("timestamp",""), it.get("tx_hash","")))
    res["transfers"] = txs
    # repeat tx detection (same from+to pair seen >1x = potential wash)
    pair_count = {}
    for f,t,ts,h in txs:
        k = f+"|"+t
        pair_count[k] = pair_count.get(k,0)+1
    res["repeat_tx"] = sum(1 for v in pair_count.values() if v > 1)
    res["uniq_wallets"] = len({x[0] for x in txs} | {x[1] for x in txs})
    return res

def token_age(addr, deployer, creation_tx):
    """Approx age via creation tx timestamp on Blockscout."""
    if not creation_tx: return None
    j = bs(f"/transactions/{creation_tx}")
    if isinstance(j, dict) and not j.get("ERR"):
        ts = j.get("timestamp")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z","+00:00"))
                return (datetime.now(timezone.utc) - dt).total_seconds()/3600
            except Exception: pass
    return None

def tax_signal(addr, pair_addr, dec_reverse=None):
    """BEST-EFFORT: compare pool slot0 marginal price vs DexScreener price.
    Only attempts RPC; never blocks. Returns dict or None on timeout/error."""
    if not pair_addr or not RPC: return None
    try:
        # slot0 = sqrtPriceX96 / tick / observationIndex / observationCardinality / ...
        body = json.dumps({"jsonrpc":"2.0","id":1,"method":"eth_call",
            "params":[{"to":pair_addr,"data":"0x3850c7bd"}, "latest"]})
        req = urllib.request.Request(RPC, data=body.encode(),
            headers={"Content-Type":"application/json","User-Agent":UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = json.loads(r.read().decode()).get("result","")
        if not raw or raw == "0x": return None
        # ABI: 0x slot0 returns (uint160 sqrtPriceX96, int24 tick, ...)
        sqrt = int(raw[2:66], 16)  # first 32 bytes
        if sqrt == 0: return None
        # marginal price = (sqrt/2^96)^2
        price = (sqrt / 2**96) ** 2
        return {"sqrt": sqrt, "price_ratio": price, "method": "pool_slot0"}
    except Exception:
        return None

# ---------- PHASE 5: LLM MINIMAX M3 ----------
def llm_call(prompt, system="You are an expert crypto/on-chain analyst."):
    body = {"model": GMI_MODEL,
            "messages":[{"role":"system","content":system},{"role":"user","content":prompt}]}
    req = urllib.request.Request(GMI_BASE+"/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","Authorization":f"Bearer {GMI_KEY}","User-Agent":UA})
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as r:
        return json.loads(r.read().decode())["choices"][0]["message"]["content"]

def llm_analyze(cands):
    """Feed candidate JSON to MiniMax M3 for qualitative scoring + ranking."""
    pack = [{
        "addr": c["addr"], "symbol": c.get("symbol"), "name": c.get("name"),
        "mc": c.get("mc"), "liq_usd": c.get("liq_usd"), "vol_24h": c.get("vol_24h"),
        "v_mc": round(c.get("v_mc",0),2), "holders": c.get("holders"),
        "top10_pct": round(c.get("top10_pct") or 0,1), "top1_pct": round(c.get("top1_pct") or 0,1),
        "verified": c.get("verified"), "contract_flags": c.get("contract_flags",[]),
        "deployer": c.get("deployer"), "age_hours": round(c.get("age_hours") or 0,1),
        "repeat_tx": c.get("repeat_tx"), "uniq_wallets": c.get("uniq_wallets"),
        "price_usd": c.get("price_usd"), "price_chg_24h": c.get("price_chg_24h"),
    } for c in cands]
    prompt = f"""You are scoring {len(cands)} micro-cap tokens on Robinhood chain (4663, Uniswap V3).
Anti-trap rules: reject coins whose volume is wallet-clusters/insiders churning. Never assume high volume=organic, many wallets=independent, low MC=upside, good narrative=good token. Tax + exitability are the decisive signals.
Scoring weights (total 100): Narrative 15 | Smart Money 10 (cap) | Whale 10 | Liquidity 15 | Volume/Momentum 5 | Tokenomics 10 | Contract Safety 15 (hard gate: unverified+owner=auto-reject) | Holder Distribution Quality 20.
Return JSON ONLY:
{{"rankings":[
  {{"addr":"0x..","score":0,"conviction":1-10,"phase":"VERY_EARLY|EARLY|GOOD_ENTRY|EXTENDED|OVERHEATED|DISTRIBUTION","narrative":"1 line","smart_money":"yes/no/unknown","wash_risk":0.0-1.0,"wash_reason":"...","entry":"AGGRESSIVE|CONSERVATIVE|DIP|NO_ENTRY","entry_zone":"$X-$Y","invalidation":"...","tp1":"$","tp2":"$","tp3":"$","rr":"1:2","risk":"top risk","enter":[3 reasons],"avoid":[3 reasons]}}
], "best_overall":"0x..","best_early":"0x..","best_meme":"0x..","best_utility":"0x..","best_rr":"0x..","highest_risk":"0x..","avoid":"0x..","watch3":["0x..","0x..","0x.."],"summary":"2-3 sentence final market summary"}}
Candidate data:
{json.dumps(pack, default=str)}"""
    try:
        raw = llm_call(prompt)
        return raw
    except Exception as e:
        return f"LLM_ERROR: {e}"

# ---------- MAIN ----------
def main():
    import urllib.parse
    print("=== MICIN SCREENER PRO v3 (MiniMax M3) ===")
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
        # keep real holders_count from discover; don't overwrite with top-50 sum
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

    # Phase 5: LLM MiniMax M3
    llm_raw = None
    if LLM_ENABLED and GMI_KEY:
        print("[5/6] MiniMax M3 analysis...")
        llm_raw = llm_analyze(cands)
        print("  -> LLM responded")
    else:
        print("[5/6] LLM disabled (no key). Using heuristic fallback.")

    # Phase 6: output
    print("[6/6] Saving output...")
    out = {"generated": datetime.now(timezone.utc).isoformat(),
           "candidates": cands, "llm_raw": llm_raw,
           "candidates_analyzed": len(cands)}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT,"w") as f: json.dump(out,f,indent=2,default=str)
    print(f"  -> {OUT}")
    print(f"\nDone in {time.time()-t0:.1f}s. {len(cands)} candidates analyzed.")

    # ---- inline TOP 5 render (sorted by LLM score if available, else vol/liq) ----
    clean_llm = llm_raw
    if isinstance(llm_raw, str) and llm_raw.strip().startswith("```"):
        import re
        m = re.search(r"```(?:json)?\s*(.*?)```", llm_raw, re.S)
        if m: clean_llm = m.group(1).strip()
    if isinstance(clean_llm, str) and not clean_llm.startswith("LLM_ERROR") and clean_llm.strip().startswith("{"):
        try:
            jr = json.loads(clean_llm)
            score = {r["addr"].lower(): r for r in jr.get("rankings",[])}
            for c in cands:
                r = score.get(c["addr"].lower())
                if r: c["llm_score"] = r.get("score"); c["llm_conv"] = r.get("conviction"); c["llm_phase"]=r.get("phase")
            print("\n"+"="*60+"\n  MICIN SCREENER PRO v3 — TOP RANKING (MiniMax M3)\n"+"="*60)
            top = [c for c in cands if c.get("llm_score") is not None]
            top.sort(key=lambda c: c.get("llm_score",0), reverse=True)
            for i,c in enumerate(top[:5],1):
                print(f"\n  #{i} {c.get('symbol','?'):<8} {c.get('name','')[:22]:<22} score={c.get('llm_score')} conviction={c.get('llm_conv')}")
                print(f"     phase={c.get('llm_phase')}  MC=${(c.get('mc') or 0)/1e3:.0f}K  liq=${(c.get('liq_usd') or 0):.0f}  vol24=${(c.get('vol_24h') or 0)/1e3:.0f}K  V/MC={(c.get('v_mc') or 0):.1f}")
                print(f"     holders={c.get('holders')} top10={c.get('top10_pct')}% top1={c.get('top1_pct')}%  verified={c.get('verified')}  age={c.get('age_hours')}h")
                print(f"     flags={c.get('contract_flags')}")
                r = score.get(c["addr"].lower())
                if r:
                    print(f"     entry={r.get('entry')} zone={r.get('entry_zone')} tp1={r.get('tp1')} tp2={r.get('tp2')} tp3={r.get('tp3')} rr={r.get('rr')}")
                    print(f"     enter: {r.get('enter')}")
                    print(f"     avoid: {r.get('avoid')}")
                    print(f"     risk: {r.get('risk')}  wash={r.get('wash_risk')} ({r.get('wash_reason')})")
                print(f"     CA: {c['addr']}")
        except Exception as e:
            print("  render err:", e)

if __name__ == "__main__":
    main()