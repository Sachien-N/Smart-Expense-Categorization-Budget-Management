# CSI3007 Combined System Architecture — Three-App Integration

**Course:** CSI3007 Advanced Python Programming
**Team:** Person A — Sachien N (23MID0255) · Person B — Shravan N A (23MID0445) · Person C — Hariharan S (23MID0182)

This document describes how the three **independent** Python applications
communicate. Each app has its own FastAPI backend, its own database and its own
Streamlit frontend; nothing shares a database file or schema, and every
cross-app interaction is a documented HTTP REST + JSON contract.

## 1. Big picture

```
                                   ┌──────────────────────────────┐
                                   │  Google Sheets + Apps Script │
                                   │  (Person A UI record store)  │
                                   └──────────▲───────────────────┘
                                              │ GET ?key=...&type=... /
                                              │ POST {key,type,id,data}
                                              │ (API_SECRET in Script Properties)
 ┌─────────────────────┐   REST/JSON   ┌──────┴───────────────────────┐
 │ Person B            │               │ Person A                     │
 │ Subscription        │──GET          │ Expense Categorization &     │
 │ Renewal & Cost      │  /integration ├──────────────────────────────┤
 │ Tracker             │  /export      │ • /expenses /budgets         │
 │ (FastAPI :8002)     │               │ • /summary /categorize       │
 └─────────────────────┘               │ • /integrations/sync (pull)  │
                                       │ (FastAPI :8001)              │
 ┌─────────────────────┐               └──────▲───────────────────────┘
 │ Person C            │──GET                        │
 │ Smart Home Energy   │  /history?months=6          │ Streamlit UI
 │ Monitoring & Bills  │  /bill/estimate             │ (Sheet-storage mode,
 │ (FastAPI :8003)     │  /tariffs                   │  + BACKEND_API_URL
 └─────────────────────┘                             │  for live sync)
                                                     ▼
                                       Person A Streamlit dashboard
```

- **Person A is the central expense dashboard.** It *pulls* from B and C; it
  never exposes write endpoints that others push into.
- **Person B supplies subscription expenses** (monthly-normalized cost of every
  active subscription, per calendar month).
- **Person C supplies electricity bills** (estimated and actual, per calendar
  month) plus consumption history.
- **Person A's Streamlit UI** keeps its records in Google Sheets through an
  Apps Script Web App (`API_URL`, authenticated with `API_SECRET` stored in
  Script Properties). The same UI can additionally call A's FastAPI backend
  (`BACKEND_API_URL`) to show live peer status, trigger the sync, and mirror
  imported expenses into the sheet.

## 2. Deployed services

| App | Backend (Render) | Frontend (Streamlit Cloud) |
|---|---|---|
| A | https://smart-expense-categorization-budget.onrender.com | https://smart-expense-categorization-budget-management-zeb9vcqhbfecckc.streamlit.app/ |
| B | https://subscription-tracker-api-ihiq.onrender.com | https://subscription-tracker-guvbi3jyccotmcqhh3uegw.streamlit.app/ |
| C | https://smart-home-energy-api.onrender.com | https://personc-ehwhch8swvjfrmuybqe2ry.streamlit.app/ |

Each backend is configured with peer base URLs through environment variables
(`SUBSCRIPTION_API_URL`, `ELECTRICITY_API_URL` on A) and keeps its own
database (PostgreSQL on Render, SQLite locally).

## 3. Contract: Person B → Person A

`GET {B}/integration/export` →
```json
{"service": "...", "contract_version": "1.0", "generated_at": "...",
 "count": 2,
 "subscriptions": [{"external_ref": "B-SUB-1", "name": "Netflix",
   "category": "Streaming", "plan": "Premium", "tags": [],
   "billing_frequency": "monthly", "amount": 649.0, "monthly_cost": 649.0,
   "currency": "INR", "active": true, "next_renewal_date": "2026-11-20"}]}
```

- `amount` is **per billing period**; `monthly_cost` is already normalized
  (weekly ×52/12, monthly ×1, quarterly ÷3, yearly ÷12).
- The payload intentionally includes inactive rows; A filters them out
  (`skipped_inactive`).
- A imports each **active, INR** subscription as ONE `Subscriptions` expense
  for the calendar month in which the sync runs, dated the 1st:
  `external_id = B:{external_ref}:{YYYY-MM}` (unique → idempotent),
  `import_basis = monthly_normalized`.
- Re-syncing the same month: price change → **update in place** (`updated`),
  unchanged → skipped (`already_imported`). Never a duplicate.

