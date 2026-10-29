
"""Person A — Smart Expense Categorization & Budget Management.
Streamlit frontend backed by Google Apps Script + Google Sheets.
"""

from datetime import date
from urllib.parse import quote

import pandas as pd
import plotly.express as px
import streamlit as st

from ui_common import (
    resolve_api_base_url,
    configure,
    api_delete,
    api_get,
    api_post,
    money,
)

st.set_page_config(
    page_title="Expense & Budget Manager",
    page_icon="💰",
    layout="wide",
)

# Configure the Google Apps Script adapter.
configure(st.secrets)
API_BASE_URL = resolve_api_base_url(st.secrets)

CATEGORIES_DEFAULT = [
    "Food",
    "Travel",
    "Bills",
    "Entertainment",
    "Shopping",
    "Subscriptions",
    "Uncategorized",
]

CATEGORY_COLORS = {
    "Food": "#f97316",
    "Travel": "#0ea5e9",
    "Bills": "#eab308",
    "Entertainment": "#a855f7",
    "Shopping": "#ec4899",
    "Subscriptions": "#10b981",
    "Uncategorized": "#94a3b8",
}

ORIGIN_LABELS = {
    "manual": "Manual",
    "subscription_tracker": "Subscriptions (Person B)",
    "smart_home_energy": "Electricity (Person C)",
    "integration": "Imported",
}


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def as_list(value):
    """Normalize a list or common API response dictionary into a list."""
    if isinstance(value, list):
        return value

    if isinstance(value, dict):
        for key in ("items", "records", "expenses", "budgets", "categories", "data"):
            if isinstance(value.get(key), list):
                return value[key]

    return []


def as_dict(value):
    """Return a dictionary even when the API response is unexpected."""
    return value if isinstance(value, dict) else {}


def show_api_error(message):
    st.error(str(message or "The API returned an unknown error."))
    st.info(
        "Check the Streamlit app's Secrets and the Google Apps Script "
        "deployment. See the Streamlit logs for the full error."
    )


def get_categories():
    """Load categories; use built-in defaults if the endpoint fails."""
    ok, result = api_get(API_BASE_URL, "/categories")

    if ok:
        rows = as_list(result)
        names = [
            str(row.get("name", "")).strip()
            for row in rows
            if isinstance(row, dict) and row.get("name")
        ]
        if names:
            return names

    return CATEGORIES_DEFAULT.copy()


def get_expenses(month=None, category=None, source=None):
    params = {}

    if month:
        params["month"] = month
    if category and category != "All":
        params["category"] = category
    if source and source != "All":
        params["source"] = source

    ok, result = api_get(API_BASE_URL, "/expenses", params=params)

    if not ok:
        return False, result

    rows = as_list(result)
    rows = [
        row for row in rows
        if isinstance(row, dict) and not row.get("_deleted", False)
    ]

    return True, rows


def display_table(rows):
    if not rows:
        st.info("No records found for the selected filters.")
        return

    df = pd.DataFrame(rows)

    preferred = [
        "id", "date", "merchant", "description", "category",
        "amount", "origin", "source",
    ]
    columns = [column for column in preferred if column in df.columns]
    columns += [column for column in df.columns if column not in columns]

    st.dataframe(
        df[columns],
        use_container_width=True,
        hide_index=True,
    )


def validate_month(value):
    try:
        parsed = date.fromisoformat(value + "-01")
        return parsed.strftime("%Y-%m") == value
    except (TypeError, ValueError):
        return False


def get_month_expenses(month):
    ok, result = get_expenses(month=month)
    if not ok:
        return False, result
    return True, result


# ---------------------------------------------------------------------
# Page header and navigation
# ---------------------------------------------------------------------

st.title("💰 Smart Expense Categorization & Budget Management")
st.caption(
    "Person A — Sachien N (23MID0255) | CSI3007 Advanced Python Programming"
)
st.caption("Storage: Google Apps Script + Google Sheets")

page = st.sidebar.radio(
    "Navigate",
    [
        "Dashboard",
        "Add Expense",
        "All Expenses",
        "Budgets",
        "Categories",
        "Integrations",
    ],
)

