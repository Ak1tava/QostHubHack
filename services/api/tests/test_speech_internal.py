import importlib
import io
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from test_speech import wav_audio


def load_internal():
    try:
        return importlib.import_module('app.modules.speech.internal')
    except ModuleNotFoundError as exc:
        if exc.name == 'app.modules.speech.internal':
            pytest.fail('ASR internal service is missing')
        raise


def test_internal_requires_bearer_before_inference(speech_directory):
    module = load_internal()
    config = SimpleNamespace(speech_service_token=SecretStr('private-test-token'), speech_model_path=speech_directory,
        speech_device='cpu', speech_compute_type='int8')
    with TestClient(module.create_app(config)) as client:
        for headers in ({}, {'Authorization': 'Bearer wrong'}):
            response = client.post('/transcribe', files={'file': ('a.wav', wav_audio(), 'audio/wav')},
                data={'language': 'ru'}, headers=headers)
            assert response.status_code == 401
            assert 'private-test-token' not in response.text


def test_internal_missing_local_model_returns_503(speech_directory):
    module = load_internal()
    config = SimpleNamespace(speech_service_token=SecretStr('private-test-token'), speech_model_path=speech_directory / 'missing',
        speech_device='cpu', speech_compute_type='int8')
    with TestClient(module.create_app(config)) as client:
        assert client.get('/health/ready').status_code == 503
        response = client.post('/transcribe', files={'file': ('a.wav', wav_audio(), 'audio/wav')},
            data={'language': 'ru'}, headers={'Authorization': 'Bearer private-test-token'})
        assert response.status_code == 503
        assert str(speech_directory) not in response.text


def test_inference_busy_rejects_second_call_without_queue():
    module = load_internal()
    service = module.LocalWhisperService(SimpleNamespace())
    service._gate.acquire()
    try:
        with pytest.raises(Exception) as exc:
            service.transcribe(wav_audio(), 'audio/wav', 'ru')
        assert exc.value.status_code == 429
    finally:
        service._gate.release()


def test_upload_is_closed_even_on_rejection():
    import asyncio
    from fastapi import UploadFile
    from starlette.datastructures import Headers
    from app.modules.speech.audio import read_upload
    file = UploadFile(io.BytesIO(b'invalid'), headers=Headers({'content-type': 'text/plain'}))
    with pytest.raises(Exception) as exc:
        asyncio.run(read_upload(file, 'ru'))
    assert exc.value.status_code == 415
    assert file.file.closed


@pytest.mark.parametrize('status,body,want', [
    (429, {'error': {'code': 'private-error', 'message': 'secret path'}}, 429),
    (500, {'error': {'message': 'secret path'}}, 503),
    (422, {'error': {'code': 'speech_no_speech', 'message': 'secret path'}}, 422),
    (200, {'text': 'ok', 'language': 'kk', 'model': 'large-v3-turbo', 'duration_seconds': 1, 'is_mock': False}, 503),
])
def test_http_provider_returns_safe_errors_without_retry(status, body, want):
    import asyncio
    from app.modules.speech.provider import HttpSpeechProvider
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    provider = HttpSpeechProvider('http://asr', 'private-test-token', transport=httpx.MockTransport(handler))
    with pytest.raises(Exception) as exc:
        asyncio.run(provider.transcribe(wav_audio(), 'audio/wav', 'ru'))
    assert exc.value.status_code == want
    assert 'secret path' not in exc.value.message
    assert len(requests) == 1


def test_http_timeout_is_safe():
    import asyncio
    from app.modules.speech.provider import HttpSpeechProvider
    def handler(request):
        raise httpx.ReadTimeout('secret path')
    provider = HttpSpeechProvider('http://asr', 'private-test-token', transport=httpx.MockTransport(handler))
    with pytest.raises(Exception) as exc:
        asyncio.run(provider.transcribe(wav_audio(), 'audio/wav', 'ru'))
    assert exc.value.status_code == 503
    assert 'secret path' not in exc.value.message

@pytest.fixture
def speech_directory():
    from uuid import uuid4
    directory = Path(__file__).resolve().parents[3] / '.tooling' / 't13-t16' / ('speech-' + uuid4().hex)
    directory.mkdir(parents=True)
    return directory


def test_partial_model_cannot_trigger_tokenizer_network_download(speech_directory):
    module = load_internal()
    for name in ('model.bin', 'config.json'):
        (speech_directory / name).write_text('{}')
    config = SimpleNamespace(speech_model_path=speech_directory)
    assert module.LocalWhisperService(config).ready() is False


