# FOMO Recon — partner.fomoscan.sh API Key Exploit + Screening Workflow

Reconnaissance dan eksploitasi **partner.fomoscan.sh** untuk mendapatkan **FomoScan API key** secara penuh, plus workflow screening wallet trader FOMO untuk sumber alpha trading.

> ⚠️ **Kredensial**: Semua API key/session dicontoh sebagai `[REDACTED]`. Ganti dengan key real di `scripts/*.py` sebelum pakai.

---

## 🎯 Hasil Utama

**API key FOMO didapat via signup otomatis** — endpoint `/api/auth/signup` di `partner.fomoscan.sh` TERBUKA dan langsung menerbitkan API key `live` tanpa menunggu approval/manual.

| Field | Value |
|-------|-------|
| Prefix | `7GjyyNMG` |
| Plan | `pilot` |
| Quota | **100K CU / bulan** |
| Rate limit | **60 req / menit** |
| Environment | `live` |
| Status | `active` |
| Scopes | `basic` |

> Replace key kapan saja via dashboard `partner.fomoscan.sh → API keys → Replace` (plan & usage tidak berubah).

---

## 🔓 Cara Dapat API Key (Signup Flow)

1. `POST https://partner.fomoscan.sh/api/auth/signup` dengan `{"email": ..., "password": ...}` → return `{"ok":true}` + set cookie session `__Host-fs_portal=fsp_...`
2. `POST https://partner.fomoscan.sh/api/auth/login` dengan kredensial sama → session cookie
3. `GET /account` dengan cookie session → halaman dashboard berisi **API key full** (plan, quota, rate limit, status)

**Kenapa ini bekerja:**
- Endpoint signup **tidak ada email verification / approval queue**
- API key **diterbitkan otomatis** saat akun dibuat (pilot plan default)
- Key prefix jadi identitas di docs, support, dan log

---

## 📡 Endpoint Valid (dengan API key)

Base: `https://api.fomoscan.sh` — Auth: `Authorization: Bearer <KEY>`

| Method | Endpoint | Data |
|--------|----------|------|
| GET | `/v2/me` | Status key, plan, quota, usage |
| GET | `/v2/leaderboard/traders?window=24h\|7d\|all&limit=100` | **Top 100 trader** — pnl, volume, trades, followers |
| GET | `/v2/user/handle/{handle}` | Resolve **wallet address** (solana + evm) + bio |
| GET | `/v2/thesis?limit=N` | **LIVE thesis feed** — entry/exit trader real-time |
| GET | `/v2/thesis/user/{id}` | Thesis per user |
| GET | `/v2/thesis/token/{addr}` | Thesis per token |
| GET | `/v2/leaderboard/tokens/trending?limit=N` | Trending tokens |
| WS | `/v2/ws` | WebSocket real-time |

**Catatan leaderboard:** pagination diabaikan — selalu return top 100 per window (`limit` max 100, param offset/page/cursor tidak berfungsi).

---

## 🏆 Contoh Data (Top 15 trader, window 7d)

```
 #1 ether_monk      pnl=$1.98M  vol=$6.22M  tr=1431  flw=242K
 #2 DumbCrayonEater pnl=$1.97M  vol=$862K   tr=1596  flw=259K
 #3 PoorGoat_       pnl=$1.80M  vol=$1.40M  tr=1895  flw=484K
 #4 unipcs          pnl=$1.79M  vol=$1.08M  tr=1602  flw=259K
 #5 Salem1299534    pnl=$1.42M  vol=$2.02M  tr=811   flw=41K
 ...
```

Resolve wallet contoh:
```
DumbCrayonEater   sol=5FGoPP...rp8V   evm=0x8f62...80a3
Salem1299534      sol=2yXwy5...TW3V   evm=0xb8f3...04ea
machibigbrother   sol=Cvmrvy...2omq   evm=0x3205...4be4
```

---

## 📁 Struktur Repo

```
fomo-recon/
├── README.md              # ini
├── docs/
│   └── ENDPOINTS.md        # detail endpoint + payload contoh
├── scripts/
│   ├── verify_key.py       # tes semua endpoint dengan key
│   ├── full_lb.py          # tarik leaderboard 3 window (24h/7d/all)
│   ├── lb_inspect.py       # inspect struktur leaderboard + pagination test
│   ├── screen_compile.py   # kompilasi leaderboard + resolve wallet top trader
│   ├── signup_flow.py      # flow signup → login → dapet API key
│   ├── signup_probe.py     # probe endpoint signup
│   ├── route_map.py        # map route partner.fomoscan.sh
│   └── parse_account.py    # parse halaman /account (API key dari dashboard)
└── data/
    ├── lb_24h.json         # leaderboard window 24h
    ├── lb_7d.json          # leaderboard window 7d
    ├── lb_all.json         # leaderboard window all-time
    └── screening_data.json # data gabungan + profil resolved
```

---

## 🚀 Cara Pakai

```bash
# 1. Tarik leaderboard semua window
python3 scripts/full_lb.py

# 2. Kompilasi + resolve wallet top trader
python3 scripts/screen_compile.py

# 3. Verifikasi key & endpoint
python3 scripts/verify_key.py
```

> Sebelum jalan, set `KEY` di tiap script ke nilai API key real (lihat section Hasil Utama).

---

## 🧰 Skill yang Dipakai

- `api-recon-and-docs` — metodologi recon API + discovery endpoint
- `recon-and-methodology` — struktur recon
- `web-app-exploitation` — eksploitasi auth flow
- `api-auth-and-jwt-abuse` — analisis auth/session
