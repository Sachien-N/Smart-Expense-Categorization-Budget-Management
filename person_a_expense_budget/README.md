# Smart Expense Categorization & Budget Management (Person A)

CSI3007 - Advanced Python Programming | Person A: **Sachien N (23MID0255)**

A personal finance backend + dashboard that tracks expenses, auto-categorizes
merchants with **transparent keyword rules** (every suggestion is explainable),
manages monthly budgets with live utilization, and **integrates with two peer
apps strictly over HTTP REST**:

```
                  HTTP REST (JSON contracts only, no shared DB files)
   Person B ──► GET /integration/export ──┐
   (subscriptions)                        │
                                          ├──► Person A (this app)
   Person C ──► GET /history?months=6 ────┘      imports + categorizes + budgets
   (electricity bills)
```

## Features

- **Expenses**: create (manual or auto-categorized), list with filters
  (month / category / source), update, delete.
- **Rule-based categorizer**: priority-ordered keyword rules over six canonical
  categories (Food, Travel, Bills, Entertainment, Shopping, Subscriptions) plus
  an `Uncategorized` fallback bucket. `GET /categorize?merchant=Netflix`
  previews the decision with the matched keyword.
- **Budgets**: one limit per (category, month); live spent / remaining /
  utilization / over-budget comparison in both `GET /budgets` and `GET /summary`.
- **Monthly summary**: totals, per-category shares, budget comparison. An empty
  month is a valid zero, clearly distinguished from missing/invalid input.
- **Integrations (the CSI3007 headline)**: `POST /integrations/sync` pulls
  Person B's subscriptions (normalized monthly cost) and Person C's electricity
  bills into local expenses. Every import carries a **stable external id**
  (`B:B-SUB-4:2026-10`, `C:2026-09`) with a UNIQUE constraint, so re-running
  a sync **never duplicates**; an electricity estimate is upgraded in place
  when the actual bill arrives. Imported costs are labelled (`origin`,
  `import_basis`, `GET /summary` -> `by_source`) separately from manual ones.
  Outbound calls use a pooled session, explicit connect/read timeouts,
  bounded GET-only retries, contract-key validation, and a peer outage is
  reported per-source - it never breaks A or the other source.
- **Streamlit dashboard**: KPIs, donut chart of spend split, budget progress
  bars, expense CRUD, budget setup, category drill-down. The Integrations page
  shows **live peer status** and runs a one-click sync when `BACKEND_API_URL`
  is configured; imported expenses are mirrored into Google Sheets
  (idempotent on `external_id`).

## System architecture

Person A is the central expense hub of the three-app CSI3007 system. The full
three-app communication map (including the Google Sheets data path) lives in
[`SYSTEM_ARCHITECTURE.md`](./SYSTEM_ARCHITECTURE.md).

## Tech stack

| Layer     | Technology |
|-----------|------------|
| Backend   | Python 3.12, FastAPI, Pydantic v2 |
| Database  | SQLite via SQLAlchemy 2 (own file: `data/expense_budget.db`); PostgreSQL on Render |
| Frontend  | Streamlit + Plotly — stores expenses/budgets in **Google Apps Script + Google Sheets** (`API_URL` + `API_SECRET`); talks to the FastAPI backend for live integration status/sync when `BACKEND_API_URL` is set |
| Testing   | pytest + FastAPI TestClient (**48 tests**) |
| Deploy    | Render (backend, see `RENDER_DEPLOYMENT.md`) + Streamlit Community Cloud (frontend) |

## Deployment URLs (verified 2026-11-05)

| Service | URL | Status |
|---|---|---|
| Backend (Render) | https://smart-expense-categorization-budget.onrender.com/health | HTTP 200, `status: ok` |
| Frontend (Streamlit Cloud) | https://smart-expense-categorization-budget-management-zeb9vcqhbfecckc.streamlit.app/ | Deployed (viewer sign-in may be required) |
| Google Sheets data API | Apps Script Web App (`API_URL`) | Live, enforces `API_SECRET` (`{"ok":false,"error":"Unauthorized"}` without a key) |

## Quickstart

