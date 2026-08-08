#!/usr/bin/env bash
# Downloads the MediaPipe Pose Landmarker model (not committed; ~9MB).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)/models"
mkdir -p "$DIR"
curl -fL --retry 3 -o "$DIR/pose_landmarker.task" \
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task"
echo "model ready: $DIR/pose_landmarker.task"