st.sidebar.divider()
st.sidebar.caption("API connection")

if API_BASE_URL.startswith("https://"):
    st.sidebar.success("HTTPS endpoint configured")
else:
    st.sidebar.warning("Check API_URL in Streamlit Secrets")


# ---------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------

if page == "Dashboard":
    st.subheader("Monthly dashboard")

    month = st.text_input(
        "Month (YYYY-MM)",
        value=date.today().strftime("%Y-%m"),
        max_chars=7,
        key="dashboard_month",
    ).strip()

    if not validate_month(month):
        st.warning("Enter a valid month in YYYY-MM format, for example 2026-10.")
        st.stop()

    ok, result = api_get(
        API_BASE_URL,
        "/summary",
        params={"month": month},
    )

    if not ok:
        show_api_error(result)
    else:
        data = as_dict(result)

        total = data.get("total_expenses", 0)
        count = data.get("transaction_count", 0)
        comparisons = data.get("budget_comparison", [])
        comparisons = comparisons if isinstance(comparisons, list) else []

        exceeded = [
            item for item in comparisons
            if isinstance(item, dict) and item.get("over_budget")
        ]

        col1, col2, col3 = st.columns(3)
        col1.metric("Total spent", money(total))
        col2.metric("Transactions", count)
        col3.metric("Budgets exceeded", len(exceeded))

        st.divider()
        st.subheader("Spending by category")

        category_rows = data.get("by_category", [])
        if isinstance(category_rows, list) and category_rows:
            df = pd.DataFrame(category_rows)

            if {"category", "total"}.issubset(df.columns):
                fig = px.pie(
                    df,
                    names="category",
                    values="total",
                    title=f"Spending breakdown — {month}",
                    hole=0.4,
                    color="category",
                    color_discrete_map=CATEGORY_COLORS,
                )
                st.plotly_chart(fig, use_container_width=True)

                table = df.rename(
                    columns={
                        "total": "Total (INR)",
                        "share_percent": "Share (%)",
                    }
                )
                st.dataframe(table, use_container_width=True, hide_index=True)
            else:
                st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No expenses recorded for this month yet.")

        if comparisons:
            st.subheader("Budget comparison")
            st.dataframe(
                pd.DataFrame(comparisons),
                use_container_width=True,
                hide_index=True,
            )


# ---------------------------------------------------------------------
# Add Expense
# ---------------------------------------------------------------------