def test_internal_missing_fields_follow_error_contract(speech_directory):
    module = load_internal()
    config = SimpleNamespace(speech_service_token=SecretStr('private-test-token'), speech_model_path=speech_directory,
        speech_device='cpu', speech_compute_type='int8')
    with TestClient(module.create_app(config)) as client:
        response = client.post('/transcribe', headers={'Authorization': 'Bearer private-test-token'})
        assert response.status_code == 422
        assert response.json()['error']['code'] == 'validation_error'
        assert response.headers['cache-control'] == 'no-store'


def test_local_model_iterates_lazy_segments_and_reuses_loaded_model(speech_directory, monkeypatch):
    module = load_internal()
    for name in ('model.bin', 'config.json', 'tokenizer.json'):
        (speech_directory / name).write_text('{}')
    import faster_whisper
    loads = []
    class Model:
        def __init__(self, path, **kwargs):
            assert path == str(speech_directory)
            assert kwargs['local_files_only'] is True
            loads.append(path)
        def transcribe(self, audio, **kwargs):
            assert kwargs['language'] == 'ru'
            assert kwargs['task'] == 'transcribe'
            def segments():
                yield SimpleNamespace(text=' Насос ')
                yield SimpleNamespace(text=' жөнделді ')
            return segments(), SimpleNamespace(language=kwargs['language'])
    monkeypatch.setattr(faster_whisper, 'WhisperModel', Model)
    service = module.LocalWhisperService(SimpleNamespace(speech_model_path=speech_directory,
        speech_device='cpu', speech_compute_type='int8'))
    for language in ('ru', 'ru'):
        result = service.transcribe(wav_audio(), 'audio/wav', language)
        assert result.text == 'Насос жөнделді'
        assert result.language == language
        assert result.is_mock is False
    assert len(loads) == 1


@pytest.mark.parametrize('mode,status', [('empty', 422), ('error', 503)])
def test_lazy_inference_failure_is_safe_and_releases_gate(mode, status):
    module = load_internal()
    class Model:
        def transcribe(self, audio, **kwargs):
            def segments():
                if mode == 'error':
                    raise RuntimeError('private local model path')
                yield from ()
            return segments(), SimpleNamespace()
    service = module.LocalWhisperService(SimpleNamespace())
    service._model = Model()
    with pytest.raises(Exception) as exc:
        service.transcribe(wav_audio(), 'audio/wav', 'ru')
    assert exc.value.status_code == status
    assert 'private local model path' not in exc.value.message
    assert service._gate.acquire(blocking=False)
    service._gate.release()

def test_cancelled_upload_closes_temporary_file():
    import asyncio
    from fastapi import UploadFile
    from starlette.datastructures import Headers
    from app.modules.speech.audio import read_upload
    file = UploadFile(io.BytesIO(wav_audio()), headers=Headers({'content-type': 'audio/wav'}))
    async def cancelled_read(size):
        raise asyncio.CancelledError()
    file.read = cancelled_read
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(read_upload(file, 'ru'))
    assert file.file.closed


def test_running_inference_returns_busy_then_allows_next_request():
    from concurrent.futures import ThreadPoolExecutor
    module = load_internal()
    started = threading.Event()
    release = threading.Event()
    class Model:
        def transcribe(self, audio, **kwargs):
            def segments():
                started.set()
                assert release.wait(3)
                yield SimpleNamespace(text='ремонт')
            return segments(), SimpleNamespace()
    service = module.LocalWhisperService(SimpleNamespace())
    service._model = Model()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.transcribe, wav_audio(), 'audio/wav', 'ru')
        try:
            assert started.wait(3)
            second = pool.submit(service.transcribe, wav_audio(), 'audio/wav', 'ru')
            with pytest.raises(Exception) as exc:
                second.result(timeout=3)
            assert exc.value.status_code == 429
        finally:
            release.set()
        assert first.result(timeout=3).text == 'ремонт'
        assert service.transcribe(wav_audio(), 'audio/wav', 'ru').language == 'ru'


