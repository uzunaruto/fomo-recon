#!/usr/bin/env python3
"""
MICIN COMBINED REPORT — merge MAIN (under 5M) + MICRO (<1M) rankings, curate,
render a single Telegram-ready list with copy-friendly CAs, MC in $M.
Curated = score >= threshold AND entry not NO_ENTRY AND verified AND not serial deployer.
Prints (deliverable) to stdout. Silent if nothing passes curation.
"""
import json, os, sys, re

BASE = os.path.expanduser("~/fomo-recon/data")
FILES = ["pro_v4_ranking.json", "pro_v4_micro_ranking.json"]  # MAIN first, then MICRO
SCORE_MIN = float(os.environ.get("MICIN_SCORE_MIN", "30"))
STATE = os.path.expanduser("~/fomo-recon/data/micin_report_state.json")

def fmt_mc(v):
    if v is None: return None
    s = str(v).replace("$","").replace(" ","").lower()
    s = re.split(r"[-–—]", s)[0]
    if s in ("","n/a","none","-"): return None
    try:
        if s.endswith("m"): return float(s[:-1].replace(",",""))
        if s.endswith("k"): return float(s[:-1].replace(",",""))/1000
        return float(s)
    except: return None

def load_llm(d):
    llm = d.get("llm_raw","")
    if not isinstance(llm,str) or not llm.strip(): return {}
    if llm.strip().startswith("```"):
        llm = re.sub(r"^```[a-zA-Z]*\s*","",llm,flags=re.M)
    i=llm.find("{"); j=llm.rfind("}")
    if i<0 or j<=i: return {}
    try:
        return {r.get("addr","").lower(): r for r in json.loads(llm[i:j+1]).get("rankings",[])}
    except: return {}

def main():
    merged = {}   # addr -> {meta, llm}
    for f in FILES:
        p = os.path.join(BASE, f)
        if not os.path.exists(p): continue
        d = json.load(open(p))
        scores = load_llm(d)
        for c in d.get("candidates",[]):
            a = c["addr"].lower()
            if a in merged: continue  # dedupe, MAIN wins
            merged[a] = {"meta": c, "llm": scores.get(a,{})}

    state = {}
    if os.path.exists(STATE):
        try: state = json.load(open(STATE))
        except: state = {}

    curated = []
    for a, e in merged.items():
        m = e["meta"]; r = e["llm"]
        score = r.get("score") or 0
        entry = r.get("entry") or "NO_ENTRY"
        verified = m.get("verified", False)
        serial = bool(m.get("serial_dep")) or ("serial" in (r.get("avoid") and " ".join(r.get("avoid") or [])).lower()) or ("repeat deployer" in (r.get("avoid") and " ".join(r.get("avoid") or [])).lower()) or bool(m.get("deployer_launches") and m.get("deployer_launches")>=2)
        # curated gate
        if score < SCORE_MIN: continue
        if entry in ("NO_ENTRY","N/A",None,""): continue
        if not verified: continue
        if serial: continue
        entry_mc = fmt_mc(r.get("entry_mc")) or fmt_mc(r.get("entry_zone"))
        if entry_mc is None: continue
        mc = (m.get("mc") or 0)/1e6
        curated.append({"addr": a, "sym": (m.get("symbol") or r.get("symbol") or "?"), "score": score,
                        "entry_mc": entry_mc, "mc": mc, "r": r, "m": m})

    curated.sort(key=lambda x: x["score"], reverse=True)

    if not curated:
        print("NO_CURATED")
        return

    # deliverable
    lines = []
    lines.append("🎯 MICIN KURASI (gabungan micro + <5M)")
    lines.append(f"   {len(curated)} token layak entry | score ≥{SCORE_MIN:.0f}, verified, bukan serial")
    lines.append("")
    for x in curated:
        r = x["r"]; m = x["m"]
        lines.append(f"#{x['score']} {x['sym']}")
        lines.append(f"   MC ${x['mc']:.2f}M → entry ${x['entry_mc']:.2f}M | score {x['score']} | phase {r.get('phase')}")
        tp1 = fmt_mc(r.get("tp1_mc")); tp2 = fmt_mc(r.get("tp2_mc")); tp3 = fmt_mc(r.get("tp3_mc"))
        tps = []
        if tp1: tps.append(f"TP1 ${tp1:.2f}M")
        if tp2: tps.append(f"TP2 ${tp2:.2f}M")
        if tp3: tps.append(f"TP3 ${tp3:.2f}M")
        if tps: lines.append(f"   {' | '.join(tps)}")
        if r.get("enter"):
            lines.append(f"   → {'; '.join(r['enter'][:2])}")
        if r.get("avoid"):
            lines.append(f"   ⚠ {'; '.join(r['avoid'][:2])}")
        lines.append(f"   CA: `{m['addr']}`")
        lines.append("")
    print("\n".join(lines))

if __name__ == "__main__":
    main()
