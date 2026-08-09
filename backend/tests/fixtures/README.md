# Test fixtures

## `person_front.jpg` (committed)

Used by `test_measure_from_images_returns_plausible_and_classifiable` in
`tests/test_measure.py`, to exercise the real MediaPipe pipeline
end-to-end. That test is skipped automatically (`pytest.mark.skipif`) if
this file is ever absent, so the suite stays green either way -- but it
normally isn't absent: this photo is deliberately committed to the repo
(the author has confirmed they hold the rights to it), rather than kept
local/git-ignored, so this end-to-end check runs for every contributor
out of the box.

Requirements for the photo:

- Full body in frame, front-facing.
- Ankles (both feet) visible and not cropped out -- leg length is measured
  from hip to ankle, so a cropped-at-the-knee photo will fail the
  visibility check (`ValueError: full body not visible`).
- Shoulders and hips clearly visible (not heavily occluded by loose
  clothing, arms crossed over the torso, etc.).
- A single person in the shot (only `pose_landmarks[0]`, the first
  detected person, is used).
- Rights to use/commit the photo confirmed by the author.

Any modern phone photo taken a few steps back, standing straight, arms
slightly away from the body, works well.
