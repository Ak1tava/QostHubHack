import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.core.security import AuthError
from app.modules.speech.audio import validate_language
from app.modules.speech.schemas import SpeechTranscription


def unavailable() -> AuthError:
    return AuthError(503, "speech_unavailable", "Распознавание речи временно недоступно")


class HttpSpeechProvider:
    def __init__(self, url: str, token: str, timeout: float = 90,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.url, self.token, self.timeout, self.transport = url, token, timeout, transport

    async def transcribe(self, content: bytes, content_type: str, language: str) -> SpeechTranscription:
        validate_language(language)
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport,
                                         follow_redirects=False, trust_env=False) as client:
                response = await client.post(self.url.rstrip("/") + "/transcribe",
                    headers={"Authorization": "Bearer " + self.token},
                    files={"file": ("audio", content, content_type)}, data={"language": language})
            if response.status_code == 429:
                raise AuthError(429, "speech_busy", "Распознавание занято. Повторите позже", retry_after=5)
            if response.status_code == 422:
                code = response.json().get("error", {}).get("code")
                if code == "speech_no_speech":
                    raise AuthError(422, "speech_no_speech", "Речь не найдена. Попробуйте другую запись")
                raise unavailable()
            if response.status_code != 200:
                raise unavailable()
            result = SpeechTranscription.model_validate(response.json())
            if result.language != language or not result.text.strip():
                raise unavailable()
            return result
        except AuthError:
            raise
        except (httpx.HTTPError, ValidationError, ValueError, TypeError, AttributeError):
            raise unavailable() from None


def get_speech_provider() -> HttpSpeechProvider:
    url, token = settings.speech_service_url, settings.speech_service_token
    if not url or not token or not token.get_secret_value():
        raise unavailable()
    return HttpSpeechProvider(url, token.get_secret_value(), settings.speech_request_timeout_seconds)
