"""Person A - Streamlit frontend for the Smart Expense & Budget API.

The UI is a standalone REST client: set API_BASE_URL to the backend URL
(default http://127.0.0.1:8001). Run:  streamlit run app.py
"""
import os
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from ui_common import api_delete, api_get, api_post, money

st.set_page_config(page_title="Expense & Budget Manager (A)", layout="wide")


def _api_base_url(default: str) -> str:
    """Resolve the backend URL: env var first (local runs / Render), then
    Streamlit Community Cloud secrets (the Secrets editor is surfaced through
    st.secrets), then the local default."""
    value = os.getenv("API_BASE_URL")
    if value:
        return value
    try:
        return st.secrets.get("API_BASE_URL", default)
    except Exception:  # no secrets file in a plain local run
        return default


API_BASE_URL = _api_base_url("http://127.0.0.1:8001")

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
st.caption("Person A - Sachien N (23MID0255) | CSI3007 Advanced Python Programming | "
           f"API: `{API_BASE_URL}`")

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
        else:
            st.info(f"No expenses recorded for {month} yet (valid zero month).")

        if data["budget_comparison"]:
            st.subheader("Budget vs actual")
            for row in data["budget_comparison"]:
                # st.progress only accepts values in [0.0, 1.0]. Cap the BAR at
                # 100%; the true percentage (even when over budget, e.g. 141.5%)
                # stays visible in the label and the OVER BUDGET tag below.
                util = min(row["utilization_percent"], 100) / 100
                label = (f"**{row['category']}** - {money(row['spent'])} of {money(row['budget'])} "
                         f"({row['utilization_percent']}%)")
                if row["over_budget"]:
                    st.error(label + " - OVER BUDGET")
                else:
                    st.write(label)
                st.progress(util)

# ---------------------------------------------------------------- Add Expense
elif page == "Add Expense":
    st.subheader("Add an expense")
    with st.form("add_expense", clear_on_submit=True):
        merchant = st.text_input("Merchant *", placeholder="e.g. Swiggy, Uber, Netflix")
        amount = st.number_input("Amount (INR) *", min_value=0.01, value=100.0, step=10.0)
        expense_date = st.date_input("Date", value=date.today())
        ok, categories = api_get(API_BASE_URL, "/categories")
        choices = ["Auto (rule-based categorizer)"] + [c["name"] for c in categories] if ok else ["Auto (rule-based categorizer)"]
        category_choice = st.selectbox("Category", choices)
        description = st.text_input("Description (optional)")
        submitted = st.form_submit_button("Save expense")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Preview suggested category") and merchant:
            ok, suggestion = api_get(API_BASE_URL, "/categorize", params={"merchant": merchant})
            if ok:
                st.info(f"**{suggestion['suggested_category']}** ({suggestion['confidence']}) - {suggestion['reason']}")
            else:
                st.error(suggestion)
    with col_b:
        if submitted:
            if not merchant:
                st.error("Merchant is required.")
            else:
                body = {
                    "merchant": merchant,
                    "amount": amount,
                    "expense_date": expense_date.isoformat(),
                    "description": description,
                }
                if category_choice != "Auto (rule-based categorizer)":
                    body["category"] = category_choice
                ok, result = api_post(API_BASE_URL, "/expenses", body)
                if ok:
                    st.success(f"Saved expense #{result['id']} in category **{result['category']}** "
                               f"(source: {result['source']})")
                    st.json(result)
                else:
                    st.error(result)