@pytest.mark.parametrize('container,codec,mime', [
    ('webm', 'libopus', 'audio/webm'), ('ogg', 'libopus', 'audio/ogg'),
    ('mp3', 'libmp3lame', 'audio/mpeg'), ('mp4', 'aac', 'audio/mp4'),
])
def test_real_browser_audio_containers_are_decoded(container, codec, mime):
    import av
    import numpy as np
    from app.modules.speech.audio import decode_audio
    output = io.BytesIO()
    options = {'movflags': 'frag_keyframe+empty_moov'} if container == 'mp4' else {}
    with av.open(output, 'w', format=container, options=options) as target:
        stream = target.add_stream(codec, rate=48000)
        stream.layout = 'mono'
        frame = av.AudioFrame.from_ndarray(np.zeros((1, 4800), dtype=np.float32), format='flt', layout='mono')
        frame.sample_rate = 48000
        for packet in stream.encode(frame):
            target.mux(packet)
        for packet in stream.encode(None):
            target.mux(packet)
    decoded = decode_audio(output.getvalue(), mime)
    assert 0.08 <= decoded.duration_seconds <= 0.2
    assert len(decoded.samples) >= 1280


def test_sixty_seconds_boundary_is_accepted():
    from app.modules.speech.audio import decode_audio
    decoded = decode_audio(wav_audio(60), 'audio/wav')
    assert decoded.duration_seconds == 60

def test_cancelling_internal_request_keeps_inference_gate_until_worker_finishes():
    import asyncio
    from starlette.concurrency import run_in_threadpool
    module = load_internal()
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    class Model:
        def transcribe(self, audio, **kwargs):
            def segments():
                started.set()
                assert release.wait(3)
                try:
                    yield SimpleNamespace(text='ремонт')
                finally:
                    finished.set()
            return segments(), SimpleNamespace()
    service = module.LocalWhisperService(SimpleNamespace())
    service._model = Model()
    async def scenario():
        pending = asyncio.create_task(run_in_threadpool(service.transcribe, wav_audio(), 'audio/wav', 'ru'))
        try:
            assert await asyncio.to_thread(started.wait, 3)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            with pytest.raises(Exception) as exc:
                service.transcribe(wav_audio(), 'audio/wav', 'ru')
            assert exc.value.status_code == 429
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 3)
    asyncio.run(scenario())


def test_http_provider_round_trip_auth_and_internal_contract(speech_directory):
    import asyncio
    from app.modules.speech.provider import HttpSpeechProvider
    module = load_internal()
    config = SimpleNamespace(speech_service_token=SecretStr('private-test-token'), speech_model_path=speech_directory,
        speech_device='cpu', speech_compute_type='int8')
    application = module.create_app(config)
    class Model:
        def transcribe(self, audio, **kwargs):
            return iter([SimpleNamespace(text='Құбыр жөнделді')]), SimpleNamespace()
    application.state.speech_service._model = Model()
    provider = HttpSpeechProvider('http://asr', 'private-test-token', transport=httpx.ASGITransport(app=application))
    result = asyncio.run(provider.transcribe(wav_audio(), 'audio/wav', 'ru'))
    assert result.text == 'Құбыр жөнделді'
    assert result.language == 'ru'
    assert result.model == 'large-v3-turbo'
    assert result.duration_seconds == 0.1
    assert result.is_mock is False


@pytest.mark.parametrize('language', ['kk', 'en'])
def test_internal_rejects_other_languages_without_loading_model(language):
    module = load_internal()
    config = SimpleNamespace(speech_service_token=SecretStr('test-only'), speech_model_path=None)
    application = module.create_app(config)
    def load_model():
        raise AssertionError('Model must not load')
    application.state.speech_service._load_model = load_model
    with TestClient(application) as client:
        response = client.post('/transcribe', files={'file': ('a.wav', wav_audio(), 'audio/wav')},
            data={'language': language}, headers={'Authorization': 'Bearer test-only'})
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'speech_invalid_language'


def test_response_cannot_claim_kazakh_transcription():
    from pydantic import ValidationError
    from app.modules.speech.schemas import SpeechTranscription
    with pytest.raises(ValidationError):
        SpeechTranscription(text='ремонт', language='kk', duration_seconds=1)


@pytest.mark.parametrize('language', ['kk', 'en'])
def test_http_provider_rejects_other_languages_without_transport(language):
    import asyncio
    from app.modules.speech.provider import HttpSpeechProvider
    def handler(request):
        return httpx.Response(503)
    provider = HttpSpeechProvider('http://asr', 'test-only', transport=httpx.MockTransport(handler))
    with pytest.raises(Exception) as exc:
        asyncio.run(provider.transcribe(wav_audio(), 'audio/wav', language))
    assert exc.value.status_code == 422
    assert exc.value.code == 'speech_invalid_language'