elif page == "Add Expense":
    st.subheader("➕ Add a new expense")
    st.write("Enter the transaction details below.")

    categories = get_categories()

    with st.form("add_expense_form", clear_on_submit=False):
        merchant = st.text_input(
            "Merchant / Payee *",
            placeholder="e.g. Swiggy, Uber, Electricity Board",
        )

        col1, col2 = st.columns(2)

        with col1:
            amount = st.number_input(
                "Amount (INR) *",
                min_value=0.01,
                value=100.0,
                step=10.0,
                format="%.2f",
            )
            expense_date = st.date_input("Expense date", value=date.today())

        with col2:
            category = st.selectbox("Category", categories)
            origin = st.selectbox(
                "Source",
                options=["manual", "integration"],
                format_func=lambda value: ORIGIN_LABELS.get(value, value),
            )

        description = st.text_area(
            "Description (optional)",
            placeholder="Add a note about this expense",
        )

        submitted = st.form_submit_button(
            "Save expense",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        if not merchant.strip():
            st.error("Please enter a merchant or payee.")
        elif amount <= 0:
            st.error("The amount must be greater than zero.")
        else:
            payload = {
                "merchant": merchant.strip(),
                "amount": round(float(amount), 2),
                "date": expense_date.isoformat(),
                "category": category,
                "description": description.strip(),
                "origin": origin,
            }

            with st.spinner("Saving expense..."):
                ok, result = api_post(
                    API_BASE_URL,
                    "/expenses",
                    payload,
                )

            if ok:
                st.success("Expense saved successfully!")
                st.json(result if isinstance(result, dict) else {"result": result})
            else:
                show_api_error(result)

    st.divider()
    st.subheader("Category suggestion")

    suggestion_merchant = st.text_input(
        "Enter a merchant to suggest a category",
        placeholder="e.g. Netflix",
        key="suggestion_merchant",
    )

    if st.button("Suggest category"):
        if not suggestion_merchant.strip():
            st.warning("Enter a merchant name first.")
        else:
            ok, result = api_get(
                API_BASE_URL,
                "/categorize",
                params={"merchant": suggestion_merchant.strip()},
            )

            if ok:
                st.success("Category suggestion")
                st.json(result)
            else:
                # A local fallback keeps the suggestion feature useful.
                name = suggestion_merchant.lower()
                rules = {
                    "Food": ["swiggy", "zomato", "restaurant", "cafe", "pizza"],
                    "Travel": ["uber", "ola", "rapido", "petrol", "irctc"],
                    "Bills": ["electricity", "tneb", "recharge", "broadband", "rent"],
                    "Subscriptions": ["netflix", "spotify", "prime", "hotstar"],
                    "Shopping": ["amazon", "flipkart", "myntra"],
                    "Entertainment": ["bookmyshow", "cinema", "movie", "steam"],
                }

                guessed = "Uncategorized"
                for label, keywords in rules.items():
                    if any(word in name for word in keywords):
                        guessed = label
                        break

                st.info(f"Local suggestion: **{guessed}**")
                st.caption(
                    "The remote categorization endpoint was unavailable; "
                    "this suggestion was generated locally."
                )


# ---------------------------------------------------------------------
# All Expenses
# ---------------------------------------------------------------------

elif page == "All Expenses":
    st.subheader("📋 All expenses")

    col1, col2, col3 = st.columns(3)

    with col1:
        month_filter = st.text_input(
            "Month filter (YYYY-MM, optional)",
            value="",
            max_chars=7,
            key="expenses_month",
        ).strip()

    with col2:
        category_options = ["All"] + get_categories()
        category_filter = st.selectbox(
            "Category",
            category_options,
            key="expenses_category",
        )

    with col3:
        source_filter = st.selectbox(
            "Source",
            ["All", "manual", "subscription_tracker", "smart_home_energy", "integration"],
            format_func=lambda value: (
                "All sources" if value == "All"
                else ORIGIN_LABELS.get(value, value)
            ),
            key="expenses_source",
        )

    if month_filter and not validate_month(month_filter):
        st.warning("Enter the month as YYYY-MM or leave it empty.")
        st.stop()

    ok, rows = get_expenses(
        month=month_filter or None,
        category=category_filter,
        source=source_filter,
    )

    if not ok:
        show_api_error(rows)
    else:
        st.metric("Matching expenses", len(rows))

        if rows:
            total = sum(
                float(row.get("amount", 0) or 0)
                for row in rows
            )
            st.metric("Total in this view", money(total))

        display_table(rows)

        st.divider()
        st.subheader("Delete an expense")

        if rows:
            ids = [
                str(row.get("id"))
                for row in rows
                if row.get("id") is not None
            ]

            if ids:
                selected_id = st.selectbox(
                    "Select expense ID",
                    ids,
                    key="delete_expense_id",
                )

                confirm = st.checkbox(
                    "I confirm that I want to delete this expense.",
                    key="confirm_delete_expense",
                )

                if st.button("Delete selected expense", type="primary"):
                    if not confirm:
                        st.warning("Tick the confirmation checkbox first.")
                    else:
                        with st.spinner("Deleting expense..."):
                            ok, result = api_delete(
                                API_BASE_URL,
                                "/expenses/" + quote(selected_id, safe=""),
                            )

                        if ok:
                            st.success("Delete request completed.")
                            st.rerun()
                        else:
                            show_api_error(result)
        else:
            st.caption("There are no expenses to delete in this view.")


# ---------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------

elif page == "Budgets":
    st.subheader("🎯 Monthly budgets")

    month = st.text_input(
        "Budget month (YYYY-MM)",
        value=date.today().strftime("%Y-%m"),
        max_chars=7,
        key="budgets_month",
    ).strip()

    if not validate_month(month):
        st.warning("Enter a valid month in YYYY-MM format.")
        st.stop()

    st.markdown("#### Create or update a budget")

    with st.form("add_budget_form"):
        budget_category = st.selectbox(
            "Category",
            get_categories(),
            key="budget_category",
        )
        budget_amount = st.number_input(
            "Budget limit (INR)",
            min_value=0.01,
            value=1000.0,
            step=100.0,
            format="%.2f",
        )
        budget_submitted = st.form_submit_button(
            "Save budget",
            type="primary",
        )

    if budget_submitted:
        payload = {
            "month": month,
            "category": budget_category,
            "amount": round(float(budget_amount), 2),
        }

        with st.spinner("Saving budget..."):
            ok, result = api_post(
                API_BASE_URL,
                "/budgets",
                payload,
            )

        if ok:
            st.success("Budget saved successfully.")
            st.json(result if isinstance(result, dict) else {"result": result})
        else:
            show_api_error(result)

    st.divider()
    st.markdown("#### Existing budgets")

    ok, result = api_get(
        API_BASE_URL,
        "/budgets",
        params={"month": month},
    )

    if not ok:
        show_api_error(result)
    else:
        budgets = as_list(result)
        budgets = [
            item for item in budgets
            if isinstance(item, dict) and not item.get("_deleted", False)
        ]

        if budgets:
            display_table(budgets)
        else:
            st.info(f"No budgets found for {month}.")


# ---------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------

elif page == "Categories":
    st.subheader("🏷️ Expense categories")

    ok, result = api_get(API_BASE_URL, "/categories")

    if ok:
        rows = as_list(result)
        rows = [row for row in rows if isinstance(row, dict)]

        if rows:
            display_table(rows)
        else:
            st.info("The API returned no category records.")
    else:
        st.warning("Could not load categories from the API.")
        st.write("Built-in categories are available below.")

    st.divider()
    st.markdown("#### Available categories")

    category_names = get_categories()
    for name in category_names:
        st.markdown(f"- **{name}**")

    st.divider()
    st.markdown("#### Category spending details")

    chosen_category = st.selectbox(
        "Choose a category",
        category_names,
        key="category_detail_name",
    )

    if st.button("Load category details"):
        ok, result = api_get(
            API_BASE_URL,
            "/category/" + quote(chosen_category, safe=""),
        )

        if ok:
            st.json(result)
        else:
            st.warning("The category details endpoint could not be loaded.")
            st.caption(str(result))


# ---------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------

elif page == "Integrations":
    st.subheader("🔗 Integrations")
    st.write(
        "This page shows integration status and requests a data sync. "
        "Person B and Person C must have reachable APIs configured "
        "in the backend before their data can be imported."
    )

    if st.button("Check integration status"):
        ok, result = api_get(API_BASE_URL, "/integrations/status")

        if ok:
            st.success("Status request completed.")
            st.json(result)
        else:
            show_api_error(result)

    st.divider()
    st.markdown("#### Synchronize data")

    sync_source = st.selectbox(
        "Integration to synchronize",
        ["all", "subscription_tracker", "smart_home_energy"],
        format_func=lambda value: {
            "all": "All integrations",
            "subscription_tracker": "Person B — Subscription Tracker",
            "smart_home_energy": "Person C — Electricity Manager",
        }.get(value, value),
    )

    if st.button("Start sync", type="primary"):
        payload = {"source": sync_source}

        with st.spinner("Requesting synchronization..."):
            ok, result = api_post(
                API_BASE_URL,
                "/integrations/sync",
                payload,
            )

        if ok:
            st.success("Sync request completed.")
            st.json(result if isinstance(result, dict) else {"result": result})
        else:
            show_api_error(result)

    st.info(
        "A successful request does not necessarily mean another person's "
        "data was imported. Check the returned sync results and integration "
        "configuration."
    )


# ---------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------

st.divider()
st.caption(
    "Person A | CSI3007 Advanced Python Programming | "
    "Google Apps Script + Google Sheets"
)
