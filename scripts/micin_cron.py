#!/usr/bin/env python3
"""
MICIN SCREENER CRON WRAPPER — runs full v4 scan then alert check.
Output goes to stdout (captured by cron delivery). Prints concise alert summary
so the Telegram delivery only fires when something is actionable.
"""
import subprocess, os, sys, json, re

BASE = os.path.expanduser("~/fomo-recon")
RANK = os.path.join(BASE, "data", "pro_v4_ranking.json")

def run(cmd, timeout=600):
    try:
        return subprocess.run(cmd, cwd=BASE, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return None

def main():
    # 1) Full scan (updates ranking json). Silent unless fails.
    p = run(["python3", "scripts/screener_pro_v4.py"])
    if p is None or p.returncode != 0:
        err = (p.stderr or "no output")[-800:] if p else "timeout"
        print(f"MICIN SCAN ERROR:\n{err}")
        return
    # 2) Alert check — but only emit when there are real alerts.
    a = run(["python3", "scripts/micin_alert.py", "--rank", RANK])
    if a is None:
        print("MICIN ALERT: no output (likely NO_ALERTS)")
        return
    out = (a.stdout or "").strip()
    if not out or out == "NO_ALERTS":
        return  # silent — nothing actionable
    if "NO_ALERTS" in out and "🔔" not in out:
        return
    print(out)

if __name__ == "__main__":
    main()