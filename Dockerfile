FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure the data directory exists for the SQLite DB and secret key
RUN mkdir -p /app/data

EXPOSE 8000

# Use gunicorn for production — 2 worker processes, binds to all interfaces
CMD ["gunicorn", "--workers=2", "--bind=0.0.0.0:8000", "--timeout=60", "run:app"]
