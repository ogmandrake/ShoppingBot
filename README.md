# ShoppingBot

ShoppingBot includes a daily AI-powered deals agent that:
- Reads shopping prompts from `shopping_prompts.txt` (one item per line)
- Searches online retailers and keeps offers that appear to ship to Canada
- Tracks item price and shipping cost history in PostgreSQL
- Detects sale price drops compared to prior runs
- Sends an email alert when sales are detected

## Files
- `agent/daily_deals_agent.py`: daily deals collection, sale detection, and email notification logic
- `shopping_prompts.txt`: your shopping prompts (one item per line)
- `data/sale_report.txt`: last sale alert summary
- `.github/workflows/daily-deals-agent.yml`: daily GitHub Actions automation

## Setup
1. Add your desired items to `shopping_prompts.txt`, one per line.
2. Configure repository secrets for email notifications:
   - `DATABASE_URL`
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
   shoppingbot
```

## Local PostgreSQL with Docker Compose
Start PostgreSQL in the background:
```bash
docker compose up -d postgres
```

For local development, use:
```text
DATABASE_URL=postgresql://shoppingbot:shoppingbot@localhost:5432/shoppingbot
```

The database data is stored in the named `shoppingbot-postgres-data` volume. Stop the database with:
```bash
docker compose down
```

To remove the database and its local data:
```bash
docker compose down -v
```

Pass email settings and other runtime options with `-e`, for example:
```bash
docker run --rm \
   -e DATABASE_URL="postgresql://user:password@host:5432/shoppingbot" \
   -v "${PWD}/data:/app/data" \
   -e SMTP_HOST=smtp.example.com \
   -e SMTP_PORT=587 \
   -e SMTP_USERNAME=your-user \
   -e SMTP_PASSWORD=your-password \
   -e ALERT_EMAIL_TO=you@example.com \
   shoppingbot
```
