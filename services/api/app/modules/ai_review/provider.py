from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from io import BytesIO
from time import monotonic
from typing import Protocol

from pydantic import ValidationError

from .prompts import SYSTEM_PROMPT, prompt_payload
from .schemas import ImageEvidence, ProviderOutcome, ReviewInput, StagePlan, StageResponse

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_COUNT = 20


class ReviewProvider(Protocol):
    def review(self, value: ReviewInput, plan: StagePlan, *, images: dict[str, ImageEvidence],
               previous: ProviderOutcome | None = None) -> ProviderOutcome: ...


def image_data_url(image: ImageEvidence) -> str:
    from PIL import Image

    if not image.data or len(image.data) > MAX_IMAGE_BYTES:
        raise ValueError('Image size outside allowed range')
    with Image.open(BytesIO(image.data)) as decoded:
        actual_type = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}.get(decoded.format)
        if actual_type != image.media_type or decoded.width * decoded.height > 40_000_000:
            raise ValueError('Image format or dimensions invalid')
        decoded.verify()
    return f'data:{image.media_type};base64,{base64.b64encode(image.data).decode("ascii")}'


def request_content(value: ReviewInput, plan: StagePlan, images: dict[str, ImageEvidence], previous=None) -> list[dict]:
    if len(value.photo_refs) > MAX_IMAGE_COUNT:
        raise ValueError('Too many images')
    content = [{'type': 'input_text', 'text': prompt_payload(value, plan, previous)}]
    for photo in value.photo_refs:
        ref = photo['id']
        if ref not in images:
            raise KeyError(ref)
        content.extend([{'type': 'input_text', 'text': f'Изображение с evidence_ref={ref}'},
                        {'type': 'input_image', 'image_url': image_data_url(images[ref]), 'detail': 'high'}])
    return content


def usage_metadata(response) -> dict[str, int]:
    def read(obj, key, default=None):
        return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

    source = read(response, 'usage')
    if source is None:
        return {}
    result = {key: int(read(source, key, 0) or 0) for key in ('input_tokens', 'output_tokens', 'total_tokens')}
    result['cached_tokens'] = int(read(read(source, 'input_tokens_details'), 'cached_tokens', 0) or 0)
    result['reasoning_tokens'] = int(read(read(source, 'output_tokens_details'), 'reasoning_tokens', 0) or 0)
    return result


def retry_after(error) -> float | None:
    response = getattr(error, 'response', None)
    raw = response.headers.get('retry-after') if response is not None else None
    if not raw:
        return None
    try:
        return max(0.0, min(3600.0, float(raw)))
    except ValueError:
        try:
            return max(0.0, min(3600.0, (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError):
            return None


class OpenAIReviewProvider:
    def __init__(self, api_key: str, timeout: float = 90, max_output_tokens: int = 4096,
                 complex_max_output_tokens: int = 8192, *, client=None):
        if not api_key.strip():
            raise ValueError('OpenAI API key required')
        if not 1 <= max_output_tokens <= 32768 or not 1 <= complex_max_output_tokens <= 32768:
            raise ValueError('Output cap must be bounded')
        self.max_output_tokens = max_output_tokens
        self.complex_max_output_tokens = complex_max_output_tokens
        self.timeout = timeout
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0)
        self.client = client

    def review(self, value: ReviewInput, plan: StagePlan, *, images: dict[str, ImageEvidence],
               previous: ProviderOutcome | None = None) -> ProviderOutcome:
        import openai

        started = monotonic()
        try:
            content = request_content(value, plan, images, previous)
        except KeyError:
            return ProviderOutcome(error_code='image_unavailable')
        except (ValueError, OSError):
            return ProviderOutcome(error_code='invalid_image')
        raw_metadata = {}
        try:
            resource = self.client.responses
            raw_resource = getattr(resource, 'with_raw_response', None)
            response = (raw_resource or resource).parse(
                model=plan.model, instructions=SYSTEM_PROMPT,
                input=[{'role': 'user', 'content': content}], text_format=StageResponse,
                reasoning={'effort': plan.reasoning}, store=False, timeout=self.timeout, service_tier='default',
                max_output_tokens=self.complex_max_output_tokens if plan.stage == 'escalation' else self.max_output_tokens,
            )
            if raw_resource is not None:
                raw = getattr(response, 'http_response', response).json()
                raw_metadata = dict(usage=usage_metadata(raw), response_id=raw.get('id'))
                raw_metadata['latency_ms'] = int((monotonic() - started) * 1000)
                if any(part.get('type') == 'refusal' for item in raw.get('output', []) for part in item.get('content', [])):
                    return ProviderOutcome(error_code='refusal', **raw_metadata)
                if raw.get('status', 'completed') != 'completed':
                    return ProviderOutcome(error_code='incomplete', **raw_metadata)
                raw_metadata.pop('latency_ms')
                response = response.parse()
        except (ValidationError, ValueError, openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError):
            return ProviderOutcome(error_code='schema_error', latency_ms=int((monotonic() - started) * 1000), **raw_metadata)
        except openai.APIError as error:
            status = getattr(error, 'status_code', None)
            transient = isinstance(error, (openai.APIConnectionError, openai.APITimeoutError)) or status == 429 or (status is not None and status >= 500)
            return ProviderOutcome(error_code='api_error', retryable=transient, retry_after_seconds=retry_after(error),
                                   latency_ms=int((monotonic() - started) * 1000))
        metadata = dict(usage=usage_metadata(response), response_id=getattr(response, 'id', None),
                        latency_ms=int((monotonic() - started) * 1000))
        if any(getattr(part, 'type', None) == 'refusal' for item in getattr(response, 'output', []) for part in getattr(item, 'content', [])):
            return ProviderOutcome(error_code='refusal', **metadata)
        if getattr(response, 'status', None) != 'completed':
            return ProviderOutcome(error_code='incomplete', **metadata)
        try:
            parsed = StageResponse.model_validate(getattr(response, 'output_parsed', None))
        except ValidationError:
            return ProviderOutcome(error_code='schema_error', **metadata)
        if not set(parsed.legible_refs) <= {p['id'] for p in value.photo_refs} & set(images):
            return ProviderOutcome(error_code='invalid_provider_evidence', **metadata)
        return ProviderOutcome(result=parsed.result, unresolved_conflict=parsed.unresolved_conflict,
                               conflict_refs=parsed.conflict_refs, legible_refs=parsed.legible_refs, **metadata)
