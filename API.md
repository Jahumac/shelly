# Shelly Finance JSON API

Bearer-token HTTP JSON API for external clients (Android, desktop, scripts).

**Base URL:** `http://<your-host>:<port>/api/v1`
**Auth:** `Authorization: Bearer <token>` on every request.
**Response type:** `application/json`.

---

## Minting a token

Tokens are created from the command line on the server:

```bash
python scripts/api_token.py create <username> "my android phone"
```

The token prints once. Save it — it is not recoverable. To list or revoke:

```bash
python scripts/api_token.py list <username>
python scripts/api_token.py revoke <token_id>
```

Tokens are stored in the `api_tokens` table alongside `last_used_at` so you
can see which tokens are active.

---

## Error format

Non-2xx responses always return:

```json
{ "error": "<code>", "message": "<human-readable>" }
```

Codes currently used: `missing_token`, `invalid_token`, `not_found`,
`bad_request`, `method_not_allowed`, `server_error`.

---

## Endpoints

All endpoints are GET, require auth, and are scoped to the token's user.

### `GET /me`
Current user info.
```json
{ "id": 1, "username": "alice", "is_admin": true }
```

### `GET /accounts`
List all active accounts for the user.
```json
{ "accounts": [ { "id": 1, "name": "...", "wrapper_type": "...", ... } ] }
```

### `GET /accounts/<id>`
Single account with its holdings embedded.
```json
{ "id": 1, "name": "...", "holdings": [ ... ] }
```

### `GET /holdings`
Every holding across every account.

### `GET /goals`
List goals.

### `GET /overview`
Aggregate snapshot.
```json
{ "total_value": 123456.78, "monthly_contribution": 1000, "account_count": 5 }
```

### `GET /budget/<YYYY-MM>`
Budget for a specific month. Falls back to default amounts if no entries
exist yet for that month.

### `GET /assumptions`
Growth rate, retirement age, ISA/LISA allowances, etc.

### `GET /health`  _(no auth)_
Liveness probe for uptime monitors. Returns 200 with DB status and last
backup time, or 503 if the DB is unreachable.
```json
{
  "ok": true,
  "checks": { "database": "ok", "last_backup": "2026-04-14T03:00:02" },
  "timestamp": "2026-04-14T12:00:00+00:00"
}
```

---

## Write endpoints

All writes require auth and are scoped to the token's user (attempting
to mutate another user's data returns 404).

### `POST /accounts/<id>/balance`
Update a manual-valuation account's balance. Also records a monthly
snapshot so history stays consistent with the monthly-review flow.
```json
{ "current_value": 12345.67, "month": "2026-04" }    ← month optional
```

### `POST /contributions/isa`
Log an ISA contribution.
```json
{ "account_id": 3, "amount": 500, "date": "2026-04-10", "note": "optional" }
```

### `POST /contributions/pension`
Log a pension contribution. `kind` is one of: `personal`, `employer`,
`salary_sacrifice`.
```json
{ "account_id": 7, "amount": 400, "date": "2026-04-10",
  "kind": "personal", "note": "optional" }
```

### `POST /dividends`
Log a dividend receipt.
```json
{ "account_id": 2, "amount": 50, "date": "2026-04-10", "note": "optional" }
```

---

## Example

```bash
TOKEN=<your-token>
curl -H "Authorization: Bearer $TOKEN" https://shelly.example.com/api/v1/overview
```

---

## Stability

Breaking changes will go under `/api/v2`. New fields may be added to
existing responses without warning — clients must ignore unknown keys.

Writes (POST/PUT/DELETE) are intentionally not exposed yet. Add them
endpoint-by-endpoint when you have a concrete client need — it's easier to
keep an API safe when it grows deliberately.
