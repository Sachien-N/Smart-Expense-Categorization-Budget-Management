"""Person A - Streamlit frontend for the Smart Expense & Budget API.

The UI is a standalone REST client: set API_BASE_URL to the backend URL
(default http://127.0.0.1:8001). Run:  streamlit run app.py
"""
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from ui_common import resolve_api_base_url, configure, api_delete, api_get, api_post, money

st.set_page_config(page_title="Expense & Budget Manager (A)", layout="wide")


# Load API_URL and API_SECRET from Streamlit Secrets (never hard-code credentials here).
configure(st.secrets)
API_BASE_URL = resolve_api_base_url(st.secrets)

ORIGIN_LABELS = {
    "manual": "Manual expenses",
    "subscription_tracker": "Subscriptions (from B)",
    "smart_home_energy": "Electricity (from C)",
    "integration": "Other imports",
}
STATUS_TEXT = {
    "available": "ONLINE", "ok": "OK", "empty": "NOTHING TO IMPORT", "unavailable": "OFFLINE",
    "timeout": "TIMED OUT", "unauthorized": "UNAUTHORIZED", "invalid_response": "BAD RESPONSE",
    "not_configured": "NOT CONFIGURED", "misconfigured": "BAD URL",
}
CATEGORY_COLORS = {
    "Food": "#f97316",
    "Travel": "#0ea5e9",
    "Bills": "#eab308",
    "Entertainment": "#a855f7",
    "Shopping": "#ec4899",
    "Subscriptions": "#10b981",
    "Uncategorized": "#94a3b8",
}

st.title("Smart Expense Categorization & Budget Management")
st.caption("Person A - Sachien N (23MID0255) | CSI3007 Advanced Python Programming")
st.caption("Backend: Google Apps Script + Google Sheets (configured through Streamlit Secrets)")

page = st.sidebar.radio(
    "Navigate",
    ["Dashboard", "Add Expense", "All Expenses", "Budgets", "Categories", "Integrations"],
)


def current_month() -> str:
    return date.today().strftime("%Y-%m")


def month_input(label: str, default: str | None = None) -> str:
    value = st.text_input(label, value=default or current_month(), max_chars=7)
    return value.strip()


# ------------------------------------------------------------------ Dashboard
if page == "Dashboard":
    st.subheader("Monthly dashboard")
    month = month_input("Month (YYYY-MM)")
    ok, data = api_get(API_BASE_URL, "/summary", params={"month": month})
    if not ok:
        st.error(data)
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Total spent", money(data["total_expenses"]))
        col2.metric("Transactions", data["transaction_count"])
        over = [b for b in data["budget_comparison"] if b["over_budget"]]
        col3.metric("Budgets exceeded", len(over))

        sources = {row["origin"]: row for row in data.get("by_source", [])}
        if sources:
            s1, s2, s3 = st.columns(3)
            for col, key in zip((s1, s2, s3), ("manual", "subscription_tracker", "smart_home_energy")):
                row = sources.get(key, {"total": 0.0, "count": 0})
                col.metric(ORIGIN_LABELS[key], money(row["total"]), f"{row['count']} rows", delta_color="off")
            st.caption("Imported rows come from the Integrations page sync. Each subscription is counted once "
                       "per month and each electricity month once (an estimate is replaced by the actual bill), "
                       "so refreshing this page or re-running the sync never double counts.")

        if data["by_category"]:
            df = pd.DataFrame(data["by_category"])
            fig = px.pie(
                df, names="category", values="total",
                title=f"Spend split - {month}", hole=0.4,
                color="category", color_discrete_map=CATEGORY_COLORS,
            )
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(
                df.rename(columns={"total": "Total (INR)", "share_percent": "Share %"}),
                use_container_width=True, hide_index=True,
            )
