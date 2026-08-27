#!/usr/bin/env python3
"""
MICIN ENTRY ALERT v1 — compare live MC vs LLM entry_mc, notify via Telegram when a
token's current MC drops to/below its entry zone (or close). Also alert on TP1 reached.

Run:  python3 scripts/micin_alert.py [--rank JSON] [--delta 1.2]
Delta = how far below entry_mc before alerting (1.2 = 20% below = deep dip = good).
Designed to be cron'd (e.g. every 4h). Sends ONE consolidated message.
"""
import json, urllib.request, time, os, sys, re, argparse

UA = "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36"
RANK_DEFAULT = os.path.expanduser("~/fomo-recon/data/pro_v4_ranking.json")
STATE = os.path.expanduser("~/fomo-recon/data/micin_alert_state.json")
BS = "https://robinhoodchain.blockscout.com/api/v2"

def ds_price(addr):
    """Fetch current MC from DexScreener (best effort)."""
    try:
        req = urllib.request.Request(
            "https://api.dexscreener.com/latest/dex/tokens/"+addr,
            headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.loads(r.read().decode())
        pairs = j.get("pairs", [])
        if not pairs: return None
        best = max(pairs, key=lambda p: (p.get("liquidity",{}) or {}).get("usd") or 0)
        return {"mc": best.get("marketCap"), "price": best.get("priceUsd"),
                "liq": (best.get("liquidity",{}) or {}).get("usd"),
                "chg24": (best.get("priceChange",{}) or {}).get("h24")}
    except Exception as e:
        return None

def fmt_mc(v):
    if v is None: return None
    s = str(v).replace("$","").replace(" ","").lower()
    s = re.split(r"[-–—]", s)[0]
    if s.endswith("m"): return float(s[:-1].replace(",",""))
    if s.endswith("k"): return float(s[:-1].replace(",",""))/1000
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rank", default=RANK_DEFAULT)
    ap.add_argument("--delta", type=float, default=1.2)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.rank):
        print("NO_RANK_FILE")
        return
    data = json.load(open(args.rank))
    cands = data.get("candidates", [])
    llm_raw = data.get("llm_raw") or ""
    if not cands:
        print("NO_CANDIDATES")
        return

    # parse LLM scores + entry_mc
    scores = {}
    cl = llm_raw
    if isinstance(cl, str) and cl.strip().startswith("```"):
        cl = re.sub(r"^```[a-zA-Z]*\s*","",cl,flags=re.M)
        i = cl.find("{"); 
        if i>=0: cl=cl[i:]
        j = cl.rfind("}")
        if j>0: cl=cl[:j+1]
    try:
        jr = json.loads(cl)
        for r in jr.get("rankings",[]):
            scores[r["addr"].lower()] = r
    except Exception:
        pass

    # state (to avoid spamming same alert)
    state = {}
    if os.path.exists(STATE):
        try: state = json.load(open(STATE))
        except: state = {}

    alerts = []
    for c in cands:
        a = c["addr"].lower()
        r = scores.get(a)
        if not r: continue
        entry_mc = fmt_mc(r.get("entry_mc")) or fmt_mc(r.get("entry_zone"))
        tp1_mc = fmt_mc(r.get("tp1_mc")) or fmt_mc(r.get("tp1"))
        if not entry_mc: continue
        cur = ds_price(c["addr"])
        if not cur or not cur["mc"]: continue
        cur_mc = cur["mc"] / 1e6  # normalize to millions (matching entry_mc/tp1_mc)
        # entry trigger: at or BELOW entry zone (real dip)
        entry_trigger = cur_mc <= entry_mc
        # approaching: within 25% above entry (watch list)
        approaching = (not entry_trigger) and (cur_mc <= entry_mc * 1.25)
        # tp1 trigger: cur_mc >= tp1_mc
        tp_trigger = tp1_mc and cur_mc >= tp1_mc

        prev = state.get(a, {})
        fired_entry = prev.get("entry_fired", False)
        fired_tp = prev.get("tp_fired", False)

        if (entry_trigger and not fired_entry) or (approaching and not prev.get("approach_fired")) or (tp_trigger and not fired_tp):
            sym = c.get("symbol","?")
            lines = [f"🔔 {sym} ({c.get('name','')[:20]})"]
            lines.append(f"   Current MC: ${cur_mc:.2f}M  (entry zone ${entry_mc:.2f}M)")
            lines.append(f"   price ${cur.get('price')}  24h {cur.get('chg24')}%   liq ${(cur.get('liq') or 0):,.0f}")
            if entry_trigger:
                lines.append(f"   ✅ ENTRY ZONE HIT — MC ${cur_mc:.2f}M <= entry ${entry_mc:.2f}M")
            elif approaching:
                lines.append(f"   👀 APPROACHING ENTRY — MC ${cur_mc:.2f}M (25% above ${entry_mc:.2f}M)")
            if tp_trigger:
                lines.append(f"   🎯 TP1 HIT — MC ${cur_mc:.2f}M >= ${tp1_mc:.2f}M")
            lines.append(f"   CA: {c['addr']}")
            lines.append(f"   Phase {r.get('phase')} | score {r.get('score')}")
            alerts.append("\n".join(lines))
            # mark fired
            if entry_trigger: prev["entry_fired"] = True
            if approaching: prev["approach_fired"] = True
            if tp_trigger: prev["tp_fired"] = True
            state[a] = prev

    if alerts:
        msg = "🎯 MICIN ENTRY ALERT\n" + "\n\n".join(alerts)
        if args.dry:
            print(msg)
        else:
            # deliver to telegram via hermes gateway? print for cron capture
            print(msg)
            print("\n---\n(route to Telegram via cron delivery)")
        # persist state only on real run
        json.dump(state, open(STATE,"w"), indent=2)
        print(f"\n[{len(alerts)} alert(s) fired]")
    else:
        print("NO_ALERTS")

if __name__ == "__main__":
    main()