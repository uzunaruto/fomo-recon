#!/usr/bin/env python3
"""
FOMO Whale Tracker — rekomendasi coin early yang dibeli top whale + smart wallet.
Cross-reference: live thesis feed (siapa yang lagi entry token apa) x tracked whales.

Sumber:
  - api.fomoscan.sh/v2/thesis  (live entry/exit trader, butuh API key)
  - api.dexscreener.com        (MC, liquidity, volume, momentum — gratis)

Output: daftar token early (MC kecil) yang lagi disorot trader yang kita track.
"""
import os, sys, json, time, urllib.request, urllib.parse, argparse, datetime

KEY = os.environ.get("FOMOSCAN_KEY", "")
BASE = "https://api.fomoscan.sh"
DS   = "https://api.dexscreener.com/latest/dex"

# Top smart-money whales hasil screening (score tinggi + flags WHALE/SERIOUS)
TRACKED_WHALES = {
    "ether_monk":      "WHALE pnl 2.0M",
    "Aurelius0121":    "WHALE pnl 1.5M",
    "change":          "WHALE vol 22M",
    "unipcs":          "WHALE pnl 1.9M",
    "DumbCrayonEater": "WHALE pnl 2.0M",
    "PoorGoat_":       "WHALE flw 485K",
    "loganlim_x":      "SERIOUS vol 8.7M",
    "theveeman":       "SERIOUS pnl 793K",
    "Quanterty":       "WHALE flw 235K",
    "brrrgrrrz":       "SERIOUS pnl 1.0M",
    "0xleo":           "SERIOUS vol 22M",
    "Salem1299534":    "SERIOUS pnl 1.4M",
}