## 4. Contract: Person C → Person A

`GET {C}/history?months=6` →
```json
{"months": [{"month": "2026-10", "estimated_kwh": 271.4, "actual_kwh": 280.0,
   "estimated_amount": 1091.5, "actual_amount": 1210.0,
   "deviation_percent": 9.79, "needs_investigation": false}],
 "tariff_name": "TNEB-Domestic-Monthly-Seed",
 "tariff_verified": false,
 "estimate_disclaimer": "..."}
```

- Deviation semantics: `D = actual − estimated`;
  `deviation_percent = |D| / |actual| × 100` on the amount basis when both
  amounts are > 0, else on the kWh basis, else `null` — zero-estimated and
  zero-actual values are handled safely.
- A imports every **settled** month (actual bill present, or a closed month
  with a positive estimate) as ONE `Bills` expense:
  `external_id = C:{YYYY-MM}` (unique → idempotent). The running month is
  never imported; when an actual bill arrives later, the estimate row is
  **upgraded in place** — an estimate and its actual are never double-counted.
- Tariff slabs are **configurable** database records and every estimate is
  served with a `verified: false` disclaimer unless verified against the
  official TNEB/TANGEDCO tariff order.

## 5. Idempotency and failure handling (cross-cutting rules)

1. **Stable identities**: every imported expense carries a unique
   `external_id`; the second run of any sync produces **zero** new rows.
2. **Bounded I/O**: outbound calls use pooled sessions, explicit
   connect/read timeouts (3 s / 10 s default; raise read timeout to ~60 s for
   free-tier cold starts) and bounded retries for idempotent GETs only
   (connection errors, timeouts, 5xx; linear backoff).
3. **Contract validation**: responses are checked for required keys and JSON
   shape; violations are reported as `invalid_response`, never crash a service.
4. **Partial failures are isolated**: B down does not stop C's import and
   vice-versa; sync returns per-source statuses
   (`ok | empty | unavailable | timeout | unauthorized | invalid_response |
   not_configured | misconfigured`) and never HTTP 500.
5. **No shared databases**: each app owns its schema; integration happens
   exclusively through the HTTP contracts above.
6. **Duplicate defense in depth**: unique `external_id` + pre-check +
   `IntegrityError` catch in A, plus a manual-duplicate heuristic
   (same-name/same-amount manual expenses block the import).

## 6. Google Sheets data path (Person A UI)

- Spreadsheet: <https://docs.google.com/spreadsheets/d/1hNjUhKQn-QfZp3VWd_gzLQsCQoAzYHtahTSkFk1mE8U/edit>
- Apps Script Web App (`API_URL`): <https://script.google.com/macros/s/AKfycbzHRuhVpr-tiUFuZE2GA2BIEcRA2aUMhFUmBlkyjxyAf7pyyWfRU022oxs5J9LfngaH-Q/exec>
- Protocol: `GET {API_URL}?key={API_SECRET}&type=expenses|budgets` and
  `POST {API_URL}` with `{key, type, id, data}`; responses are
  `{ok: true, records: [...]}` / `{ok: false, error: "..."}`.
- **Security**: `API_SECRET` lives in Apps Script **Script Properties** and in
  Streamlit Secrets / env vars only — never in code, docs or git history. The
  secret was exposed in a chat in 2026-11 and must be **rotated** (see
  `RENDER_DEPLOYMENT.md` / `ENVIRONMENT_SETUP.md` for the rotation steps).
- The UI's Integrations page (when `BACKEND_API_URL` is set) proxies status +
  sync to A's FastAPI backend and mirrors backend-imported expenses into the
  sheet, matching rows on `external_id` so this mirror is also idempotent.

## 7. End-to-end flow (faculty demo script)

1. Add subscriptions in **B** (e.g. Netflix ₹649/month, Prime ₹1499/year) and
   appliances + readings + an actual bill in **C**.
2. Open **A's** Streamlit dashboard → Integrations → *Check integration
   status* (both peers `available`) → *Start sync*.
3. Show the sync JSON: B `imported: 2` (yearly plan normalized to
   ₹124.92/month, inactive subscription skipped), C `imported: 1` settled
   month (`import_basis: actual`).
4. Press *Start sync* again → `imported: 0` everywhere (idempotency).
5. Dashboard → budget comparison and `by_source` split show the imported
   money separately from manual expenses.
6. Kill B (or let Render sleep) → sync again → B reported `unavailable`, C
   still imports, dashboard stays up (partial-failure handling).
