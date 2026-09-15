FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8002

# WEB_CONCURRENCY: uvicorn worker processes — see the other 3 services' Dockerfiles for why.
ENV WEB_CONCURRENCY=2
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8002 --workers ${WEB_CONCURRENCY}"]
