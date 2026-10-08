"""Run separately: uvicorn app.modules.speech.internal:app --host 127.0.0.1 --port 8016."""

import hmac
import importlib.util
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.security import AuthError
from app.modules.auth.router import register_auth_handlers
from app.modules.auth.schemas import ErrorResponse
from app.modules.speech.audio import decode_audio, read_upload, validate_language, validate_mime
from app.modules.speech.provider import unavailable
from app.modules.speech.schemas import SpeechTranscription


class LocalWhisperService:
    def __init__(self, config):
        self.config = config
        self._model = None
        self._gate = threading.Lock()

    def ready(self) -> bool:
        path = self.config.speech_model_path
        return bool(path and Path(path).is_dir()
                    and (Path(path) / "model.bin").is_file()
                    and (Path(path) / "config.json").is_file()
                    # faster-whisper otherwise calls Tokenizer.from_pretrained over the network.
                    and (Path(path) / "tokenizer.json").is_file()
                    and importlib.util.find_spec("faster_whisper"))

    def _load_model(self):
        if self._model is None:
            if not self.ready():
                raise unavailable()
            from faster_whisper import WhisperModel
            self._model = WhisperModel(str(self.config.speech_model_path),
                device=self.config.speech_device, compute_type=self.config.speech_compute_type,
                local_files_only=True)
        return self._model

    def transcribe(self, content: bytes, mime: str, language: str) -> SpeechTranscription:
        if not self._gate.acquire(blocking=False):
            raise AuthError(429, "speech_busy", "Распознавание занято. Повторите позже", retry_after=5)
        try:
            validate_language(language)
            validate_mime(mime)
            model = self._load_model()
            decoded = decode_audio(content, mime)
            segments, _info = model.transcribe(decoded.samples, language=language,
                task="transcribe", beam_size=1, vad_filter=True, condition_on_previous_text=False)
            # faster-whisper segments are lazy: inference and errors occur while iterating.
            text = " ".join(segment.text.strip() for segment in segments).strip()
            if not text:
                raise AuthError(422, "speech_no_speech", "Речь не найдена. Попробуйте другую запись")
            return SpeechTranscription(text=text, language=language,
                duration_seconds=decoded.duration_seconds, is_mock=False)
        except AuthError:
            raise
        except Exception:
            raise unavailable() from None
        finally:
            # Owned by this worker, so client cancellation never unlocks an active inference.
            self._gate.release()


def create_app(config=settings) -> FastAPI:
    application = FastAPI(title="QostHub local ASR", docs_url=None, redoc_url=None,
                          openapi_url=None)
    register_auth_handlers(application)
    @application.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(status_code=422, headers={"Cache-Control": "no-store"},
            content={"error": {"code": "validation_error", "message": "Проверьте введённые данные",
                               "details": []}})
    service = LocalWhisperService(config)
    application.state.speech_service = service

    def authorize(authorization: str | None = Header(default=None)):
        secret = config.speech_service_token
        token = secret.get_secret_value() if secret else ""
        if not token:
            raise unavailable()
        supplied = (authorization or "").encode("utf-8")
        if not hmac.compare_digest(supplied, ("Bearer " + token).encode("utf-8")):
            raise AuthError(401, "unauthenticated", "Требуется авторизация")

    @application.get("/health/ready")
    def ready(response: Response):
        response.headers["Cache-Control"] = "no-store"
        token = config.speech_service_token
        if not token or not token.get_secret_value() or not service.ready():
            raise unavailable()
        return {"status": "ready", "model": "large-v3-turbo"}

    @application.post("/transcribe", response_model=SpeechTranscription,
                      responses={code: {"model": ErrorResponse} for code in (401, 413, 415, 422, 429, 503)},
                      dependencies=[Depends(authorize)])
    async def transcribe(response: Response, file: UploadFile = File(...),
                         language: str = Form(..., json_schema_extra={"enum": ["ru", "kk"]})):
        content, mime = await read_upload(file, language)
        result = await run_in_threadpool(service.transcribe, content, mime, language)
        response.headers["Cache-Control"] = "no-store"
        return result

    return application


app = create_app()
