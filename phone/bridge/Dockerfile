FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY bridge.py .
USER 10001:10001
CMD ["python", "-u", "bridge.py"]