def api(path):
    req = urllib.request.Request(BASE + path,
          headers={"User-Agent": "Mozilla/5.0", "Authorization": f"Bearer {KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:
        return 0, {}

def dex(tokens):
    """Batch fetch DexScreener untuk daftar token (max 30)."""
    q = ",".join(tokens[:30])
    req = urllib.request.Request(f"{DS}/tokens/{q}", headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode()).get("pairs", [])
    except Exception:
        return []

def fmt(n, d=0):
    try: return f"{n:,.{d}f}"
    except: return "?"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-mc", type=float, default=30_000_000, help="MC max (early filter)")
    ap.add_argument("--min-liq", type=float, default=5_000, help="liq min")
    ap.add_argument("--no-tracked-only", action="store_true", help="termasuk semua author, bukan cuma tracked")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not KEY:
        print("❌ set FOMOSCAN_KEY env"); sys.exit(1)

    print("🔍 FOMO Whale Tracker — cari coin early yang dibeli whale")
    c, d = api("/v2/thesis")
    if c != 200:
        print(f"❌ thesis gagal [{c}] (quota? cek /v2/me)"); sys.exit(1)
    items = d.get("data") or d.get("items") or (d if isinstance(d, list) else [])
    print(f"  ✅ thesis: {len(items)} live")

    # token yang di-call author, dedupe by tokenAddress
    calls = {}   # token -> {symbol, authors:[], authorSet, best}
    for it in items:
        tok = it.get("tokenAddress") or ""
        if not tok: continue
        author = it.get("authorHandle") or "?"
        sym = it.get("tokenSymbol") or tok[:6]
        e = calls.setdefault(tok, {"symbol": sym, "authors": [], "authorSet": set(), "network": it.get("tokenNetwork"), "theses": []})
        if author not in e["authorSet"]:
            e["authorSet"].add(author)
            e["authors"].append(author)
        e["theses"].append({"author": author, "text": (it.get("thesis") or "")[:100],
                            "pnl": it.get("realizedPnlUsd"), "holdings": it.get("holdingsUsd")})

    print(f"  ✅ {len(calls)} token unik dari thesis")
    if not calls:
        print("  (belum ada thesis dengan token address)"); sys.exit(0)

    # fetch DexScreener untuk semua token
    print("  📈 cek DexScreener (MC/liq/vol)...")
    pairs = dex(list(calls.keys()))
    bytok = {}
    for p in pairs:
        bytok.setdefault(p.get("baseToken", {}).get("address", ""), []).append(p)

    rows = []
    for tok, e in calls.items():
        ps = bytok.get(tok, [])
        if not ps: continue
        # pilih pool paling liquid
        p = max(ps, key=lambda x: float(x.get("liquidity", {}).get("usd") or 0))
        mc = float(p.get("marketCap") or 0)
        liq = float(p.get("liquidity", {}).get("usd") or 0)
        vol24 = float(p.get("volume", {}).get("h24") or 0)
        px5m = float(p.get("priceChange", {}).get("m5") or 0)
        px1h = float(p.get("priceChange", {}).get("h1") or 0)
        px6h = float(p.get("priceChange", {}).get("h6") or 0)
        sym = p.get("baseToken", {}).get("symbol") or e["symbol"]
        chain = p.get("chainId") or e.get("network") or "?"
        url = f"https://dexscreener.com/{chain}/{tok}"
        rows.append({
            "tok": tok, "sym": sym, "chain": chain, "mc": mc, "liq": liq,
            "vol24": vol24, "5m": px5m, "1h": px1h, "6h": px6h, "url": url,
            "authors": e["authors"], "theses": e["theses"],
            "tracked": [a for a in e["authors"] if a in TRACKED_WHALES],
        })

    # filter early + liq cukup
    early = [r for r in rows if 0 < r["mc"] <= args.max_mc and r["liq"] >= args.min_liq]
    if not args.no_tracked_only:
        early = [r for r in early if r["tracked"]]   # harus ada whale yang kita track

    # score: makin kecil MC (early) + volume kuat + momentum bagus + banyak mention
    for r in early:
        sc = 0
        sc += max(0, 30 - (r["mc"] / 1_000_000) * 3)          # MC <10M = early bonus
        sc += min(20, r["vol24"] / r["mc"] * 5) if r["mc"] else 0  # vol/MC ratio
        sc += 15 if r["1h"] > 10 else 8 if r["1h"] > 0 else 2
        sc += 10 if r["5m"] > 5 else 5
        sc += min(15, len(r["authors"]) * 5)                  # makin banyak yang call
        sc += 10 if r["tracked"] else 0
        r["score"] = round(sc, 1)

    early.sort(key=lambda r: -r["score"])

    print("\n" + "=" * 100)
    print("🎯 EARLY COIN RECOMMENDATION — dibeli/nyebut whale yang kita track")
    print("=" * 100)
    if not early:
        print("  (tidak ada yang lolos filter — coba --max-mc lebih tinggi / --no-tracked-only)")
        sys.exit(0)
    print(f" {'#':<2} {'sym':<10} {'score':<6} {'MC($)':<11} {'liq($)':<9} {'vol24($)':<10} {'5m':>6} {'1h':>7} {'6h':>7}  callers")
    print("-" * 100)
    for i, r in enumerate(early[:20], 1):
        tracked_tag = "🔒" if r["tracked"] else " "
        print(f" {i:<2}{tracked_tag} {r['sym'][:10]:<10} {r['score']:<6} {fmt(r['mc']):<11} {fmt(r['liq']):<9} {fmt(r['vol24']):<10} {r['5m']:>+6.1f}% {r['1h']:>+7.1f}% {r['6h']:>+7.1f}%  {','.join(r['authors'][:4])}")

    print("\n🔍 DETAIL (yang di-call whale tracked):")
    for r in [x for x in early if x["tracked"]][:5]:
        print(f"\n  ● {r['sym']} ({r['chain']}) — score {r['score']} — MC ${fmt(r['mc'])} | liq ${fmt(r['liq'])} | vol24 ${fmt(r['vol24'])}")
        print(f"    momentum: 5m {r['5m']:+.1f}% | 1h {r['1h']:+.1f}% | 6h {r['6h']:+.1f}%")
        print(f"    dexscreener: {r['url']}")
        for t in r["theses"][:3]:
            tag = "🔒WHALE" if t["author"] in TRACKED_WHALES else "trader"
            print(f"    [{tag} {t['author']}] {t['text'][:80]}")

    if args.json:
        out = {"generated": datetime.datetime.now().isoformat(),
               "tracked_whales": len(TRACKED_WHALES), "candidates": early[:20]}
        print("\n" + json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
