#!/usr/bin/env python3
"""
FOMO Screener — screening wallet trader dari platform FomoScan (fomo.family)
Cocok untuk workflow screening alpha dari tweet @magersih / smart money.

Fitur:
  1. Tarik leaderboard trader (24h/7d/all) dari api.fomoscan.sh
  2. Filter otomatis berdasarkan kriteria (pnl, volume, followers, trades)
  3. Resolve wallet address (solana + evm) per handle
  4. Tarik live thesis feed (entry/exit trader real-time)
  5. Simpan hasil ke CSV + JSON, cetak report ringkas

Cara pakai:
  python3 fomo_screener.py [--window 24h|7d|all] [--top N] [--min-pnl X] [--min-vol X] [--report]
"""
import argparse, csv, json, os, sys, time, urllib.request

# ⚠️ GANTI dengan API key real (dari partner.fomoscan.sh → API keys)
KEY = os.environ.get("FOMOSCAN_KEY", "[REDACTED]")
BASE = "https://api.fomoscan.sh"
UA = {"User-Agent": "Mozilla/5.0", "Authorization": f"Bearer {KEY}"}

OUTDIR = os.path.dirname(os.path.abspath(__file__)) + "/../data"


def api(path, retries=3):
    """GET api.fomoscan.sh dengan retry + rate-limit aware."""
    for i in range(retries):
        req = urllib.request.Request(BASE + path, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="ignore")
            # rate limit → tunggu 65 detik lalu ulangi
            if e.code == 429 and i < retries - 1:
                wait = 65
                print(f"  ⏳ rate limited (429), tunggu {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            return e.code, {"error": body[:300]}
        except Exception as e:
            if i == retries - 1:
                return 0, {"error": str(e)[:150]}
            time.sleep(2)
    return 0, {"error": "retries exhausted"}


def trunc(addr, n=8):
    if not addr:
        return None
    return f"{addr[:n]}...{addr[-4:]}" if len(addr) > n + 5 else addr


def fetch_leaderboard(window="24h", limit=100):
    c, d = api(f"/v2/leaderboard/traders?window={window}&limit={limit}")
    if c != 200 or "entries" not in d:
        print(f"  ❌ leaderboard {window}: [{c}] {d.get('error','?')}")
        return []
    return d["entries"]


def resolve_profiles(handles, max_n=15, delay=0.35):
    """Resolve wallet SOL+EVM untuk daftar handle (rate 60/min → delay)."""
    out = {}
    for i, h in enumerate(handles[:max_n]):
        c, d = api(f"/v2/user/handle/{h}")
        if c == 200 and "solanaAddress" in d:
            out[h] = {
                "name": d.get("name"),
                "solana": d.get("solanaAddress"),
                "evm": d.get("evmAddress"),
                "bio": (d.get("bio") or "")[:80],
            }
        time.sleep(delay)  # jaga-jaga rate limit
    return out


def fetch_thesis(limit=30):
    c, d = api(f"/v2/thesis?limit={limit}")
    if c != 200 or "items" not in d:
        return []
    return d["items"]


def main():
    ap = argparse.ArgumentParser(description="FOMO Screener")
    ap.add_argument("--window", default="24h", choices=["24h", "7d", "all"])
    ap.add_argument("--top", type=int, default=15, help="jumlah trader di report")
    ap.add_argument("--min-pnl", type=float, default=0, help="filter pnl minimum ($)")
    ap.add_argument("--min-vol", type=float, default=0, help="filter volume minimum ($)")
    ap.add_argument("--min-followers", type=int, default=0)
    ap.add_argument("--min-trades", type=int, default=0)
    ap.add_argument("--no-thesis", action="store_true", help="skip thesis feed")
    args = ap.parse_args()

    if KEY == "[REDACTED]":
        print("❌ Set API key dulu: FOMOSCAN_KEY=... python3 fomo_screener.py")
        sys.exit(1)

    print(f"🔍 FOMO Screener — window={args.window}")
    os.makedirs(OUTDIR, exist_ok=True)

    # 1. Leaderboard
    entries = fetch_leaderboard(args.window)
    if not entries:
        print("❌ Gagal ambil leaderboard. Cek key / koneksi.")
        sys.exit(1)
    print(f"  ✅ leaderboard: {len(entries)} trader")

    # 2. Filter
    before = len(entries)
    entries = [e for e in entries
               if (args.min_pnl <= 0 or (e.get("pnl") or 0) >= args.min_pnl)
               and (args.min_vol <= 0 or (e.get("volume") or 0) >= args.min_vol)
               and (args.min_followers <= 0 or (e.get("followers") or 0) >= args.min_followers)
               and (args.min_trades <= 0 or (e.get("numTrades") or 0) >= args.min_trades)]
    print(f"  ✅ filter: {before} → {len(entries)} trader lolos")

    # 3. Resolve wallet top-N
    top_handles = [e["handle"] for e in entries[:args.top]]
    print(f"  🔑 resolve wallet {min(len(top_handles), 15)} handle...")
    profiles = resolve_profiles(top_handles)

    # 4. Thesis feed
    thesis = []
    if not args.no_thesis:
        print("  📡 tarik live thesis...")
        thesis = fetch_thesis()

    # 5. Simpan CSV + JSON
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = f"{OUTDIR}/fomo_{args.window}_{ts}"

    with open(base + ".csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "handle", "pnl_usd", "volume_usd", "followers",
                    "num_trades", "solana_wallet", "evm_wallet", "name", "bio"])
        for e in entries[:args.top]:
            p = profiles.get(e["handle"], {})
            w.writerow([e.get("rank"), e["handle"],
                        round(e.get("pnl") or 0, 2), round(e.get("volume") or 0, 2),
                        e.get("followers"), e.get("numTrades"),
                        p.get("solana"), p.get("evm"), p.get("name"), p.get("bio")])

    payload = {
        "window": args.window,
        "generated_at": ts,
        "leaderboard_count": len(entries),
        "traders": [
            {**e, "solana": (profiles.get(e["handle"]) or {}).get("solana"),
             "evm": (profiles.get(e["handle"]) or {}).get("evm")}
            for e in entries[:args.top]
        ],
        "thesis": thesis,
    }
    with open(base + ".json", "w") as f:
        json.dump(payload, f, indent=1, default=str)

    # 6. Report
    print("\n" + "=" * 68)
    print(f"📊 FOMO SCREENING REPORT — window {args.window}")
    print("=" * 68)
    print(f"{'#':>3} {'handle':<22} {'pnl($)':>12} {'vol($)':>13} {'tr':>5} {'flw':>8}  wallet(sol)")
    print("-" * 68)
    for e in entries[:args.top]:
        p = profiles.get(e["handle"], {})
        w = trunc(p.get("solana"), 7) or "-"
        print(f"{e.get('rank',0):>3} {e['handle']:<22} {e.get('pnl') or 0:>12,.0f} "
              f"{e.get('volume') or 0:>13,.0f} {e.get('numTrades') or 0:>5} "
              f"{e.get('followers') or 0:>8,}  {w}")

    if thesis:
        print("\n" + "=" * 68)
        print("📡 LIVE THESIS (entry/exit trader real-time)")
        print("=" * 68)
        seen = 0
        for t in thesis:
            if seen >= 10:
                break
            tok = (t.get("tokenAddress") or "")[:10] + "..."
            print(f"  [{t.get('authorHandle','?')}] {t.get('thesis','')[:60]} "
                  f"→ {tok} {time.strftime('%H:%M', time.localtime((t.get('fomoCreatedAt') or 0)/1000))}")
            seen += 1

    print(f"\n💾 saved: {base}.csv | {base}.json")
    print(f"📄 total trader: {len(entries)} | profil resolved: {len(profiles)} | thesis: {len(thesis)}")

    # simpan path terakhir untuk report delivery
    with open(f"{OUTDIR}/latest.txt", "w") as f:
        f.write(base)
    print(f"\n✨ Done. Path terakhir di {OUTDIR}/latest.txt")


if __name__ == "__main__":
    main()
