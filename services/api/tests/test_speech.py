import io
import wave
from importlib import import_module
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.modules.auth.router import register_auth_handlers


def wav_audio(seconds=0.1):
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b'\x01\x00' * int(seconds * 16000))
    return output.getvalue()


@pytest.fixture
def speech_client():
    app = FastAPI()
    register_auth_handlers(app)
    try:
        module = import_module('app.modules.speech.router')
    except ModuleNotFoundError as exc:
        if exc.name != 'app.modules.speech.router':
            raise
        module = None
    if module:
        app.include_router(module.router, prefix='/api/v1')
        from app.modules.speech.schemas import SpeechTranscription
        class Provider:
            async def transcribe(self, content, content_type, language):
                return SpeechTranscription(text='Насос жөнделді', language=language,
                    duration_seconds=0.1, is_mock=True)
        app.dependency_overrides[module.get_speech_provider] = Provider
    actor = SimpleNamespace(role='worker', is_active=True)
    app.dependency_overrides[get_current_user] = lambda: actor
    with TestClient(app) as client:
        yield client, actor


def post(client, content=None, mime='audio/wav', language='ru'):
    return client.post('/api/v1/speech/transcriptions',
        files={'file': ('recording.wav', wav_audio() if content is None else content, mime)},
        data={'language': language})


@pytest.mark.parametrize('language', ['ru', 'kk'])
def test_allowed_actor_gets_editable_transcription(speech_client, language):
    client, actor = speech_client
    response = post(client, language=language)
    assert response.status_code == 200, response.text
    assert response.json() == {'text': 'Насос жөнделді', 'language': language,
        'model': 'large-v3-turbo', 'duration_seconds': 0.1, 'is_mock': True}
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('role', ['manager', 'admin'])
def test_readonly_roles_cannot_use_speech(speech_client, role):
    client, actor = speech_client
    actor.role = role
    assert post(client).status_code == 403


@pytest.mark.parametrize('content,mime,language,status,code', [
    (b'', 'audio/wav', 'ru', 422, 'speech_empty_audio'),
    (b'not an audio container', 'audio/wav', 'ru', 422, 'speech_invalid_audio'),
    (b'123', 'image/png', 'ru', 415, 'speech_unsupported_format'),
    (b'123', 'audio/wav', 'en', 422, 'speech_invalid_language'),
    (b'x' * (10 * 1024 * 1024 + 1), 'audio/wav', 'ru', 413, 'speech_file_too_large'),
], ids=['empty', 'invalid', 'mime', 'language', 'size'])
def test_invalid_upload_has_safe_error(speech_client, content, mime, language, status, code):
    response = post(speech_client[0], content, mime, language)
    assert response.status_code == status, response.text
    assert response.json()['error']['code'] == code
    assert response.headers['cache-control'] == 'no-store'


def test_declared_mime_does_not_allow_another_real_container(speech_client):
    response = post(speech_client[0], wav_audio(), 'audio/ogg')
    assert response.status_code == 415


def test_codec_parameter_is_accepted(speech_client):
    assert post(speech_client[0], mime='audio/wav; codecs=pcm').status_code == 200


def test_long_decoded_audio_is_rejected(speech_client):
    response = post(speech_client[0], wav_audio(60.1))
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'speech_audio_too_long'


@pytest.fixture
def authenticated_speech_client(client, app):
    from app.modules.speech.router import get_speech_provider
    from app.modules.speech.schemas import SpeechTranscription
    class Provider:
        async def transcribe(self, content, content_type, language):
            return SpeechTranscription(text='ремонт', language=language, duration_seconds=0.1, is_mock=True)
    app.dependency_overrides[get_speech_provider] = Provider
    yield client


def test_real_anonymous_session_cannot_transcribe(authenticated_speech_client):
    response = post(authenticated_speech_client)
    assert response.status_code == 401
    assert response.json()['error']['code'] == 'unauthenticated'


@pytest.mark.parametrize('login', ['master', 'worker'])
def test_real_authenticated_roles_can_transcribe(authenticated_speech_client, login):
    from conftest import sign_in
    client = authenticated_speech_client
    token = sign_in(client, login)
    response = client.post('/api/v1/speech/transcriptions',
        files={'file': ('a.wav', wav_audio(), 'audio/wav')}, data={'language': 'kk'},
        headers={'Origin': 'http://localhost:5173', 'X-CSRF-Token': token})
    assert response.status_code == 200
    assert response.json()['language'] == 'kk'


@pytest.mark.parametrize('headers', [{}, {'Origin': 'https://attacker.invalid', 'X-CSRF-Token': 'bad'},
    {'Origin': 'http://localhost:5173', 'X-CSRF-Token': 'bad'}], ids=['missing','origin','token'])
def test_real_session_requires_csrf(authenticated_speech_client, headers):
    from conftest import sign_in
    client = authenticated_speech_client
    sign_in(client)
    response = client.post('/api/v1/speech/transcriptions',
        files={'file': ('a.wav', wav_audio(), 'audio/wav')}, data={'language': 'ru'}, headers=headers)
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'csrf_failed'


def test_missing_form_fields_have_safe_public_contract(authenticated_speech_client):
    from conftest import sign_in
    client = authenticated_speech_client
    token = sign_in(client)
    response = client.post('/api/v1/speech/transcriptions',
        headers={'Origin': 'http://localhost:5173', 'X-CSRF-Token': token})
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'validation_error'
    assert response.headers['cache-control'] == 'no-store'
