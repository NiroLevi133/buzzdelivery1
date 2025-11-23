FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# הגדרת משתני סביבה (יוגדרו בפועל ב-Cloud Run)
ENV PORT=8080

CMD uvicorn webhook_server:app --host 0.0.0.0 --port $PORT