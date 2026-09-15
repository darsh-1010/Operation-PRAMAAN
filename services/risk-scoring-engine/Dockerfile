FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8004

# WEB_CONCURRENCY: uvicorn worker processes. Safe to run >1 now that store.py's pending/result
# state lives in Redis instead of an in-process dict (see store.py) — workers/replicas share it.
ENV WEB_CONCURRENCY=2
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8004 --workers ${WEB_CONCURRENCY}"]
