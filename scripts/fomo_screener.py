#!/usr/bin/env python3
"""
FOMO Screener v2 — screening wallet trader dari platform FomoScan (fomo.family)
Cocok untuk workflow screening alpha dari tweet @magersih / smart money.

Fitur:
  1. Tarik leaderboard trader (24h/7d/all) dari api.fomoscan.sh
  2. SMART-MONEY SCORE: kombinasi profit + followers + konsistensi trade
     (deteksi trader beneran vs "lucky" satu-hit-wonder)
  3. Resolve wallet address (solana + evm) per handle
  4. THESIS ALPHA SCANNER: auto-detect token yang di-entry trader top,
     cek MC/liquidity/volume via DexScreener, skor alpha
  5. Simpan hasil ke CSV + JSON, cetak report ringkas

Cara pakai:
  python3 fomo_screener.py [--window 24h|7d|all] [--top N] [--min-pnl X] [--min-vol X]
                           [--alpha] [--no-thesis] [--report]
"""
import argparse, csv, json, os, sys, time, urllib.request

# ⚠️ GANTI dengan API key real (dari partner.fomoscan.sh → API keys)
KEY = os.environ.get("FOMOSCAN_KEY", "[REDACTED]")
BASE = "https://api.fomoscan.sh"
DEXS = "https://api.dexscreener.com/latest/dex/tokens"
UA = {"User-Agent": "Mozilla/5.0", "Authorization": f"Bearer {KEY}"}

OUTDIR = os.path.dirname(os.path.abspath(__file__)) + "/../data"


# ──────────────────────────────────────────────────────────────
# API helpers
# ──────────────────────────────────────────────────────────────
def api(path, retries=3):
    for i in range(retries):
        req = urllib.request.Request(BASE + path, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="ignore")
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


def dexscreener(tokens):
    """Cek MC/liq/volume via DexScreener (gratis, tanpa key). tokens = list CA."""
    if not tokens:
        return {}
    out = {}
    # batch max 30 per request
    for i in range(0, len(tokens), 30):
        batch = tokens[i:i + 30]
        url = f"{DEXS}/{','.join(batch)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode())
            for p in d.get("pairs", []):
                base = (p.get("baseToken") or {}).get("address", "")
                if not base:
                    continue
                chain = p.get("chainId", "?")
                price = float(p.get("priceUsd") or 0)
                mc = float((p.get("marketCap") or 0) or 0)
                liq = float((p.get("liquidity") or {}).get("usd") or 0)
                vol = float((p.get("volume") or {}).get("h24") or 0)
                ch5m = float((p.get("priceChange") or {}).get("m5") or 0)
                ch1h = float((p.get("priceChange") or {}).get("h1") or 0)
                ch6h = float((p.get("priceChange") or {}).get("h6") or 0)
                ch24 = float((p.get("priceChange") or {}).get("h24") or 0)
                # pilih pair dengan liq terbesar per token
                prev = out.get(base)
                if prev is None or liq > prev["liquidity"]:
                    out[base] = {
                        "chain": chain, "price": price, "mc": mc, "liquidity": liq,
                        "vol24": vol, "ch5m": ch5m, "ch1h": ch1h,
                        "ch6h": ch6h, "ch24h": ch24,
                        "pair": f"https://dexscreener.com/{chain}/{p.get('pairAddress','')}",
                        "dex": (p.get("dexId") or "?"),
                        "symbol": (p.get("baseToken") or {}).get("symbol", "?"),
                    }
        except Exception:
            pass
        time.sleep(1.2)
    return out


def trunc(addr, n=8):
    if not addr:
        return None
    return f"{addr[:n]}...{addr[-4:]}" if len(addr) > n + 5 else addr


