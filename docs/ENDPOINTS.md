# FomoScan API — Endpoint Reference

Base URL: `https://api.fomoscan.sh`
Auth: `Authorization: Bearer <API_KEY>`
Rate: 60 req/min (pilot), Quota: 100K CU/month

---

## Authentication

```
GET /v2/me
Authorization: Bearer <KEY>
```
Response:
```json
{
  "key": {"prefix": "7GjyyNMG", "name": "user@mail.com", "environment": "live"},
  "plan": "pilot",
  "scopes": ["basic"],
  "entitlement": {"monthlyUnits": 100000, "ratePerMinute": 60},
  "usage": {"period": "2026-08", "unitsUsed": 0, "unitsRemaining": 100000}
}
```

---

## Leaderboard — Traders

```
GET /v2/leaderboard/traders?window=24h|7d|all&limit=100
```
- `window`: 24h, 7d, all (default 24h)
- `limit`: max 100 (pagination diabaikan)
- Entry fields: `rank, id, handle, label, avatarUrl, pnl, volume, followers, numTrades, memberCount, marketCap, price, liquidity`

Response shape:
```json
{
  "board": "traders",
  "window": "24h",
  "capturedAt": 1787822174237,
  "count": 100,
  "entries": [
    {"rank": 1, "id": "...", "handle": "...", "pnl": 681804.7, "volume": 862377.0, "followers": 259536, "numTrades": 1596}
  ]
}
```

---

## User Profile (resolve wallet)

```
GET /v2/user/handle/{handle}
```
Response keys: `id, handle, name, bio, banner, profilePicture, twitter, solanaAddress, evmAddress`

Ini endpoint kunci untuk workflow screening — resolve **wallet SOL + EVM** dari handle trader.

---

## Thesis Feed (live entry/exit)

```
GET /v2/thesis?limit=N
GET /v2/thesis/user/{id}
GET /v2/thesis/token/{addr}
```
Response:
```json
{
  "count": 20, "hasMore": true, "nextBefore": "...", "updatedAt": 1787822214338,
  "items": [
    {"id": "...", "authorHandle": "...", "thesis": "...", "fomoCreatedAt": ..., "tokenAddress": "..."}
  ]
}
```

---

## Trending Tokens

```
GET /v2/leaderboard/tokens/trending?limit=N
```
Entry fields: `rank, id, handle, label, volume, numTrades, memberCount, marketCap, price, liquidity`

---

## WebSocket

```
WS /v2/ws
```
Real-time feed (belum dianalisis penuh).

---

## Signup / Auth (partner.fomoscan.sh)

```
POST https://partner.fomoscan.sh/api/auth/signup   {"email": "...", "password": "..."} → {"ok":true} + session cookie
POST https://partner.fomoscan.sh/api/auth/login    {"email": "...", "password": "..."} → {"ok":true} + Set-Cookie __Host-fs_portal=fsp_...
GET  https://partner.fomoscan.sh/account           (with session cookie) → dashboard berisi API key
```

Session cookie: `__Host-fs_portal=fsp_...` (Secure, HttpOnly, SameSite=lax, Max-Age 30d)

---

## Subdomain Map

| Subdomain | Fungsi |
|-----------|--------|
| `partner.fomoscan.sh` | Dashboard partner — signup/login, API key, billing |
| `admin.fomoscan.sh` | Admin/operator panel — `/keys`, login `/api/auth` (terpisah, operator-only) |
| `api.fomoscan.sh` | Public API (butuh key) |
| `terminal.fomoscan.sh` | Terminal — library code, tanpa data feed |
| `www.fomoscan.sh` | Frontend publik — leaderboard gratis (top 15), halaman profil `/{handle}` |
