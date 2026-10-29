# Cloud Deployment - Person A - Expense & Budget Manager

Backend (FastAPI) -> **Render** web service + **Render PostgreSQL**, defined in
[`render.yaml`](render.yaml).
Frontend (Streamlit) -> **Streamlit Community Cloud**, talking to the Render
backend over HTTPS.

Status of this guide: the Blueprint was validated with
`render blueprints validate` (result `valid: true`) and the backend was run
locally against PostgreSQL 15 with the full test suite and the live
end-to-end scenarios. Nothing has been deployed by the maintainers of this
document - URLs below are placeholders until you deploy.

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

1. <https://share.streamlit.io> -> **Create app** -> pick the repository and branch.
2. **Main file path**: `person_a_expense_budget/app.py`
   (Community Cloud installs `person_a_expense_budget/requirements.txt`).
3. **Advanced settings** -> Python 3.12 -> **Secrets**:
   ```toml
   API_BASE_URL = "https://<your-service>.onrender.com"
   ```
   (template: `.streamlit/secrets.toml.example`). Optional:
   `API_TIMEOUT_SECONDS = "60"` as an environment-style secret is not read -
   the 60 s default already covers Render cold starts.
4. Deploy and open every sidebar page. The caption under the title shows the
   API URL in use. If the backend was asleep, the first page can take up to a
   minute or show a "may be waking up" message - reload once.

The frontend never touches a database; it only calls `API_BASE_URL`.

## 4. Free-tier caveats

- Free Render services sleep after ~15 minutes idle; the first request takes
  ~30-60 s.
- `allow_origins=["*"]` CORS is intentional for the course demo (the
  frontends call the APIs server-side). Restrict it for real use.
- Unhandled errors return `{"detail": "Internal server error"}`; tracebacks
  go to the Render logs only.
