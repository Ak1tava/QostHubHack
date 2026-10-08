from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.security import AuthError, get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import ErrorResponse
from app.modules.speech.audio import decode_audio, read_upload, validate_language
from app.modules.speech.provider import get_speech_provider
from app.modules.speech.schemas import SpeechTranscription

router = APIRouter(prefix="/speech", tags=["speech"])


def require_speech_actor(user: User = Depends(get_current_user)) -> User:
    if not user.is_active or user.role not in {"master", "worker"}:
        raise AuthError(403, "forbidden", "Действие недоступно")
    return user


def require_speech_language(language: str = Form(..., json_schema_extra={"enum": ["ru"]}),
                            actor: User = Depends(require_speech_actor)) -> str:
    return validate_language(language)


@router.post("/transcriptions", response_model=SpeechTranscription,
             responses={code: {"model": ErrorResponse} for code in (401, 403, 413, 415, 422, 429, 503)})
async def transcribe(response: Response, file: UploadFile = File(...),
                     language: str = Depends(require_speech_language),
                     actor: User = Depends(require_speech_actor),
                     provider=Depends(get_speech_provider)):
    content, mime = await read_upload(file, language)
    decoded = await run_in_threadpool(decode_audio, content, mime)
    # The API owns validation and duration; the model's metadata is not authoritative.
    duration = decoded.duration_seconds
    del decoded
    result = await provider.transcribe(content, mime, language)
    response.headers["Cache-Control"] = "no-store"
    return result.model_copy(update={"duration_seconds": duration})