# --------------------------------------------------------------- All Expenses
elif page == "All Expenses":
    st.subheader("All expenses")
    col1, col2, col3, col4 = st.columns(4)
    month = col1.text_input("Month filter (YYYY-MM, blank = all)")
    ok, categories = api_get(API_BASE_URL, "/categories")
    cat_names = [""] + ([c["name"] for c in categories] if ok else [])
    category = col2.selectbox("Category filter", cat_names)
    source = col3.selectbox("Source", ["", "manual", "integration"])
    limit = col4.number_input("Max rows", 10, 200, 100, step=10)

    params = {"limit": limit}
    if month:
        params["month"] = month
    if category:
        params["category"] = category
    if source:
        params["source"] = source
    ok, expenses = api_get(API_BASE_URL, "/expenses", params=params)
    if not ok:
        st.error(expenses)
    elif not expenses:
        st.info("No expenses match these filters.")
    else:
        df = pd.DataFrame(expenses)[["id", "expense_date", "merchant", "category", "amount", "source"]]
        st.dataframe(df, use_container_width=True, hide_index=True)

        expense_id = st.number_input("Expense ID to delete", min_value=1, step=1)
        if st.button("Delete selected expense"):
            ok, result = api_delete(API_BASE_URL, f"/expenses/{int(expense_id)}")
            if ok:
                st.success(f"Deleted expense #{expense_id}")
                st.rerun()
            else:
                st.error(result)

# -------------------------------------------------------------------- Budgets
elif page == "Budgets":
    st.subheader("Monthly budgets")
    month = month_input("Month (YYYY-MM)")
    ok, budgets = api_get(API_BASE_URL, "/budgets", params={"month": month} if month else None)
    if not ok:
        st.error(budgets)
    elif budgets:
        st.dataframe(pd.DataFrame(budgets), use_container_width=True, hide_index=True)
    else:
        st.info(f"No budgets set for {month}.")

    st.markdown("#### Set a new budget")
    with st.form("set_budget"):
        ok, categories = api_get(API_BASE_URL, "/categories")
        cat_names = [c["name"] for c in categories] if ok else []
        budget_month = st.text_input("Month *", value=current_month(), max_chars=7)
        category = st.selectbox("Category *", cat_names)
        amount_limit = st.number_input("Monthly limit (INR) *", min_value=1.0, value=2000.0, step=100.0)
        if st.form_submit_button("Save budget"):
            ok, result = api_post(
                API_BASE_URL, "/budgets",
                {"category": category, "month": budget_month, "amount_limit": amount_limit},
            )
            if ok:
                st.success(f"Budget saved for {category} ({budget_month})")
                st.rerun()
            else:
                st.error(result)

# ----------------------------------------------------------------- Categories
elif page == "Categories":
    st.subheader("Categories")
    ok, categories = api_get(API_BASE_URL, "/categories")
    if not ok:
        st.error(categories)
    else:
        cat_names = [c["name"] for c in categories]
        st.dataframe(pd.DataFrame(categories), use_container_width=True, hide_index=True)
        chosen = st.selectbox("Drill down into a category", cat_names)
        if st.button("Show category detail"):
            ok, detail = api_get(API_BASE_URL, f"/category/{chosen}")
            if ok:
                st.metric(f"Total in {detail['category']}", money(detail["total_amount"]))
                st.metric("Transactions", detail["expense_count"])
                if detail["expenses"]:
                    st.dataframe(pd.DataFrame(detail["expenses"]), use_container_width=True, hide_index=True)
            else:
                st.error(detail)

# --------------------------------------------------------------- Integrations
elif page == "Integrations":
    st.subheader("Cross-app integrations (HTTP REST only)")
    st.caption("A pulls from Person B (subscriptions) and Person C (electricity bills). "
               "No shared databases - only documented REST contracts.")

    ok, status = api_get(API_BASE_URL, "/integrations/status")
    if not ok:
        st.error(status)
    else:
        cols = st.columns(len(status["services"]))
        for col, svc in zip(cols, status["services"]):
            badge = {"available": "ONLINE", "unavailable": "OFFLINE",
                     "invalid_response": "BAD RESPONSE", "not_configured": "NOT CONFIGURED"}
            col.metric(svc["service_key"], badge.get(svc["status"], svc["status"].upper()))
            col.caption(f"{svc.get('peer_service_name') or '-'} | {svc.get('latency_ms') or '-'} ms")

    if st.button("Run sync now (idempotent)"):
        with st.spinner("Syncing from B and C over HTTP..."):
            ok, result = api_post(API_BASE_URL, "/integrations/sync", {})
        if ok:
            st.success(f"Sync finished - overall: **{result['overall']}**")
            st.json(result)
        else:
            st.error(result)
