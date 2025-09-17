# TONA — Telegram Open Network Arbitrage (Telegram self-client)

A minimal async watcher for the Portals marketplace that runs from your own Telegram account.  
It scans configured “models”, filters by allowed backdrops from a CSV, logs under-floor listings, and triggers a buy callback (stubbed).

## Features
- Auth token auto-refresh & caching
- Batched, concurrent searches with retry/backoff & result caching
- Per-model backdrop allow-list from CSV
- Simple Telegram control: `/start` to begin, `/stop` to end (DM yourself)
- Clean structured logging

## Requirements
- Python 3.10+
- Telegram app credentials (API_ID / API_HASH)
- A valid `model-backdrop-match.csv` with headers: `col` (model), `name` (backdrop)
- The `portalsmp` package (provides `search` and `update_auth`)

## Quickstart
```bash
python -m venv .venv
source ./venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env         # then edit values
python main.py
```

### `.env` example
```dotenv
API_ID=123456
API_HASH=your_api_hash
SESSION_NAME=tona

# Optional tuning
PORTALS_MAX_RETRIES=2
PORTALS_BACKOFF_BASE=0.3
PORTALS_RETRY_DELAY=1.0
CACHE_TTL=1.5
```

## Usage
1. Start the app: `python main.py`  
2. In your Telegram “Saved Messages” (or any chat where you’re the sender), send:
   - `/start` — begins the monitoring loop
   - `/stop` — gracefully stops it

Example log line:
```
[PORTALS] Model X #123 | 8.5 TON (floor 10.0)
```

If `price > 0` and `price < floor_price`, the app calls `buy_item(...)`.  
> The actual purchase logic is commented out; wire your own function where indicated.

## How it works
- **Auth**: `Portals.get_auth()` refreshes every 30 min (configurable), falls back to cached token on transient errors.
- **Mapping**: `model-backdrop-match.csv` maps each `model` to an allow-listed set of `backdrops`.
- **Search**: `search_multiple_models()` runs concurrent queries with:
  - retry w/ jittered exponential backoff,
  - per-model short-lived cache (`CACHE_TTL`),
  - result filtering by backdrop.
- **Loop**: `optimized_loop()` iterates models in fixed-size batches, sleeps between batches, and invokes your `on_items` callback.

## Configuration knobs (defaults in code)
- `search_limit` (default `100`)
- `sleep_between_models` (default `0.95` s)
- `request_timeout` (default `3.0` s)
- `batch_size` (default `2`)
- `PORTALS_MAX_RETRIES` (default `2`)
- `PORTALS_BACKOFF_BASE` (default `0.3`)
- `PORTALS_RETRY_DELAY` (default `1.0`)
- `CACHE_TTL` (default `1.5` s)

## CSV format
`model-backdrop-match.csv` (UTF-8, BOM tolerated)
| col (model) | name (backdrop) |
|-------------|------------------|
| abc_model   | blue neon        |
| abc_model   | red chrome       |
| xyz_model   | sunset           |

## Expected item shape (minimum used)
```python
{
  "id": "...",
  "name": "...",
  "price": 8.5,
  "floor_price": 10.0,
  "attributes": [
    {"type": "backdrop", "value": "blue neon"}
  ]
}
```

## Extending: implement buying
Edit `TONAApp.buy_item(...)`:
```python
# success = await portals_buy_item(item_id, price)
# if success: ...
```
Add your signer, slippage checks, and error handling as needed.

## Troubleshooting
- **CSV file not found**: ensure `model-backdrop-match.csv` is in the working directory or pass a path when constructing `Portals`.
- **Auth update failed**: verify `API_ID`/`API_HASH`; transient issues will fall back to cached token.
- **Timeouts / rate limits**: increase `sleep_between_models`, `request_timeout`, or reduce `batch_size`/`search_limit`.
- **No results / all filtered**: confirm your CSV model/backdrop names match marketplace values (case-insensitive, trimmed).

## Project structure
```
.
├─ main.py        # Telegram app & command handlers
├─ portal.py      # Portals client, search loop, filters
├─ model-backdrop-match.csv
├─ .env
└─ requirements.txt
```