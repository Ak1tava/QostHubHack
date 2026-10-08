"""Bounded decoding of uploaded bytes; paths and URLs are never accepted."""

import io
from dataclasses import dataclass

from fastapi import UploadFile

from app.core.security import AuthError

MAX_BYTES = 10 * 1024 * 1024
MAX_SECONDS = 60
SAMPLE_RATE = 16_000
MIME_FORMATS = {
    "audio/webm": {"matroska", "webm"},
    "audio/mp4": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
    "audio/x-m4a": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
    "audio/mpeg": {"mp3"},
    "audio/wav": {"wav"},
    "audio/x-wav": {"wav"},
    "audio/ogg": {"ogg"},
}


def validate_language(language: str) -> str:
    if language != "ru":
        raise AuthError(422, "speech_invalid_language", "Распознавание доступно только на русском языке")
    return language


def validate_mime(content_type: str | None) -> str:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime not in MIME_FORMATS:
        raise AuthError(415, "speech_unsupported_format", "Формат аудио не поддерживается")
    return mime


async def read_upload(file: UploadFile, language: str) -> tuple[bytes, str]:
    try:
        validate_language(language)
        mime = validate_mime(file.content_type)
        content = await file.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise AuthError(413, "speech_file_too_large", "Аудио должно быть не больше 10 МБ")
        if not content:
            raise AuthError(422, "speech_empty_audio", "Аудиозапись пустая")
        return content, mime
    finally:
        await file.close()


@dataclass
class DecodedAudio:
    samples: object
    duration_seconds: float


def decode_audio(content: bytes, mime: str) -> DecodedAudio:
    try:
        import av
        import numpy as np
    except ImportError:
        raise AuthError(503, "speech_unavailable", "Распознавание речи временно недоступно") from None
    chunks = []
    count = 0
    try:
        # Custom byte IO is the sole source; embedded network/file references are forbidden.
        with av.open(io.BytesIO(content), mode="r", options={"protocol_whitelist": ""}) as container:
            if not set(container.format.name.split(",")) & MIME_FORMATS[mime]:
                raise AuthError(415, "speech_unsupported_format", "Содержимое не соответствует формату аудио")
            if not container.streams.audio or container.streams.video:
                raise AuthError(422, "speech_invalid_audio", "Не удалось прочитать аудиозапись")
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(stream):
                # Check before conversion too: one pathological frame cannot allocate unlimited output.
                if not frame.sample_rate or frame.samples / frame.sample_rate > MAX_SECONDS:
                    raise AuthError(422, "speech_audio_too_long", "Аудио должно быть не длиннее 60 секунд")
                for converted in resampler.resample(frame):
                    count += converted.samples
                    if count > MAX_SECONDS * SAMPLE_RATE:
                        raise AuthError(422, "speech_audio_too_long", "Аудио должно быть не длиннее 60 секунд")
                    chunks.append(converted.to_ndarray().reshape(-1))
            for converted in resampler.resample(None):
                count += converted.samples
                if count > MAX_SECONDS * SAMPLE_RATE:
                    raise AuthError(422, "speech_audio_too_long", "Аудио должно быть не длиннее 60 секунд")
                chunks.append(converted.to_ndarray().reshape(-1))
        if not count:
            raise AuthError(422, "speech_empty_audio", "Аудиозапись пустая")
        samples = np.concatenate(chunks).astype(np.float32) / 32768.0
        return DecodedAudio(samples=samples, duration_seconds=count / SAMPLE_RATE)
    except AuthError:
        raise
    except Exception:
        raise AuthError(422, "speech_invalid_audio", "Не удалось прочитать аудиозапись") from None
