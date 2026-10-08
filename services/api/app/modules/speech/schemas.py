from typing import Literal

from pydantic import BaseModel, Field


class SpeechTranscription(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    language: Literal["ru", "kk"]
    model: Literal["large-v3-turbo"] = "large-v3-turbo"
    duration_seconds: float = Field(gt=0, le=60, allow_inf_nan=False)
    is_mock: bool = False
