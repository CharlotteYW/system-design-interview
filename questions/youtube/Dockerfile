FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# hls.js plays HLS in browsers that lack native support.
RUN mkdir -p /app/vendor && python -c "import urllib.request; urllib.request.urlretrieve('https://cdn.jsdelivr.net/npm/hls.js@1.5.15/dist/hls.min.js', '/app/vendor/hls.min.js')"
COPY src ./src

EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
