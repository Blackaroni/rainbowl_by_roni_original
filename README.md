# Rainbowl

Rainbowl is a separate order, payments, and cash-tracking app for a colour-coordinated product line. This project lives in its own folder with its own schema, env file, and starter catalogue.

## Starter catalogue

The schema seeds these products automatically on `init-db`:

- `RB-01` Maxi Fruit Bowl: cost `3000`, selling `3500`
- `RB-02` Mini Fruit Bowl: cost `1250`, selling `1500`
- `RB-03` Maxi Bowling Pin: cost `3800`, selling `5000`
- `RB-04` Mini Bowling Pin: cost `2100`, selling `3000`

The same starter data is also available in [csv_files/products.csv](csv_files/products.csv) if you prefer the import flow.

## Folder layout

- `rainbowl_app/`: backend package
- `static/`: frontend
- `sql/postgres_rainbowl.sql`: schema and starter seed
- `.env`: Rainbowl-specific connection settings
- `.env.example`: safe template for sharing or resetting config

## Supabase setup

1. Open `.env` in this folder and replace the placeholder values with your Supabase details.
2. Recommended Supabase values:

```dotenv
DB_HOST=aws-0-your-region.pooler.supabase.com
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres.your-project-ref
DB_PASSWORD=your-supabase-password
DB_SCHEMA=rainbowl
DB_SSLMODE=require
DB_CONNECT_TIMEOUT=5
APP_HOST=127.0.0.1
APP_PORT=8010
```

3. Apply the schema:

```powershell
python server.py init-db
```

That creates the `rainbowl` schema, all app tables, the `sales_lines` view, and the four starter products.

## Run locally

```powershell
python server.py serve
```

Then open `http://127.0.0.1:8010`.

## Import flow

If you later export data from sheets or another system, the same import commands are available here:

```powershell
python server.py import --products csv_files/products.csv
```

You can also supply `--customers`, `--sales`, `--expenses`, and `--accounts` as needed.

## Notes

- This project uses the `rainbowl` schema by default.
- The frontend uses `window.RAINBOWL_CONFIG` in [static/config.js](static/config.js) for an external API base URL.
- The default app port is `8010` so it can run alongside your other local project on the same machine.