@pytest.mark.parametrize('language', ['kk', 'en'])
def test_synthetic_http_fixture_rejects_other_languages(language, monkeypatch):
    import importlib.util
    path = Path(__file__).resolve().parents[3] / 'infra' / 'fake_speech_service.py'
    spec = importlib.util.spec_from_file_location('fake_speech_fixture', path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    monkeypatch.setenv('SPEECH_SERVICE_TOKEN', 'test-only')
    with TestClient(fixture.app) as client:
        response = client.post('/transcribe', files={'file': ('a.wav', wav_audio(), 'audio/wav')},
            data={'language': language}, headers={'Authorization': 'Bearer test-only'})
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'speech_invalid_language'

def test_playlist_disguised_as_audio_cannot_fetch_external_url():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from app.modules.speech.audio import decode_audio
    contacted = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            contacted.set()
            self.send_response(200)
            self.send_header('Content-Length', str(len(wav_audio())))
            self.end_headers()
            self.wfile.write(wav_audio())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        playlist = ('#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:0\n'
            '#EXTINF:1,\nhttp://127.0.0.1:' + str(server.server_port) + '/audio.ts\n#EXT-X-ENDLIST\n').encode()
        with pytest.raises(Exception):
            decode_audio(playlist, 'audio/wav')
        assert not contacted.is_set(), 'Decoder fetched a URL embedded in the upload'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

@pytest.mark.parametrize('token', [None, SecretStr('')], ids=['absent', 'empty'])
def test_ready_without_bearer_configuration_returns_unavailable(speech_directory, token):
    module = load_internal()
    for name in ('model.bin', 'config.json', 'tokenizer.json'):
        (speech_directory / name).write_text('{}')
    config = SimpleNamespace(speech_service_token=token, speech_model_path=speech_directory,
        speech_device='cpu', speech_compute_type='int8')
    with TestClient(module.create_app(config)) as client:
        response = client.get('/health/ready')
        assert response.status_code == 503
        assert response.json()['error']['code'] == 'speech_unavailable'

def test_prepare_model_download_is_pinned_to_verified_revision(speech_directory, monkeypatch, capsys):
    import sys
    import huggingface_hub
    from app.modules.speech.prepare_model import main
    def download(**kwargs):
        assert kwargs['repo_id'] == 'mobiuslabsgmbh/faster-whisper-large-v3-turbo'
        assert kwargs.get('revision') == '0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf'
        Path(kwargs['local_dir'], 'model.bin').write_bytes(b'prepared')
    monkeypatch.setattr(huggingface_hub, 'snapshot_download', download)
    monkeypatch.setattr(sys, 'argv', ['prepare_model', '--output', str(speech_directory)])
    main()
    assert (speech_directory / 'model.bin').read_bytes() == b'prepared'
    assert str(speech_directory) not in capsys.readouterr().out

@pytest.mark.parametrize('seconds,accepted', [(59, True), (60, False)], ids=['59s-with-padding', '60s-padding-over-limit'])
def test_fragmented_mp4_aac_duration_uses_decoded_samples(seconds, accepted):
    import av
    import numpy as np
    from app.core.security import AuthError
    from app.modules.speech.audio import decode_audio
    output = io.BytesIO()
    with av.open(output, 'w', format='mp4', options={'movflags': 'frag_keyframe+empty_moov'}) as target:
        stream = target.add_stream('aac', rate=48000)
        stream.layout = 'mono'
        frame = av.AudioFrame.from_ndarray(np.zeros((1, seconds * 48000), dtype=np.float32),
            format='flt', layout='mono')
        frame.sample_rate = 48000
        for packet in stream.encode(frame):
            target.mux(packet)
        for packet in stream.encode(None):
            target.mux(packet)
    content = output.getvalue()
    assert len(content) < 100_000, 'The regression fixture should remain a small encoded upload'
    if accepted:
        decoded = decode_audio(content, 'audio/mp4')
        assert 59 <= decoded.duration_seconds <= 60
    else:
        # Fragmented AAC carries encoder padding beyond exactly sixty seconds;
        # the server limit applies to the actual decoded samples, not the input frame.
        with pytest.raises(AuthError) as exc:
            decode_audio(content, 'audio/mp4')
        assert exc.value.status_code == 422
        assert exc.value.code == 'speech_audio_too_long'