# ──────────────────────────────────────────────────────────────
# Smart money scoring
# ──────────────────────────────────────────────────────────────
def smart_score(e):
    """
    Skor 0-100: trader beneran (smart money) vs lucky.
    - Profit (max 30): pnl besar = kuat
    - Efisiensi pnl/trade (max 15): profit per trade sehat
    - Konsistensi (max 20): numTrades banyak = bukan one-hit-wonder
    - Sosial proof (max 20): followers = reputasi
    - Volume (max 15): volume = aktivitas nyata
    Flags: LUCKY (pnl tinggi tapi trade dikit), SUS (pnl/trade gak wajar)
    """
    pnl = e.get("pnl") or 0
    vol = e.get("volume") or 0
    flw = e.get("followers") or 0
    tr = e.get("numTrades") or 0

    score = 0
    # 1. profit (30)
    if pnl >= 2_000_000: score += 30
    elif pnl >= 1_000_000: score += 24
    elif pnl >= 500_000: score += 18
    elif pnl >= 250_000: score += 12
    elif pnl >= 100_000: score += 6

    # 2. efisiensi pnl/trade (15) — profit per trade
    eff = pnl / tr if tr > 0 else 0
    if eff >= 5_000: score += 15
    elif eff >= 2_000: score += 12
    elif eff >= 1_000: score += 9
    elif eff >= 500: score += 6
    elif eff >= 200: score += 3

    # 3. konsistensi (20) — banyak trade = bukan satu keberuntungan
    if tr >= 2000: score += 20
    elif tr >= 1000: score += 16
    elif tr >= 500: score += 12
    elif tr >= 200: score += 8
    elif tr >= 80: score += 4

    # 4. sosial proof (20)
    if flw >= 250_000: score += 20
    elif flw >= 100_000: score += 16
    elif flw >= 50_000: score += 12
    elif flw >= 20_000: score += 8
    elif flw >= 5_000: score += 4

    # 5. volume (15)
    if vol >= 10_000_000: score += 15
    elif vol >= 5_000_000: score += 12
    elif vol >= 2_000_000: score += 9
    elif vol >= 1_000_000: score += 6
    elif vol >= 300_000: score += 3

    # flags
    flags = []
    if pnl >= 300_000 and tr < 50:
        flags.append("LUCKY")          # pnl gede tapi trade dikit → satu hit
    if eff >= 20_000 and tr < 100:
        flags.append("SUS")            # pnl/trade gak wajar
    if pnl <= 0:
        flags.append("LOSING")
    if flw >= 200_000 and tr >= 800:
        flags.append("WHALE")          # influensial + aktif
    if pnl >= 500_000 and tr >= 800:
        flags.append("SERIOUS")

    return score, flags


# ──────────────────────────────────────────────────────────────
# Alpha scanner
# ──────────────────────────────────────────────────────────────
def alpha_score(tok):
    """
    Skor alpha 0-100 buat kandidat token dari thesis:
    - Likuiditas (30): liq >= 10K wajib (bisa keluar)
    - Volume/aktivitas (25): vol24
    - Momentum harga (20): 5m/1h positif
    - Ukuran MC (15): prefer kecil-menengah (ruang pump)
    - Referensi (10): masuk dari trader mana (diberi bobot by caller)
    """
    liq = tok.get("liquidity") or 0
    vol = tok.get("vol24") or 0
    mc = tok.get("mc") or 0
    ch5m = tok.get("ch5m") or 0
    ch1h = tok.get("ch1h") or 0

    score = 0
    # likuiditas (30) — safety dulu
    if liq >= 100_000: score += 30
    elif liq >= 50_000: score += 25
    elif liq >= 20_000: score += 20
    elif liq >= 10_000: score += 14
    elif liq >= 5_000: score += 8

    # volume (25)
    if vol >= 500_000: score += 25
    elif vol >= 200_000: score += 20
    elif vol >= 100_000: score += 16
    elif vol >= 50_000: score += 12
    elif vol >= 20_000: score += 8
    elif vol >= 5_000: score += 4

    # momentum (20)
    if ch5m >= 5 and ch1h >= 10: score += 20
    elif ch5m >= 2 and ch1h >= 5: score += 15
    elif ch1h >= 0: score += 8
    elif ch1h < -10: score -= 5

    # market cap (15) — kecil-menengah = ruang pump
    if 0 < mc <= 500_000: score += 15
    elif mc <= 2_000_000: score += 12
    elif mc <= 10_000_000: score += 8
    elif mc <= 50_000_000: score += 5
    elif mc <= 0: pass  # gak ada data

    return max(0, min(100, score))


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────
def fetch_leaderboard(window="24h", limit=100):
    c, d = api(f"/v2/leaderboard/traders?window={window}&limit={limit}")
    if c != 200 or "entries" not in d:
        print(f"  ❌ leaderboard {window}: [{c}] {d.get('error','?')}")
        return []
    return d["entries"]


