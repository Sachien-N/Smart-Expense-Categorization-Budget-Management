# Cloud Deployment - Person A - Expense & Budget Manager

Backend (FastAPI) -> **Render** web service + **Render PostgreSQL**, defined in
[`render.yaml`](render.yaml).
Frontend (Streamlit) -> **Streamlit Community Cloud**, talking to the Render
backend over HTTPS.

Status of this guide: the Blueprint was validated with
`render blueprints validate` (result `valid: true`) and the backend was run
locally against PostgreSQL 15 with the full test suite and the live
end-to-end scenarios.

**Live deployment status (verified 2026-11-05):** the backend is deployed at
https://smart-expense-categorization-budget.onrender.com and `/health`
returns `status: ok`. Two environment gaps need fixing in the Render
Dashboard (no code change required):

1. `DATABASE_URL` — `/health` currently reports `database_backend: sqlite`,
   so the free-tier ephemeral filesystem is in use and data is wiped on every
   redeploy. Create/provision the PostgreSQL instance from the Blueprint (or
   manually) and set `DATABASE_URL`, then redeploy.
2. `SUBSCRIPTION_API_URL` / `ELECTRICITY_API_URL` — `GET /integrations/status`
   currently reports both peers as `not_configured`. Set them to
   `https://subscription-tracker-api-ihiq.onrender.com` and
   `https://smart-home-energy-api.onrender.com`.

## 1. Why PostgreSQL and not the SQLite file

Render's free web services have an **ephemeral filesystem** and cannot attach
a persistent disk, so a SQLite file there is wiped on every deploy, restart
and spin-down. The Blueprint therefore provisions a Render PostgreSQL
database and injects its connection string as `DATABASE_URL`
(`postgres://...` is normalized to the psycopg driver automatically).

- Free Render Postgres **expires 30 days after creation**, and one workspace
  can own only one free database. Upgrade the plan or recreate the database
  before it expires.
- Paid alternative: an instance with a disk mounted at `/var/data` and
  `DATABASE_URL=sqlite:////var/data/<name>.db` (remove the `databases:` block).
- Tables are created on startup; there is no destructive reset. The only
  schema change in v1.1 is additive (A's `expenses.import_basis`).

## 2. Deploy the backend (Render Blueprint)

1. Push this project to its GitHub repository (it lives in the
   `person_a_expense_budget/` folder of the repo).
2. Render dashboard -> **New** -> **Blueprint** -> connect the repository.
3. **Blueprint Path**: `person_a_expense_budget/render.yaml`.
4. Review the plan (one web service `expense-budget-api`, one database `expense-budget-db`)
   and fill any prompted values. Apply.

What the Blueprint configures:

| Setting | Value |
|---|---|
| Root directory | `person_a_expense_budget` |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Health check | `/health` |
| Python | `PYTHON_VERSION=3.12.8` |

Environment variables:

| Key | Value | Source |
|---|---|---|
| `DATABASE_URL` | connection string of `expense-budget-db` | from database |
| `SERVICE_NAME` | `expense-budget-api` | in Blueprint |
| `SUBSCRIPTION_API_URL` | B's Render URL, e.g. `https://subscription-cost-tracker.onrender.com` | prompted (`sync: false`) |
| `ELECTRICITY_API_URL` | C's Render URL, e.g. `https://smart-home-energy-monitor.onrender.com` | prompted (`sync: false`) |
| `INTEGRATION_CONNECT_TIMEOUT_SECONDS` | `10` | in Blueprint |
| `INTEGRATION_TIMEOUT_SECONDS` | `60` (a sleeping free peer needs ~50 s to wake) | in Blueprint |
| `INTEGRATION_MAX_RETRIES` | `1` | in Blueprint |

No secrets are committed: the database credentials exist only in Render.

### Verify the backend

```bash
curl https://<your-service>.onrender.com/health
```
- `status: ok`, `database: connected`, `database_backend: postgresql`.
- `https://<your-service>.onrender.com/docs` and `/openapi.json` load.
- `GET /integrations/status` -> both peers `available` (a sleeping peer may
  first report `timeout`; retry after a minute).
- `POST /integrations/sync` twice -> second run: `imported: 0`, `updated: 0`;
  `GET /summary` totals unchanged.
- Create a record through `/docs`, trigger **Manual Deploy -> Restart service**,
  and confirm the record is still there (PostgreSQL persistence).

## 3. Deploy the frontend (Streamlit Community Cloud)

The Streamlit app stores expenses/budgets in **Google Apps Script + Google
Sheets** and (optionally) talks to the Render backend for live integration
status/sync.

1. <https://share.streamlit.io> -> **Create app** -> pick the repository and branch.
2. **Main file path**: `person_a_expense_budget/app.py`
   (Community Cloud installs `person_a_expense_budget/requirements.txt`).
3. **Advanced settings** -> Python 3.12 -> **Secrets**:
   ```toml
   API_URL = "https://script.google.com/macros/s/<DEPLOYMENT_ID>/exec"
   API_SECRET = "<the same secret stored in Apps Script Script Properties>"
   BACKEND_API_URL = "https://smart-expense-categorization-budget.onrender.com"
   ```
   (template: `.streamlit/secrets.toml.example`). `API_SECRET` must equal the
   value stored in the Apps Script project's **Script Properties** (key
   `API_SECRET`) — see the rotation checklist below. Without `API_URL`/`API_SECRET`
   the app falls back to `API_BASE_URL` (local backend mode), which is only
   useful when running everything locally.
