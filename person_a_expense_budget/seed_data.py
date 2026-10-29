"""Seed Person A's database with demo data for demos and presentations.

Usage:  python seed_data.py
Idempotent for integration-style rows (uses fixed external ids); manual demo
expenses are added only when the expenses table is empty.
"""
from datetime import date

from database import Base, SessionLocal, engine
from crud import create_budget, create_expense, get_or_create_category, list_budgets, list_expenses, seed_default_categories
from services.categorizer import categorize_merchant

DEMO_EXPENSES = [
    # (day_of_month, merchant, amount, category_or_None)
    (2, "Swiggy", 412.50, None),
    (3, "Uber", 236.00, None),
    (4, "TNEB Electricity Bill", 845.00, "Bills"),
    (5, "Netflix", 199.00, None),
    (6, "Amazon", 1580.00, None),
    (7, "A2B Veg Restaurant", 340.00, None),
    (8, "Indian Oil Petrol", 1000.00, None),
    (10, "BookMyShow", 470.00, None),
    (12, "ACT Fibernet", 799.00, None),
    (15, "Zomato", 289.00, None),
    (18, "Spotify", 119.00, "Subscriptions"),
    (20, "Decathlon", 1249.00, None),
]

DEMO_BUDGETS = [
    ("Food", 3000.0),
    ("Travel", 2500.0),
    ("Bills", 2000.0),
    ("Entertainment", 1000.0),
    ("Shopping", 2000.0),
    ("Subscriptions", 700.0),
]


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_default_categories(db)
        month = date.today().strftime("%Y-%m")

        if not list_expenses(db, month=month, limit=1):
            today = date.today()
            for day, merchant, amount, category in DEMO_EXPENSES:
                expense_date = date(today.year, today.month, min(day, 28))
                create_expense(
                    db,
                    expense_date=expense_date,
                    merchant=merchant,
                    amount=amount,
                    category_name=category or categorize_merchant(merchant)[0],
                    description="Demo seed row",
                )
            print(f"Seeded {len(DEMO_EXPENSES)} demo expenses for {month}.")
        else:
            print(f"Expenses already exist for {month}; skipped expense seeding.")

        existing_budgets = {(b.category, b.month) for b in list_budgets(db)}
        created = 0
        for category, limit in DEMO_BUDGETS:
            if (category, month) not in existing_budgets:
                category_obj = get_or_create_category(db, category)
                create_budget(db, category_id=category_obj.id, month=month, amount_limit=limit)
                created += 1
        print(f"Seeded {created} demo budgets for {month}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
