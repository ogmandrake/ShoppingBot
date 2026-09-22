# ShoppingBot

ShoppingBot includes a daily AI-powered deals agent that:
- Reads shopping prompts from `shopping_prompts.txt` (one item per line)
- Searches online retailers and stores all parsed offers with their Canada-shipping status
- Tracks item price and shipping cost history in PostgreSQL
- Detects sale price drops compared to prior runs
- Sends an email alert when sales are detected

## Files
- `agent/daily_deals_agent.py`: daily deals collection, sale detection, and email notification logic
- `shopping_prompts.txt`: your shopping prompts (one item per line)
- `data/sale_report.txt`: last sale alert summary
- `data/last_response.json`: most recent SerpAPI JSON response, overwritten on each search
- `.github/workflows/daily-deals-agent.yml`: daily GitHub Actions automation

## Setup
1. Add your desired items to `shopping_prompts.txt`, one per line.
2. Configure repository secrets for email notifications:
   - `DATABASE_URL`
   - `SERPAPI_API_KEY`
   - `SMTP_HOST`
   - `SMTP_PORT`
   - `SMTP_USERNAME`
   - `SMTP_PASSWORD`
   - `ALERT_EMAIL_TO`
   - `ALERT_EMAIL_FROM` (optional; defaults to SMTP username)
3. Enable GitHub Actions for the repository.

The workflow runs daily at 13:00 UTC and can also be run manually using **Run workflow**.

## Local run
```bash
pip install -r requirements.txt
python agent/daily_deals_agent.py
```

## Docker
Build the image from the repository root:
```bash
docker build -t shoppingbot .
```

Run the agent with a PostgreSQL connection string:
```bash
docker run --rm \
   -e DATABASE_URL="postgresql://user:password@host:5432/shoppingbot" \
   -e SERPAPI_API_KEY="your-serpapi-key" \
   shoppingbot
```

## Local PostgreSQL with Docker Compose
Start PostgreSQL in the background:
```bash
docker compose up -d postgres
```

Build and run the shopping bot against the Compose PostgreSQL service:
```bash
docker compose up --build shoppingbot
```

Set `SERPAPI_API_KEY` in the host environment before running Compose:
```powershell
$env:SERPAPI_API_KEY = "your-serpapi-key"
docker compose up --build shoppingbot
```

The bot is a one-shot container: it runs the configured shopping scan and exits. The Compose connection string uses the internal service name `postgres`; from the host, use `localhost` instead.

Set `VERBOSE_LOGGING=true` in `.env` to log external request URLs, response status, headers, and bodies. API keys are redacted from logged URLs.

Run the external SerpAPI connectivity test through Compose:
```powershell
docker compose run --rm --entrypoint python shoppingbot -m unittest discover -s /app/tests -v
```

The external tests are skipped when `SERPAPI_API_KEY` is not configured. They include a real `iphone` shopping search. The Docker image does not include `tests` or `mock_results.json`, so mount both when running the command:
```powershell
docker compose run --rm --entrypoint python `
   -v "${PWD}/tests:/app/tests" `
   -v "${PWD}/mock_results.json:/app/mock_results.json:ro" `
   shoppingbot -m unittest discover -s /app/tests -v
```

For local development, use:
```text
DATABASE_URL=postgresql://shoppingbot:shoppingbot@localhost:5432/shoppingbot
```

The database data is stored on the host at `C:\tmp\pgadmin-data-shoppingbot`. Stop the database with:
```bash
docker compose down
```

To remove the database and its local data, stop the stack and delete `C:\tmp\pgadmin-data-shoppingbot`:
```bash
docker compose down
Remove-Item -Recurse -Force C:\tmp\pgadmin-data-shoppingbot
```

Pass email settings and other runtime options with `-e`, for example:
```bash
docker run --rm \
   -e DATABASE_URL="postgresql://user:password@host:5432/shoppingbot" \
   -e SERPAPI_API_KEY="your-serpapi-key" \
   -v "${PWD}/data:/app/data" \
   -e SMTP_HOST=smtp.example.com \
   -e SMTP_PORT=587 \
   -e SMTP_USERNAME=your-user \
   -e SMTP_PASSWORD=your-password \
   -e ALERT_EMAIL_TO=you@example.com \
   shoppingbot
```
