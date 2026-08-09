# Test fixtures

## `person_front.jpg` (not committed)

Used by `test_measure_from_images_returns_plausible_and_classifiable` in
`tests/test_measure.py`. That test is skipped automatically
(`pytest.mark.skipif`) when this file is absent, so the suite stays green
without it -- drop a photo in to exercise the real MediaPipe pipeline
end-to-end.

Requirements for the photo:

- Full body in frame, front-facing.
- Ankles (both feet) visible and not cropped out -- leg length is measured
  from hip to ankle, so a cropped-at-the-knee photo will fail the
  visibility check (`ValueError: full body not visible`).
- Shoulders and hips clearly visible (not heavily occluded by loose
  clothing, arms crossed over the torso, etc.).
- A single person in the shot (only `pose_landmarks[0]`, the first
  detected person, is used).
- Permissively licensed if this repo intends to commit it -- otherwise
  keep it local/git-ignored.

Any modern phone photo taken a few steps back, standing straight, arms
slightly away from the body, works well.