4. Deploy and open every sidebar page. The caption under the title shows the
   storage mode. If the backend was asleep, the Integrations page can take up
   to a couple of minutes on its first sync — retry once.

The UI never touches the backend database directly: records go through the
Apps Script API, and integration status/sync/mirroring go through
`BACKEND_API_URL` when configured.

## 4. API secret handling and rotation (IMPORTANT)

The `API_SECRET` shared between the Streamlit app and the Apps Script Web App
was accidentally exposed in a chat in 2026-11. Treat it as compromised:

1. Generate a new secret, e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Apps Script: open the project -> **Project Settings -> Script Properties**
   -> update the `API_SECRET` property to the new value -> save.
   (No redeploy of the web app is needed for Script Property changes.)
3. Streamlit Community Cloud: **App settings -> Secrets** -> update `API_SECRET`.
4. Any local `.env` / `secrets.toml`: update and keep them gitignored.
5. Never paste the secret into chat, issues, README, screenshots or code.
   It is read at runtime from the environment / Script Properties only
   (`ui_common.configure()`), so no code change is needed when rotating.
6. Git-history check: all three project repositories were scanned (full
   history) on 2026-11-05 — no real secret was ever committed; only
   placeholders exist. No history rewrite is required, but keep it that way.

## 5. Free-tier caveats

- Free Render services sleep after ~15 minutes idle; the first request takes
  ~30-60 s.
- `allow_origins=["*"]` CORS is intentional for the course demo (the
  frontends call the APIs server-side). Restrict it for real use.
- Unhandled errors return `{"detail": "Internal server error"}`; tracebacks
  go to the Render logs only.
- **HTTP 429 on free instances**: Render's edge can throttle bursts of
  requests to a waking free instance with `429 Too Many Requests`. This is
  infrastructure-level - no rate limiter exists in this codebase. Person A's
  integration client classifies it as `rate_limited`, honours `Retry-After`
  (capped at 10 s) and retries within a bounded budget (max 2), so a sync
  recovers automatically. Before a demo, warm every service once:

  ```bash
  curl -s https://subscription-tracker-api-ihiq.onrender.com/health
  curl -s https://smart-home-energy-api.onrender.com/health
  curl -s https://smart-expense-categorization-budget.onrender.com/health
  ```

  then open Person A's Integrations page and press **Check status** before
  **Sync now** - this wakes the peers without racing the sync.
