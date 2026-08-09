#!/usr/bin/env bash
# Downloads MediaPipe models used by app/cv/measure.py (not committed --
# git-ignored, ~9MB pose model + ~250KB segmenter model).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)/models"
mkdir -p "$DIR"

curl -fL --retry 3 -o "$DIR/pose_landmarker.task" \
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task"
echo "model ready: $DIR/pose_landmarker.task"

curl -fL --retry 3 -o "$DIR/selfie_segmenter.tflite" \
  "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/latest/selfie_segmenter.tflite"
echo "model ready: $DIR/selfie_segmenter.tflite"
