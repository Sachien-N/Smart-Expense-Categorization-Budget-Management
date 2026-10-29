# Implementation Checklist - Person A (Expense & Budget Manager)

Status legend: `[x]` done with evidence - `[!]` done but flagged / unverified -
`[ ]` not done.

## Backend (FastAPI + SQLAlchemy + SQLite)

- [x] Own SQLite database file `data/expense_budget.db` (never shared) - `database.py`
- [x] ORM models: Category / Expense / Budget with unique constraints - `models.py`
- [x] Pydantic v2 request/response contracts - `schemas.py`
- [x] CRUD layer isolated from routers - `crud.py`
- [x] `GET /health` with DB probe - `main.py`
- [x] `POST /expenses` with rule-based auto-categorization - `routers/expenses.py`
- [x] `GET /expenses` with month/category/source filters + paging
- [x] `GET/PUT/DELETE /expenses/{id}` (404 handled)
- [x] `GET /categories` (6 canonical + Uncategorized fallback, idempotent seed)
- [x] `GET /category/{name}` drill-down with totals
- [x] `GET /summary?month=YYYY-MM` (totals, shares, budget comparison; empty month = valid zero)
- [x] `GET /categorize?merchant=...` explainable preview
- [x] `GET/POST /budgets` with live spent/utilization; duplicate -> 409
- [x] 12-factor config via env vars + `.env.example` placeholders only - `config.py`

## Rule-based categorizer

- [x] Six canonical categories + transparent keyword rules - `services/categorizer.py`
- [x] Deterministic priority order (Subscriptions > Entertainment > Food > Travel > Bills > Shopping)
- [x] Fallback bucket `Uncategorized` (no arbitrary miscategorization)
- [x] Keyword + confidence surfaced in API responses

## Integration (HTTP REST only - the course headline)

- [x] Outbound client with explicit timeouts - `services/integration_client.py`
- [x] Bounded retries (2) limited to connection errors / 5xx
- [x] Contract-key validation (`expected_keys`) -> `invalid_response` classification
- [x] Distinguish `unavailable` / `invalid_response` / `empty` / `not_configured`
- [x] `GET /integrations/status` live health probe of B and C
- [x] `POST /integrations/sync` idempotent imports via stable external ids
      (`B:{external_ref}:{month}`, `C:{basis}:{month}`) + UNIQUE index
- [x] Partial-failure isolation: B down doesn't block C; never a 500
- [x] No shared database files - A only calls B's `/integration/export`
      and C's `/history?months=6`

## Frontend (Streamlit)

- [x] Dashboard: KPIs, donut chart, budget progress bars - `app.py`
- [x] Add Expense with categorizer preview + auto/manual category
- [x] All Expenses: filters + delete
- [x] Budgets: table + create form
- [x] Categories: list + drill-down
- [x] Integrations: live status cards + sync button
- [x] UI is a pure REST client (HTTP only), friendly API-down errors - `ui_common.py`

## Quality assurance

- [x] 23 pytest tests pass (unit + integration-mocked) - `tests/`
      (`python -m pytest -q` -> `23 passed`)
- [x] Validation tests: non-positive amount 422, bad month format 422, unknown ids 404, duplicate budget 409
- [x] Categorizer tests: Netflix -> Subscriptions, Swiggy -> Food, fallback -> Uncategorized
- [x] Integration tests: peers-down graceful, invalid-response flagged,
      import + idempotency (second sync imports 0), inactive/malformed rows skipped
- [x] Live smoke test (real uvicorn processes): health x3 OK, status
      `available` with latency, sync imported 9 subs + 1 actual bill, second
      sync all `already_imported` - see `docs/FINAL_VERIFICATION_REPORT.md`
- [x] Streamlit boot check: `/_stcore/health` -> ok

## Documentation & packaging

- [x] `README.md` (features, architecture, contracts, limitations)
- [x] `ENVIRONMENT_SETUP.md` (PowerShell + zsh, three-app run guide, troubleshooting)
- [x] `API_DOCUMENTATION.md` (every endpoint + examples + error semantics)
- [x] `RENDER_DEPLOYMENT.md` (two services, disk caveats, integration wiring)
- [x] `.env.example` placeholders only; `.gitignore` covers `.env`, `data/*.db`, caches
- [x] `seed_data.py` idempotent demo data

## Flagged / unverified

- [!] TNEB/TANGEDCO tariffs (Person C's domain) are seeded UNVERIFIED - see C's docs (A only consumes C's numbers).
- [!] Render free tier: no persistent disk; SQLite resets on deploy (documented in RENDER_DEPLOYMENT.md).
- [ ] Multi-currency support - out of scope, documented in README limitations.
