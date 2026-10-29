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
  (`B:B-SUB-4:2026-10`, `C:actual:2026-09`) with a UNIQUE constraint, so
  re-running a sync **never duplicates**. Outbound calls use explicit
  timeouts, bounded retries, contract-key validation, and a peer outage is
  reported per-source - it never breaks A or the other source.
- **Streamlit dashboard**: KPIs, donut chart of spend split, budget progress
  bars, expense CRUD, budget setup, category drill-down, live integration
  status cards + one-click sync.

## Tech stack

| Layer     | Technology |
|-----------|------------|
| Backend   | Python 3.12, FastAPI, Pydantic v2 |
| Database  | SQLite via SQLAlchemy 2 (own file: `data/expense_budget.db`) |
| Frontend  | Streamlit + Plotly (pure REST client - never touches the DB) |
| Testing   | pytest + FastAPI TestClient (23 tests) |
| Deploy    | Render (see `RENDER_DEPLOYMENT.md`) |

## Quickstart

```bash
# 1. environment
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. configuration (placeholders only - edit as needed)
cp .env.example .env

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
| `DATABASE_URL` | `sqlite:///./data/expense_budget.db` | Own SQLite file (never shared) |
| `APP_PORT` | `8001` | Backend port |
| `API_BASE_URL` (frontend) | `http://127.0.0.1:8001` | Where Streamlit finds the API |
| `INTEGRATION_B_BASE_URL` | - | Person B base URL (blank = integration off) |
| `INTEGRATION_C_BASE_URL` | - | Person C base URL (blank = integration off) |
| `INTEGRATION_TIMEOUT_SECONDS` | `3.0` | Outbound connect+read timeout |
| `INTEGRATION_MAX_RETRIES` | `2` | Bounded retries (connection errors / 5xx only) |
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
  A imports each **active** subscription as a monthly `Subscriptions` expense
  (dated the 1st of the sync month) with `external_id = B:{external_ref}:{month}`.
- **Person C**: `GET {C}/history?months=6` ->
  `{months:[{month, estimated_kwh, actual_kwh, estimated_amount, actual_amount, deviation_percent, needs_investigation}]}`.
  A imports the most recent month that has an **actual** bill; if none, the most
  recent **completed** month's estimate, with `external_id = C:{basis}:{month}`.
- Failure semantics: unavailable / invalid-response / empty are distinct
  statuses in the sync result; a partial failure never blocks the other source
  and never returns HTTP 500.

## Known limitations & unverified items

- Keyword rules are heuristic and English/Tamil-Nadu-merchant oriented; they
  are configurable in `services/categorizer.py`.
- Currency is assumed INR throughout; no FX handling.
- Integration rows are re-dated to the 1st of the sync month (subscription
  billing dates may differ) - documented behaviour, kept simple on purpose.
- SQLite is single-writer; fine for a course-scale demo, not for concurrency.

## Git quickstart (GitHub-ready)

```bash
git init
git add .
git commit -m "CSI3007 Person A: expense & budget manager"
git branch -M main
git remote add origin https://github.com/<your-user>/csi3007-expense-budget-manager.git
git push -u origin main
```
