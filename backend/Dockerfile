# Mirra backend — FastAPI + MediaPipe
# Python 3.12 to match the development environment (mediapipe 0.10.35 wheels).
FROM python:3.12-slim

# OpenCV/MediaPipe runtime libs (headless).
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The MediaPipe model files are not committed (~9MB); fetch them at build time
# so the image is self-contained and the container starts without network access.
RUN chmod +x ./scripts_setup_model.sh && ./scripts_setup_model.sh

ENV PORT=8000
EXPOSE 8000

# Respect the platform-provided $PORT (Render/Railway/Fly all set it).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
