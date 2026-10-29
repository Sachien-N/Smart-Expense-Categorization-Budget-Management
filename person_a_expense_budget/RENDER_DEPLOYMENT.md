# Render Deployment Guide - Person A (Expense & Budget Manager)

Deploy **two Render services from this one repository**: the FastAPI backend
and the Streamlit dashboard. Cross-app integration (B/C base URLs) is
configured with environment variables after those apps are deployed.

## 0. Prerequisites

- The project pushed to a GitHub repo (e.g. `csi3007-expense-budget-manager`),
  root of the repo = this folder (`main.py` at top level).
- A free Render account. Note Render's free tier caveats at the bottom.

## 1. Service 1 - REST API

1. Render dashboard -> **New +** -> **Web Service** -> connect the repo.
2. Settings:
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**: Free (or any)
3. Environment variables:

   | Key | Value |
   |---|---|
   | `SERVICE_NAME` | `expense-budget-api` |
   | `DATABASE_URL` | `sqlite:////data/expense_budget.db` (see disk below) |
   | `INTEGRATION_B_BASE_URL` | *(set after B is deployed, e.g. `https://csi3007-subscription-tracker.onrender.com`)* |
   | `INTEGRATION_C_BASE_URL` | *(set after C is deployed)* |
   | `INTEGRATION_TIMEOUT_SECONDS` | `5.0` (Render free instances sleep - first calls are slow) |

4. **Persistent disk (important)**: SQLite writes to disk, and Render's
   container filesystem is ephemeral. Add a Disk (Render -> Service ->
   Disks -> Add Disk), e.g. mount path `/data`, size 1 GB. Free-tier
   web services do **not** support disks - on Free, either accept that the
   DB resets on every deploy/restart, or run on a paid instance.
5. Deploy, then verify `https://<api-host>/health` returns
   `{"status": "ok", ...}`.

## 2. Service 2 - Streamlit dashboard

1. **New +** -> **Web Service** -> same repo.
2. Settings:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`
3. Environment variables:

   | Key | Value |
   |---|---|
   | `API_BASE_URL` | `https://<api-host-from-step-1>` |
   | `INTEGRATION_B_BASE_URL` | same as on the API service |
   | `INTEGRATION_C_BASE_URL` | same as on the API service |

4. Deploy and open the dashboard. The **Integrations** page should show both
   peers with live status, and **Run sync now** pulls B/C data over HTTPS.

> The dashboard is a pure REST client - it talks to the API service over
> HTTP; it never imports backend code at runtime and never opens the DB file.

## 3. Cross-app wiring (the CSI3007 integration story)

Deploy order matters only for convenience:

1. Deploy B (`csi3007-subscription-cost-tracker`) and C
   (`csi3007-smart-home-energy-monitor`) first - each is one API service
   (+ optional UI service) using the same recipe with their own
   `RENDER_DEPLOYMENT.md`.
2. Copy their `https://...onrender.com` URLs into **this app's** env vars
   (`INTEGRATION_B_BASE_URL`, `INTEGRATION_C_BASE_URL`) on BOTH services of A.
3. `Manual Deploy -> Clear build cache & deploy` on A's services, then run
   `POST /integrations/sync` once - imports carry stable external ids, so
   re-deploys and re-syncs never duplicate.

## 4. Verification checklist

- [x] `GET /health` -> `status: ok`, `database: connected`
- [x] `GET /docs` loads (OpenAPI UI)
- [x] Create + list an expense via `/docs`
- [x] `GET /integrations/status` shows peers `available` (or `not_configured` if not yet wired)
- [x] `POST /integrations/sync` returns per-source results; run twice, second is all `already_imported`
- [x] Streamlit dashboard loads and shows the same data

## 5. Free-tier caveats (stated honestly)

- Free web services **sleep** after ~15 min idle; the first request wakes
  them (~30-60 s). Sync calls between sleeping services may hit the timeout -
  increase `INTEGRATION_TIMEOUT_SECONDS`, retry, or upgrade.
- Free tier does not support persistent disks -> the SQLite DB is ephemeral.
  For durable data use a paid instance + disk, or point `DATABASE_URL` at a
  managed Postgres (would require a small SQLAlchemy URL change - SQLite-only
  conveniences like `strftime` filters are used in queries).
- `allow_origins=["*"]` CORS is deliberate for the course demo; lock it down
  for any real deployment.
