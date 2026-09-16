FROM python:3.11-slim

WORKDIR /app

# paddleocr/paddlex pull in a full opencv build (opencv-contrib-python) alongside our own
# opencv-python-headless pin — whichever installs last wins the file overwrite, since both
# ship a `cv2` module. python:3.11-slim has none of the shared libs that build needs at
# import time (PaddleOCR was silently falling back to Tesseract because of this), so
# install them rather than fight pip over which opencv variant "wins".
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

# WEB_CONCURRENCY: uvicorn worker processes. Heavy OCR/CV pipeline calls run off the event
# loop (see main.py's run_in_threadpool use) but still tie up one worker's thread pool for
# the duration of a request, so more than 1 process is needed for real concurrency.
ENV WEB_CONCURRENCY=2
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8001 --workers ${WEB_CONCURRENCY}"]
