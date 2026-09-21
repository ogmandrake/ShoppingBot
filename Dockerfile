FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent ./agent
COPY shopping_prompts.txt .

RUN mkdir -p /app/data

VOLUME ["/app/data"]

ENTRYPOINT ["python", "agent/daily_deals_agent.py"]