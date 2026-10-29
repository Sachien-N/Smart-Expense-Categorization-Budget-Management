# Environment Setup - Person A (Expense & Budget Manager)

Target: Python **3.11 or 3.12** (tested on 3.12). No database server needed -
the app uses its own SQLite file under `data/`.

---

## Windows (PowerShell)

```powershell
# 1. Verify Python
python --version          # expect 3.11+

# 2. Create and activate a virtual environment (inside the project folder)
cd person_a_expense_budget
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# If script execution is blocked:
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 3. Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Configuration
Copy-Item .env.example .env
notepad .env              # adjust ports/URLs if needed (placeholders inside)

# 5. Seed demo data (optional)
python seed_data.py

# 6. Run the backend (keep this terminal open)
uvicorn main:app --host 127.0.0.1 --port 8001 --reload

# 7. Run the frontend in a SECOND terminal (activate venv first)
.\.venv\Scripts\Activate.ps1
$env:API_BASE_URL = "http://127.0.0.1:8001"
streamlit run app.py
```

Open the dashboard at <http://localhost:8501> and the API docs at
<http://127.0.0.1:8001/docs>.

## macOS (zsh)

```zsh
# 1. Verify Python
python3 --version         # expect 3.11+

# 2. Create and activate a virtual environment (inside the project folder)
cd person_a_expense_budget
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
python3 -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Configuration
cp .env.example .env
# edit if needed:  nano .env

# 5. Seed demo data (optional)
python seed_data.py

# 6. Run the backend (keep this terminal open)
uvicorn main:app --host 127.0.0.1 --port 8001 --reload

# 7. Run the frontend in a SECOND terminal (activate venv first)
source .venv/bin/activate
export API_BASE_URL="http://127.0.0.1:8001"
streamlit run app.py
```

## Running all three teammates' apps together (integration demo)

| App | Backend port | Frontend port |
|---|---|---|
| B - Subscription Tracker | 8002 | 8502 |
| C - Smart Home Energy | 8003 | 8503 |
| **A - this app** | 8001 | 8501 |

```bash
# terminal 1 (B)   cd person_b_subscription_tracker && uvicorn main:app --port 8002
# terminal 2 (C)   cd person_c_smart_home_energy   && uvicorn main:app --port 8003
# terminal 3 (A)   cd person_a_expense_budget      && uvicorn main:app --port 8001
```

In A's `.env`, set:

```
INTEGRATION_B_BASE_URL=http://127.0.0.1:8002
INTEGRATION_C_BASE_URL=http://127.0.0.1:8003
```

Then use the **Integrations** page in A's dashboard (or
`curl -X POST http://127.0.0.1:8001/integrations/sync`) and watch subscription
costs and the electricity bill land as categorized expenses - idempotently.

## Tests

```bash
python -m pytest -q          # 23 tests, uses a throwaway SQLite file
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Activate.ps1 cannot be loaded` | PowerShell policy - see step 2 comment. |
| Streamlit shows "Cannot reach API" | Backend not running, or `API_BASE_URL` mismatch. |
| Integrations page shows OFFLINE | B/C not started, or base URLs wrong in `.env`. OFFLINE is normal when teammates' apps aren't running. |
| Port 8001 already in use | Another process holds it: change `--port` and `APP_PORT`, or kill the old process. |
| `database is locked` | Two processes writing the same SQLite file - ensure only the API process uses `data/expense_budget.db`. |
| Sync imports nothing | Expected when B/C are empty; run their `seed_data.py` first. |