def resolve_profiles(handles, max_n=15, delay=0.35):
    """
    Resolve wallet SOL+EVM untuk daftar handle.
    CATATAN: endpoint /v2/user/handle/{handle} memakan CU gede per call
    (pilot 100K CU/bulan). Bisa QUOTA_EXCEEDED (402) cepat. Graceful:
    stop saat quota habis, jangan boros CU tersisa.
    """
    out = {}
    for i, h in enumerate(handles[:max_n]):
        c, d = api(f"/v2/user/handle/{h}")
        if c == 402:  # QUOTA_EXCEEDED — stop biar hemat CU
            print(f"  ⚠️ quota habis pas resolve '{h}', stop resolve wallet", file=sys.stderr)
            break
        if c == 200 and "solanaAddress" in d:
            out[h] = {
                "name": d.get("name"), "solana": d.get("solanaAddress"),
                "evm": d.get("evmAddress"), "bio": (d.get("bio") or "")[:80],
            }
        time.sleep(delay)
    return out


def fetch_thesis(limit=40):
    c, d = api(f"/v2/thesis?limit={limit}")
    if c != 200 or "items" not in d:
        return []
    return d["items"]


def main():
    ap = argparse.ArgumentParser(description="FOMO Screener v2")
    ap.add_argument("--window", default="7d", choices=["24h", "7d", "all"])
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--min-pnl", type=float, default=0)
    ap.add_argument("--min-vol", type=float, default=0)
    ap.add_argument("--min-followers", type=int, default=0)
    ap.add_argument("--min-trades", type=int, default=0)
    ap.add_argument("--min-score", type=int, default=0, help="smart-score minimum (0-100)")
    ap.add_argument("--alpha", action="store_true", help="jalankan thesis alpha scanner")
    ap.add_argument("--no-thesis", action="store_true")
    args = ap.parse_args()

    if KEY == "[REDACTED]":
        print("❌ Set API key dulu: FOMOSCAN_KEY=... python3 fomo_screener.py")
        sys.exit(1)

    print(f"🔍 FOMO Screener v2 — window={args.window}")
    os.makedirs(OUTDIR, exist_ok=True)

    # 1. leaderboard
    entries = fetch_leaderboard(args.window)
    if not entries:
        print("❌ Gagal ambil leaderboard. Cek key / koneksi.")
        sys.exit(1)
    print(f"  ✅ leaderboard: {len(entries)} trader")

    # 2. filter dasar
    before = len(entries)
    entries = [e for e in entries
               if (args.min_pnl <= 0 or (e.get("pnl") or 0) >= args.min_pnl)
               and (args.min_vol <= 0 or (e.get("volume") or 0) >= args.min_vol)
               and (args.min_followers <= 0 or (e.get("followers") or 0) >= args.min_followers)
               and (args.min_trades <= 0 or (e.get("numTrades") or 0) >= args.min_trades)]
    print(f"  ✅ filter dasar: {before} → {len(entries)}")

    # 3. smart score
    for e in entries:
        e["smart_score"], e["smart_flags"] = smart_score(e)
    if args.min_score:
        before = len(entries)
        entries = [e for e in entries if e["smart_score"] >= args.min_score]
        print(f"  ✅ filter smart-score >= {args.min_score}: {before} → {len(entries)}")
    entries.sort(key=lambda x: x["smart_score"], reverse=True)

    # 4. resolve wallet
    top_handles = [e["handle"] for e in entries[:args.top]]
    print(f"  🔑 resolve wallet {min(len(top_handles), 15)} handle...")
    profiles = resolve_profiles(top_handles)

    # 5. thesis + alpha
    thesis, alpha = [], []
    if not args.no_thesis:
        print("  📡 tarik live thesis...")
        thesis = fetch_thesis()
        if args.alpha and thesis:
            print("  ⚡ alpha scanner: cek token dari thesis via DexScreener...")
            # token yang disebut trader, dedupe
            tok_mentions = {}
            for t in thesis:
                addr = t.get("tokenAddress")
                if not addr:
                    continue
                if addr not in tok_mentions:
                    tok_mentions[addr] = {"count": 0, "authors": []}
                tok_mentions[addr]["count"] += 1
                tok_mentions[addr]["authors"].append(t.get("authorHandle", "?"))

            ds = dexscreener(list(tok_mentions.keys()))
            for addr, m in tok_mentions.items():
                info = ds.get(addr, {})
                if not info:
                    continue
                # bonus referensi: multiple mention = stronger
                ref_bonus = min(10, (m["count"] - 1) * 4)
                sc = alpha_score(info) + ref_bonus
                alpha.append({**info, "token": addr, "mentions": m["count"],
                              "authors": m["authors"][:4], "alpha_score": sc})
            alpha.sort(key=lambda x: x["alpha_score"], reverse=True)
            print(f"  ✅ alpha: {len(alpha)} token kandidat dari {len(tok_mentions)} unik")

    # 6. simpan
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = f"{OUTDIR}/fomo_{args.window}_{ts}"

    with open(base + ".csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "handle", "pnl_usd", "volume_usd", "followers", "num_trades",
                    "smart_score", "flags", "solana_wallet", "evm_wallet", "name"])
        for e in entries[:args.top]:
            p = profiles.get(e["handle"], {})
            w.writerow([e.get("rank"), e["handle"], round(e.get("pnl") or 0, 2),
                        round(e.get("volume") or 0, 2), e.get("followers"), e.get("numTrades"),
                        e["smart_score"], "|".join(e["smart_flags"]) or "-",
                        p.get("solana"), p.get("evm"), p.get("name")])

    payload = {
        "window": args.window, "generated_at": ts,
        "leaderboard_count": len(entries),
        "traders": [
            {**e, "solana": (profiles.get(e["handle"]) or {}).get("solana"),
             "evm": (profiles.get(e["handle"]) or {}).get("evm")}
            for e in entries[:args.top]
        ],
        "thesis": thesis, "alpha": alpha,
    }
    with open(base + ".json", "w") as f:
        json.dump(payload, f, indent=1, default=str)

    # 7. report
    print("\n" + "=" * 78)
    print(f"📊 FOMO SCREENING REPORT — window {args.window}  (smart-money scored)")
    print("=" * 78)
    print(f"{'#':>2} {'handle':<20} {'score':>5} {'pnl($)':>11} {'vol($)':>12} {'tr':>5} {'flw':>7}  flags")
    print("-" * 78)
    for e in entries[:args.top]:
        fl = "|".join(e["smart_flags"]) or "-"
        print(f"{e.get('rank',0):>2} {e['handle']:<20} {e['smart_score']:>5} "
              f"{e.get('pnl') or 0:>11,.0f} {e.get('volume') or 0:>12,.0f} "
              f"{e.get('numTrades') or 0:>5} {e.get('followers') or 0:>7,}  {fl}")

    # wallet resolved
    print("\n🔑 WALLET RESOLVED:")
    for h in top_handles[:15]:
        p = profiles.get(h, {})
        if p:
            print(f"  {h:<20} sol={trunc(p.get('solana'),7) or '-':<20} evm={trunc(p.get('evm'),7) or '-'}")

    if alpha:
        print("\n" + "=" * 78)
        print("⚡ ALPHA CANDIDATES (token dari thesis trader, cek MC/liq/volume)")
        print("=" * 78)
        print(f"{'score':>5} {'sym':<8} {'chain':<6} {'mc($)':>12} {'liq($)':>11} {'vol24($)':>11} {'5m':>6} {'1h':>6}  mentioned_by")
        print("-" * 78)
        for a in alpha[:12]:
            print(f"{a['alpha_score']:>5} {a.get('symbol','?'):<8} {a.get('chain','?'):<6} "
                  f"{a.get('mc') or 0:>12,.0f} {a.get('liquidity') or 0:>11,.0f} "
                  f"{a.get('vol24') or 0:>11,.0f} {a.get('ch5m') or 0:>+5.1f}% {a.get('ch1h') or 0:>+5.1f}%  "
                  f"{','.join(a['authors'][:3])}")

    print(f"\n💾 saved: {base}.csv | {base}.json")
    print(f"📄 trader: {len(entries)} | wallet: {len(profiles)} | thesis: {len(thesis)} | alpha: {len(alpha)}")

    with open(f"{OUTDIR}/latest.txt", "w") as f:
        f.write(base)
    print(f"\n✨ Done.")


if __name__ == "__main__":
    main()
