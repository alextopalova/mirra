from typing import Optional

from pydantic import BaseModel


class BodyMeasurements(BaseModel):
    shoulder_w: float
    bust_w: float
    waist_w: float
    hip_w: float
    torso_len: float
    leg_len: float
    bmi: float
    has_side: bool = False
    torso_depth: Optional[float] = None


class BodyProfile(BaseModel):
    fruit: str
    japanese: str
    japanese_weights: dict[str, float]
    confidence: float
    summary: str
