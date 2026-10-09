FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir 'fastapi>=0.115,<1' 'uvicorn>=0.30,<1' 'python-multipart>=0.0.18,<1' 'httpx>=0.27,<1' 'faster-whisper>=1.1,<2' 'piper-tts>=1.3,<2' 'av==18.1.0' 'websockets>=14,<16'
RUN mkdir /cache /state && chown 10001:10001 /cache /state
WORKDIR /app
COPY app.py panel_tools.py /app/
COPY static /app/static
USER 10001:10001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

COPY phone_api.py /app/phone_api.py
