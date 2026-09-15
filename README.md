# ShoppingBot

ShoppingBot includes a daily AI-powered deals agent that:
- Reads shopping prompts from `shopping_prompts.txt` (one item per line)
- Searches online retailers and keeps offers that appear to ship to Canada
- Tracks item price and shipping cost history in `data/price_history.csv`
- Detects sale price drops compared to prior runs
- Sends an email alert when sales are detected

## Files
- `agent/daily_deals_agent.py`: daily deals collection, sale detection, and email notification logic
- `shopping_prompts.txt`: your shopping prompts (one item per line)
- `data/price_history.csv`: auto-generated price + shipping history
- `data/sale_report.txt`: last sale alert summary
- `.github/workflows/daily-deals-agent.yml`: daily GitHub Actions automation

## Setup
1. Add your desired items to `shopping_prompts.txt`, one per line.
2. Configure repository secrets for email notifications:
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