```bash
# 1. environment
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. configuration (placeholders only - edit as needed)
cp .env.example .env
#   Backend integration (optional locally): set SUBSCRIPTION_API_URL / ELECTRICITY_API_URL.
#   Frontend Sheets mode: set API_URL + API_SECRET (see .streamlit/secrets.toml.example)
#   and optionally BACKEND_API_URL for live integration status/sync.

# 3. demo data (optional but recommended)
python seed_data.py

# 4. backend (terminal 1)
uvicorn main:app --host 127.0.0.1 --port 8001 --reload

# 5. frontend (terminal 2)
streamlit run app.py

# 6. tests
python -m pytest -q
```

Interactive API docs: <http://127.0.0.1:8001/docs>

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `data/expense_budget.db` (SQLite) | Own database. Relative SQLite paths resolve against this folder; `postgres://`/`postgresql://` URLs (Render Postgres) are supported |
| `APP_PORT` | `8001` | Backend port (Render injects `$PORT` instead) |
| `API_URL` (frontend) | - | Google Apps Script Web App `/exec` URL — the Streamlit app's data store |
| `API_SECRET` (frontend) | - | Shared secret for the Apps Script API. **Must come from Streamlit Secrets / env — never hardcode it.** The same value must be stored in the Apps Script project's Script Properties |
| `BACKEND_API_URL` (frontend) | - | This FastAPI backend's public URL; enables live integration status + sync + Sheets mirroring in the UI |
| `API_BASE_URL` (frontend) | `http://127.0.0.1:8001` | Local fallback when `API_URL` is not set |
| `API_TIMEOUT_SECONDS` (frontend) | `60` | Frontend read timeout (covers Render cold starts) |
| `SUBSCRIPTION_API_URL` | - | Person B base URL (blank = integration off). Alias: `INTEGRATION_B_BASE_URL` |
| `ELECTRICITY_API_URL` | - | Person C base URL (blank = integration off). Alias: `INTEGRATION_C_BASE_URL` |
| `INTEGRATION_CONNECT_TIMEOUT_SECONDS` | `3.0` | Outbound connect timeout |
| `INTEGRATION_TIMEOUT_SECONDS` | `10.0` | Outbound read timeout (use ~60 when peers are free Render instances) |
| `INTEGRATION_MAX_RETRIES` | `2` | Bounded retries for GETs (connection errors, timeouts, 5xx only) |
| `INTEGRATION_RETRY_BACKOFF_SECONDS` | `0.5` | Linear backoff per attempt |

## API summary

Full reference with examples: `API_DOCUMENTATION.md`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness + DB probe |
| GET/POST | `/expenses` | List (filterable) / create (auto-categorize) |
| GET/PUT/DELETE | `/expenses/{id}` | Read / partial update / delete |
| GET | `/categories` | Six canonical + fallback |
| GET | `/category/{name}` | Drill-down with totals |
| GET | `/summary?month=YYYY-MM` | Monthly roll-up + budget comparison |
| GET | `/categorize?merchant=...` | Explainable suggestion preview |
| GET/POST | `/budgets` | List (with spent) / set limit |
| GET | `/integrations/status` | Live health of B and C |
| POST | `/integrations/sync` | Idempotent pull from B and C |

## Project structure

```
person_a_expense_budget/
├── main.py                  # FastAPI app + lifespan (create tables, seed categories)
├── config.py                # 12-factor env-var settings
├── database.py              # SQLAlchemy engine/session (own SQLite file)
├── models.py                # Category / Expense / Budget ORM models
├── schemas.py               # Pydantic v2 request/response contracts
├── crud.py                  # All DB access (routers never touch the ORM)
├── routers/
│   ├── expenses.py          # /expenses CRUD
│   ├── categories.py        # /categories, /category/{name}
│   ├── budgets.py           # /budgets
│   └── summary.py           # /summary, /categorize, /integrations/*
├── services/
│   ├── categorizer.py       # Transparent keyword rules (priority-ordered)
│   ├── integration_client.py# Timeout + bounded-retry + contract-checked HTTP
│   └── integration_service.py# Idempotent sync orchestration
├── app.py                   # Streamlit frontend (REST client)
├── ui_common.py             # HTTP helpers for the frontend
├── seed_data.py             # Demo expenses/budgets (idempotent)
├── tests/                   # pytest suite (unit + integration-mocked)
├── .env.example             # Placeholders ONLY (real .env is gitignored)
└── requirements.txt
```

## Integration contract (what A consumes)

