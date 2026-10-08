"""Synthetic HTTP ASR fixture for disposable acceptance stacks only.

Run with access logs disabled; accepts in-memory synthetic PCM WAV only.
Never substitute this app for the production local Whisper service.
"""
import hmac
import io
import os
from pathlib import Path
import sys
import wave

from fastapi import FastAPI, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/api'))
from app.modules.speech.schemas import SpeechTranscription

app = FastAPI()
MAX_BYTES = 10 * 1024 * 1024


def failure(status: int, code: str, message: str):
    return JSONResponse({'error': {'code': code, 'message': message, 'details': []}}, status_code=status, headers={'Cache-Control': 'no-store'})


@app.get('/health/ready')
async def ready():
    configured = bool(os.environ.get('SPEECH_SERVICE_TOKEN'))
    return JSONResponse({'ready': configured, 'is_mock': True}, status_code=200 if configured else 503, headers={'Cache-Control': 'no-store'})


@app.post('/transcribe', response_model=SpeechTranscription)
async def transcribe(file: UploadFile = File(...), language: str = Form(...), authorization: str | None = Header(default=None)):
    try:
        token = os.environ.get('SPEECH_SERVICE_TOKEN', '')
        if not token or not authorization or not hmac.compare_digest(authorization, 'Bearer ' + token):
            return failure(403, 'forbidden', 'Synthetic fixture authentication required')
        if language != 'ru':
            return failure(422, 'speech_invalid_language', 'Only Russian speech is supported')
        if (file.content_type or '').split(';')[0].lower() not in ('audio/wav', 'audio/x-wav'):
            return failure(415, 'speech_unsupported_format', 'Synthetic fixture accepts PCM WAV')
        content = await file.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            return failure(413, 'speech_too_large', 'Audio exceeds limit')
        try:
            with wave.open(io.BytesIO(content), 'rb') as audio:
                duration = audio.getnframes() / audio.getframerate()
                if not 0 < duration <= 60 or audio.getsampwidth() != 2 or audio.getcomptype() != 'NONE':
                    return failure(422, 'speech_invalid_audio', 'Invalid synthetic audio')
                frames = audio.readframes(audio.getnframes())
        except (wave.Error, EOFError, ZeroDivisionError):
            return failure(422, 'speech_invalid_audio', 'Invalid synthetic audio')
        if not frames or not any(frames):
            return failure(422, 'speech_no_speech', 'Synthetic silence contains no speech')
        result = SpeechTranscription(text='Заменён подшипник',
                                     language='ru', duration_seconds=duration, is_mock=True)
        return JSONResponse(result.model_dump(), headers={'Cache-Control': 'no-store'})
    finally:
        await file.close()
