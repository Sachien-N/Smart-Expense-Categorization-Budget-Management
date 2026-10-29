# API Documentation - Person A (Smart Expense Categorization & Budget API)

- Base URL (local): `http://127.0.0.1:8001`
- Interactive OpenAPI docs: `http://127.0.0.1:8001/docs`
- Auth: none (course demo scope; do not expose to the public internet as-is)
- Content type: `application/json`
- Errors: FastAPI standard - `422` validation, `404` missing resource,
  `409` uniqueness conflicts, `500` never expected on integration paths.

---

## System

### `GET /health`
Liveness + database connectivity probe (also polled by teammates' tools).

```json
{
  "status": "ok",
  "service": "expense-budget-api",
  "owner": "Person A - Sachien N (23MID0255)",
  "version": "1.0.0",
  "database": "connected",
  "time": "2026-10-28T13:35:59.082892+00:00"
}
```

## Expenses

### `POST /expenses` -> 201
Creates an expense. When `category` is omitted, the rule-based categorizer
assigns one (see `GET /categorize`); no-rule merchants land in
`Uncategorized`.

```bash
curl -X POST http://127.0.0.1:8001/expenses \
  -H "Content-Type: application/json" \
  -d '{"merchant": "Netflix", "amount": 199.0, "expense_date": "2026-10-05"}'
```

```json
{
  "id": 1, "expense_date": "2026-10-05", "merchant": "Netflix",
  "description": "", "amount": 199.0, "category": "Subscriptions",
  "source": "manual", "external_id": null,
  "created_at": "...", "updated_at": "..."
}
```

Validation: `merchant` 1-120 chars; `amount` > 0; `expense_date` ISO date
(defaults to today); unknown category names are created on demand;
`external_id` (integration use) is unique - duplicates give `409`.

### `GET /expenses`
Query params: `month` (`YYYY-MM`), `category`, `source`
(`manual|integration`), `limit` (1-200, default 50), `offset`.
Ordered newest-first.

```bash
curl "http://127.0.0.1:8001/expenses?month=2026-10&source=integration"
```

### `GET /expenses/{id}` -> 200 | 404
### `PUT /expenses/{id}` -> 200
Partial update; all fields optional (`merchant`, `amount`, `expense_date`,
`category`, `description`).

### `DELETE /expenses/{id}` -> 200
```json
{ "deleted": true, "id": 7 }
```

## Categories

### `GET /categories`
Six canonical (`Food`, `Travel`, `Bills`, `Entertainment`, `Shopping`,
`Subscriptions`) + the `Uncategorized` fallback, seeded idempotently at
startup.

### `GET /category/{name}` -> 200 | 404
Case-insensitive drill-down:

```json
{
  "category": "Food", "expense_count": 2, "total_amount": 701.5,
  "first_expense_date": "2026-10-02", "last_expense_date": "2026-10-15",
  "expenses": [ /* ExpenseOut[] */ ]
}
```

## Summary & categorizer

### `GET /summary?month=YYYY-MM`
Month roll-up (defaults to the current month). An empty month is a **valid
zero** (`total_expenses: 0.0`, empty lists), not an error.

```json
{
  "month": "2026-10",
  "total_expenses": 8123.4,
  "transaction_count": 14,
  "by_category": [
    {"category": "Shopping", "total": 1580.0, "count": 1, "share_percent": 19.5}
  ],
  "budget_comparison": [
    {"category": "Food", "budget": 3000.0, "spent": 1041.5,
     "remaining": 1958.5, "utilization_percent": 34.7, "over_budget": false}
  ]
}
```

### `GET /categorize?merchant=Netflix`
Explainable, save-free preview:

```json
{
  "merchant": "Netflix",
  "suggested_category": "Subscriptions",
  "matched_keyword": "netflix",
  "confidence": "rule",
  "reason": "Merchant matched keyword 'netflix' (first rule in priority order wins)"
}
```

Rule priority: Subscriptions > Entertainment > Food > Travel > Bills >
Shopping; fallback `Uncategorized` with `confidence: "fallback"`.

## Budgets

### `GET /budgets?month=YYYY-MM`
Budgets enriched with live spend:

```json
{
  "id": 1, "category": "Travel", "month": "2026-10", "amount_limit": 2500.0,
  "spent": 1236.0, "remaining": 1264.0, "utilization_percent": 49.4,
  "over_budget": false
}
```

### `POST /budgets` -> 201 | 409 (duplicate category+month)
```bash
curl -X POST http://127.0.0.1:8001/budgets \
  -H "Content-Type: application/json" \
  -d '{"category": "Food", "month": "2026-10", "amount_limit": 3000}'
```

## Integrations (cross-app, HTTP REST only)

A **never** opens B's or C's SQLite files. All data flows through their
documented endpoints.

### `GET /integrations/status`
Live probe of both peers (short timeout, no retries):

```json
{
  "checked_at": "2026-10-28T13:37:36.523860+00:00",
  "services": [
    {"service_key": "subscription_tracker", "base_url": "http://127.0.0.1:8002",
     "status": "available", "peer_service_name": "subscription-cost-tracker",
     "peer_version": "1.0.0", "latency_ms": 3.6, "error": null},
    {"service_key": "smart_home_energy", "base_url": "http://127.0.0.1:8003",
     "status": "unavailable", "peer_service_name": null,
     "peer_version": null, "latency_ms": null,
     "error": "connection_error: ConnectionError"}
  ]
}
```

`status` ∈ `available | unavailable | invalid_response | not_configured`
(`not_configured` when the env var is blank - integration intentionally off).

### `POST /integrations/sync`
Pulls both peers and imports idempotently. **Partial failure never blocks the
other source and never returns 500.**

```json
{
  "synced_at": "2026-10-28T13:34:56.873193+00:00",
  "overall": "ok",
  "results": [
    {"source": "subscription_tracker", "status": "ok", "imported": 9, "skipped": 1,
     "basis": null, "error": null,
     "details": [
       {"external_ref": "B-SUB-10", "action": "skipped_inactive"},
       {"external_ref": "B-SUB-2", "action": "imported"} ]},
    {"source": "smart_home_energy", "status": "ok", "imported": 1, "skipped": 0,
     "basis": "actual", "error": null,
     "details": [{"external_ref": "C:actual:2026-09", "action": "imported"}]}
  ]
}
```

- B imports: active subscriptions -> `Subscriptions` expenses, amount =
  pre-normalized `monthly_cost`, `external_id = B:{external_ref}:{YYYY-MM}`.
- C imports: most recent month with an actual bill, else the most recent
  completed month's estimate -> `Bills` expense, `external_id = C:{basis}:{month}`.
- `action` values: `imported`, `already_imported`, `skipped_inactive`,
  `skipped_invalid_payload`, `skipped_malformed_entry`.
- `overall` ∈ `ok | partial | failed`.
- Idempotency: re-running always yields `already_imported` (UNIQUE index on
  `expenses.external_id`) - verified live and in the test suite.

## Consumed peer contracts (frozen)

| Peer | Endpoint | Key fields A relies on |
|---|---|---|
| B | `GET /integration/export` | `service`, `subscriptions[].external_ref/name/monthly_cost/active` |
| C | `GET /history?months=6` | `months[].month/estimated_amount/actual_amount` |