- **Person B**: `GET {B}/integration/export` ->
  `{service, contract_version, generated_at, count, subscriptions:[{external_ref, name, category, tags, billing_frequency, amount, monthly_cost, currency, active, next_renewal_date}]}`.
  Each **active, INR** subscription becomes ONE `Subscriptions` expense per
  calendar month (dated the 1st of the sync month), amount = B's
  monthly-normalized cost (yearly 12000 -> 1000.00), identity
  `external_id = B:{external_ref}:{YYYY-MM}`, `import_basis = monthly_normalized`.
  Re-syncing in the same month updates the amount if B's price changed;
  inactive and non-INR subscriptions are skipped and reported.
- **Person C**: `GET {C}/history?months=6` ->
  `{months:[{month, estimated_kwh, actual_kwh, estimated_amount, actual_amount, deviation_percent, needs_investigation}], tariff_name, tariff_verified, estimate_disclaimer}`.
  Every **settled** month in that window becomes ONE `Bills` expense,
  identity `external_id = C:{YYYY-MM}`: the actual bill when C has one
  (`import_basis = actual`), otherwise a closed month's estimate
  (`import_basis = estimated`, merchant suffixed "(estimate)"). The running
  month is never imported. When an actual bill is recorded later, the
  estimate row is **upgraded in place** - estimate and actual are never both
  counted. v1.0 ids (`C:actual:<month>` / `C:estimated:<month>`) are migrated
  to the new identity on first sync.
- **Manual vs imported**: `expenses.source` is `manual` or `integration`;
  `origin` (in every expense response) is `manual`, `subscription_tracker` or
  `smart_home_energy`, and `GET /summary` reports `by_source` totals. If a
  manual expense already covers the same cost in that month (same
  subscription name + amount, or an electricity/TNEB bill), the import is
  skipped as `skipped_manual_duplicate` so the cost is not counted twice.
- **Model**: imported rows are *synchronized records* (upserted by identity),
  not live summaries. Deleting an imported row in A and syncing again
  re-imports it.
- Failure semantics: `not_configured`, `misconfigured`, `unavailable`,
  `timeout`, `unauthorized`, `rate_limited`, `invalid_response` and `empty`
  are distinct statuses; a failing source never blocks the other and never
  returns 500. HTTP 429 from a peer (cloud-host throttling of bursts/cold
  starts) is classified as `rate_limited` and retried within a bounded
  budget (max 2 retries, Retry-After honoured up to a 10 s cap) - never an
  infinite retry.

## Verified demo evidence (2026-11-05)

- Backend test suite: `python -m pytest -q` -> **48 passed** (18 API + 14
  HTTP-client/transport incl. 429 retry/backoff + 14 integration-flow + 2
  migration).
- Live end-to-end run (three real uvicorn processes, real HTTP): Person B
  seeded with 3 subscriptions (1 inactive), Person C seeded with appliances,
  October readings and an actual EB bill. First `POST /integrations/sync`
  imported B: 2 (monthly-normalized; inactive skipped), C: 1 settled month;
  second sync imported 0 (idempotent); a B price change updated the existing
  row in place (imported=0, updated=1); killing B made sync report
  `unavailable` for B while C still imported — no HTTP 500 anywhere.
- Live deployed contract check: a local A instance talking to the deployed
  Render B (`/integration/export`) and Render C (`/history?months=6`) — both
  peers report `available` and the sync completes with 0 imports (empty
  deployed databases).

## Known limitations & unverified items

- Keyword rules are heuristic and English/Tamil-Nadu-merchant oriented; they
  are configurable in `services/categorizer.py`.
- Currency is INR throughout; non-INR subscriptions from B are skipped
  (reported as `skipped_unsupported_currency`), never converted.
- Integration rows are dated the 1st of their month (subscription billing
  dates may differ) and a subscription is imported only for the month in
  which a sync runs - months with no sync get no subscription row.
- The manual-duplicate check is a heuristic (name/amount or electricity
  keywords in the same month); review `details` in the sync result.
- SQLite is single-writer; fine for local demos. Cloud deployments use
  PostgreSQL (see `RENDER_DEPLOYMENT.md`).
- Database schema changes are additive only (`import_basis` column added on
  startup via `ALTER TABLE ... ADD COLUMN`); there is no Alembic history.

## Git workflow (this repository)

```bash
git clone https://github.com/Sachien-N/Smart-Expense-Categorization-Budget-Management.git
cd Smart-Expense-Categorization-Budget-Management
git checkout -b <feature-branch>
# ... changes ...
git add . && git commit -m "..." && git push origin <feature-branch>
```
