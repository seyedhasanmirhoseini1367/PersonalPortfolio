from pydantic import BaseModel, field_validator
from typing import Any


def _flatten_list(v: Any) -> list[str]:
    if not isinstance(v, list):
        return [str(v)]
    result = []
    for item in v:
        if isinstance(item, list):
            result.extend(str(i) for i in item)
        else:
            result.append(str(item))
    return result


def _to_str(v: Any) -> str:
    if isinstance(v, dict):
        return ", ".join(f"{k}: {val}" for k, val in v.items())
    if isinstance(v, list):
        return ", ".join(str(i) for i in v)
    return str(v)


class BrandProfile(BaseModel):
    tone: str
    values: list[str]
    audience: str
    preferred_style: str
    forbidden_words: list[str]
    differentiators: list[str]

    @field_validator("audience", "tone", "preferred_style", mode="before")
    @classmethod
    def str_fields(cls, v: Any) -> str:
        return _to_str(v)

    @field_validator("values", "forbidden_words", "differentiators", mode="before")
    @classmethod
    def list_fields(cls, v: Any) -> list[str]:
        return _flatten_list(v)


class CompetitorGapMap(BaseModel):
    competitors: list[str]
    common_claims: list[str]
    gaps: list[str]
    unique_angles: list[str]

    @field_validator("competitors", "common_claims", "gaps", "unique_angles", mode="before")
    @classmethod
    def list_fields(cls, v: Any) -> list[str]:
        return _flatten_list(v)


class ContentBrief(BaseModel):
    goal: str
    angle: str
    target_audience: str
    key_messages: list[str]
    gap_opportunities: list[str]

    @field_validator("target_audience", "goal", "angle", mode="before")
    @classmethod
    def str_fields(cls, v: Any) -> str:
        return _to_str(v)

    @field_validator("key_messages", "gap_opportunities", mode="before")
    @classmethod
    def list_fields(cls, v: Any) -> list[str]:
        return _flatten_list(v)


class ImageAsset(BaseModel):
    prompt: str                   # generation prompt sent to image model
    url: str = ""                 # filled once image is generated
    alt_text: str = ""
    model: str = ""               # e.g. "dall-e-3", "stable-diffusion-xl"


class VideoAsset(BaseModel):
    prompt: str                   # generation prompt sent to video model
    url: str = ""                 # filled once video is generated
    duration_seconds: int = 0
    model: str = ""               # e.g. "runway-gen3", "kling"


class ContentPiece(BaseModel):
    title: str
    headline: str         = ""
    sections: list[dict]  = []
    cta: str              = ""
    language: str         = "English"
    image_prompts: list[ImageAsset] = []
    video_prompts: list[VideoAsset] = []
    seo_title: str        = ""
    seo_description: str  = ""


class JudgeResult(BaseModel):
    score: int
    feedback: str
    details: dict = {}

    @field_validator("feedback", mode="before")
    @classmethod
    def str_field(cls, v: Any) -> str:
        return _to_str(v)


class EvaluationResult(BaseModel):
    customer: JudgeResult
    geo: JudgeResult
    competitor: JudgeResult
    naturalness: JudgeResult
    overall_score: int
    passed: bool


class PipelineOutput(BaseModel):
    content_en: ContentPiece
    content_fi: ContentPiece
    evaluation: EvaluationResult
    content_type: dict = {}
