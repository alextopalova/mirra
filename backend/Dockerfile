# Mirra backend — FastAPI + MediaPipe
# Python 3.12 to match the development environment (mediapipe 0.10.35 wheels).
FROM python:3.12-slim

# OpenCV/MediaPipe runtime libs (headless).
#
# These are the native .so files the wheels dlopen but don't vendor. Two
# separate consumers, needing different libraries -- both are required:
#
#   libgl1        libGL.so.1     -- `import cv2`. requirements.txt asks for
#                                   opencv-python-headless, which wouldn't
#                                   need this, but mediapipe depends on the
#                                   non-headless opencv-contrib-python and
#                                   that's the build that actually gets
#                                   imported, so headless is not in effect.
#   libgles2      libGLESv2.so.2 -- mediapipe's own C bindings, loaded lazily
#   libegl1       libEGL.so.1       via ctypes.CDLL the first time an
#                                   mp.Image is constructed (see
#                                   app/cv/measure.py extract_landmarks).
#   libglib2.0-0  libgvc/glib      -- transitively needed by the above.
#
# The mediapipe ones fail LAZILY, on the first real request rather than at
# import, so /health returning 200 does not prove they're present. Verify a
# change here with an actual POST /analyze-body carrying a real photo.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 libegl1 libgles2 curl \
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
