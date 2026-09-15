FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

# WEB_CONCURRENCY: uvicorn worker processes. Heavy OCR/CV pipeline calls run off the event
# loop (see main.py's run_in_threadpool use) but still tie up one worker's thread pool for
# the duration of a request, so more than 1 process is needed for real concurrency.
ENV WEB_CONCURRENCY=2
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8001 --workers ${WEB_CONCURRENCY}"]
