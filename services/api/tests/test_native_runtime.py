"""Native lifecycle safety, with no real processes, network or paid I/O."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]


def runtime():
    path = ROOT / 'infra/native_runtime.py'
    assert path.is_file(), 'Native runtime launcher is missing'
    spec = importlib.util.spec_from_file_location('native_runtime', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeProcesses:
    def __init__(self):
        self.running, self.started, self.stopped = {}, [], []
        self.occupied, self.fail_ready = set(), None
        self.next_pid = 100

    def identity(self, pid):
        return self.running.get(pid)

    def free(self, port):
        if port in self.occupied:
            raise RuntimeError('Port occupied')

    def spawn(self, name, command, cwd, env, log):
        self.next_pid += 1
        record = {'pid': self.next_pid, 'created': str(self.next_pid), 'exe': command[0]}
        self.running[record['pid']] = record
        self.started.append((name, command, dict(env)))
        return record

    def postgres_start(self, config, env, log):
        return self.spawn('db', [config['postgres_bin'] + '/postgres.exe'], '', env, log)

    def wait(self, name, config, env):
        if name == self.fail_ready:
            raise RuntimeError('Not ready')
        if name in ('notifications', 'reviews'):
            record = json.loads((Path(config['state_dir']) / 'processes.json').read_text())[name]
            (Path(config['state_dir']) / f'{name}.ready.json').write_text(json.dumps({
                'pid': record['identity']['pid'], 'token': record['readiness_token'], 'service': name}))

    def stop(self, name, record, config):
        assert self.identity(record['pid']) == record
        self.stopped.append(name)
        self.running.pop(record['pid'])


@pytest.fixture
def configuration(tmp_path):
    repo = tmp_path / 'repo'
    (repo / 'apps/web/dist').mkdir(parents=True)
    (repo / 'apps/web/dist/index.html').write_text('synthetic')
    (repo / 'services/api').mkdir(parents=True)
    (repo / 'infra').mkdir()
    (repo / 'infra/nginx.tunnel.conf.template').write_bytes(
        (ROOT / 'infra/nginx.tunnel.conf.template').read_bytes())
    model = tmp_path / 'large-v3-turbo'
    model.mkdir()
    for name in ('model.bin', 'config.json', 'tokenizer.json'):
        (model / name).write_text('{}')
    pg = tmp_path / 'pg'
    pg.mkdir()
    for name in ('postgres.exe', 'pg_ctl.exe', 'pg_isready.exe'):
        (pg / name).touch()
    pgdata = tmp_path / 'pgdata'
    pgdata.mkdir()
    (pgdata / 'PG_VERSION').write_text('17')
    nginx = tmp_path / 'nginx.exe'
    nginx.touch()
    mime = tmp_path / 'mime.types'
    mime.touch()
    python = tmp_path / 'python.exe'
    python.touch()
    tunnel = tmp_path / 'cloudflared.exe'
    tunnel.touch()
    photos = tmp_path / 'photos'
    photos.mkdir()
    env = tmp_path / 'environment.json'
    env.write_text(json.dumps({'DATABASE_URL': 'postgresql://synthetic@127.0.0.1:55486/demo',
        'SESSION_SECRET': 'synthetic', 'SESSION_COOKIE_SECURE': 'true',
        'PUBLIC_BASE_URL': 'https://synthetic.trycloudflare.com',
        'OPENAI_API_KEY': 'synthetic-secret', 'TELEGRAM_BOT_TOKEN': 'synthetic-token',
        'SPEECH_SERVICE_TOKEN': 'synthetic-asr'}))
    ledger = tmp_path / 'budget'
    ledger.mkdir()
    (ledger / 'budget.json').write_text(json.dumps({'limit_usd': '10',
        'spent_or_reserved_usd': '0.02', 'calls': []}))
    (ledger / 'frozen.json').write_text('{}')
    config = dict(repo=str(repo), state_dir=str(tmp_path / 'state'), env_file=str(env),
        python=str(python), postgres_bin=str(pg), postgres_data=str(pgdata),
        postgres_port=55486, api_port=8036, web_port=5214, asr_port=8016,
        nginx=str(nginx), nginx_mime_types=str(mime), model_path=str(model),
        photo_path=str(photos), ledger=str(ledger / 'budget.json'), cloudflared=str(tunnel))
    return config


def test_start_is_idempotent_and_secrets_stay_out_of_unpaid_processes(configuration):
    module, backend = runtime(), FakeProcesses()
    control = module.Controller(configuration, backend)
    control.start()
    control.start()
    assert [x[0] for x in backend.started] == ['db', 'asr', 'api', 'nginx']
    assert all(not env.get('OPENAI_API_KEY') for _, _, env in backend.started)
    assert all(not env.get('TELEGRAM_BOT_TOKEN') for _, _, env in backend.started)
    assert set(control.status().values()) == {'running'}
    assert 'synthetic-secret' not in control.state_file.read_text()


def test_stop_never_kills_reused_pid(configuration):
    module, backend = runtime(), FakeProcesses()
    control = module.Controller(configuration, backend)
    control.start()
    state = json.loads(control.state_file.read_text())
    old = state['api']['identity']
    backend.running[old['pid']] = {**old, 'created': 'other-process'}
    assert control.status()['api'] == 'stale'
    control.stop()
    assert backend.running[old['pid']]['created'] == 'other-process'
    assert backend.stopped == ['nginx', 'asr', 'db']


def test_missing_identity_does_not_count_as_owned(configuration):
    module, backend = runtime(), FakeProcesses()
    control = module.Controller(configuration, backend)
    control.state_dir.mkdir()
    control.state_file.write_text(json.dumps({'api': {'identity': None}}))
    assert control.status()['api'] == 'stale'
    control.stop()
    assert not backend.stopped


def test_occupied_port_refused_before_any_start(configuration):
    module, backend = runtime(), FakeProcesses()
    backend.occupied.add(configuration['api_port'])
    with pytest.raises(RuntimeError, match='occupied'):
        module.Controller(configuration, backend).start()
    assert not backend.started


def test_readiness_failure_rolls_back_only_new_processes(configuration):
    module, backend = runtime(), FakeProcesses()
    control = module.Controller(configuration, backend)
    control.start()
    state = json.loads(control.state_file.read_text())
    backend.running.pop(state['api']['identity']['pid'])
    backend.fail_ready = 'api'
    with pytest.raises(RuntimeError, match='ready'):
        control.start()
    assert backend.stopped == ['api']
    assert control.status()['db'] == 'running'


@pytest.mark.parametrize('mutation', ['missing', 'limit', 'unresolved', 'halt', 'spent'])
def test_paid_start_fails_closed_without_original_healthy_budget(configuration, mutation):
    module, backend = runtime(), FakeProcesses()
    ledger = Path(configuration['ledger'])
    if mutation == 'missing':
        ledger.unlink()
    elif mutation == 'halt':
        ledger.with_suffix('.halt.json').write_text('{}')
    else:
        value = json.loads(ledger.read_text())
        if mutation == 'limit':
            value['limit_usd'] = '2'
        elif mutation == 'spent':
            value['spent_or_reserved_usd'] = '10'
        else:
            value['calls'] = [{'state': 'reserved'}]
        ledger.write_text(json.dumps(value))
    with pytest.raises((RuntimeError, ValueError), match='[Bb]udget|[Ll]edger'):
        module.Controller(configuration, backend).start(live_ai=True)
    assert not backend.started


def test_paid_worker_is_opt_in_reuses_ledger_and_notifies_only_on_request(configuration):
    module, backend = runtime(), FakeProcesses()
    control = module.Controller(configuration, backend)
    control.start(live_ai=True, notifications=True)
    assert [x[0] for x in backend.started][-2:] == ['notifications', 'reviews']
    name, command, env = backend.started[-1]
    assert env['OPENAI_API_KEY'] == 'synthetic-secret'
    assert not env['TELEGRAM_BOT_TOKEN']
    assert command[-1] == 'reviews'
    assert control.config['ledger'] == configuration['ledger']
    control.stop(keep_db=True)
    assert backend.stopped == ['reviews', 'notifications', 'nginx', 'api', 'asr']
    assert control.status() == {'db': 'running'}


def test_nginx_render_keeps_host_gate_and_forwards_only_to_loopback(configuration):
    module = runtime()
    rendered = module.render_nginx(configuration, 'synthetic.trycloudflare.com')
    assert 'listen 127.0.0.1:5214;' in rendered
    assert 'http://127.0.0.1:8036' in rendered
    assert 'return 421;' in rendered and '$remote_addr' in rendered
    assert '${TUNNEL_HOSTNAME}' not in rendered
    with pytest.raises(ValueError):
        module.render_nginx(configuration, 'host.invalid; include secret;')


def test_controller_uses_original_config_for_stop_after_operator_changes_paths(configuration):
    module, backend = runtime(), FakeProcesses()
    control = module.Controller(configuration, backend)
    control.start()
    original = backend.stop
    observed = []
    def stop(name, record, config):
        observed.append(config['postgres_data'])
        original(name, record, config)
    backend.stop = stop
    changed = {**configuration, 'postgres_data': '/unrelated/cluster'}
    module.Controller(changed, backend).stop()
    assert set(observed) == {configuration['postgres_data']}


def test_external_postgres_is_explicit_never_started_or_stopped(configuration):
    module, backend = runtime(), FakeProcesses()
    configuration['manage_postgres'] = False
    control = module.Controller(configuration, backend)
    control.start()
    assert 'db' not in [x[0] for x in backend.started]
    control.stop()
    assert 'db' not in backend.stopped


def test_config_cannot_copy_inline_secrets_into_process_state(configuration):
    module, backend = runtime(), FakeProcesses()
    configuration['OPENAI_API_KEY'] = 'forbidden-inline-key'
    with pytest.raises(ValueError, match='Unknown configuration'):
        module.Controller(configuration, backend).start()
    assert not backend.started


def test_preflight_rejects_remote_database_before_start(configuration):
    module, backend = runtime(), FakeProcesses()
    env_path = Path(configuration['env_file'])
    value = json.loads(env_path.read_text())
    value['DATABASE_URL'] = 'postgresql://synthetic@production.invalid/demo'
    env_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='loopback'):
        module.Controller(configuration, backend).start()
    assert not backend.started


def test_atomic_state_write_survives_short_windows_sharing_lock(tmp_path, monkeypatch):
    module = runtime()
    path = tmp_path / 'processes.json'
    path.write_text('{"old": true}')
    replace = Path.replace
    attempts = []
    def transient_lock(source, target):
        attempts.append(source)
        if len(attempts) < 3:
            assert json.loads(path.read_text()) == {'old': True}
            raise PermissionError('Sharing violation')
        return replace(source, target)
    monkeypatch.setattr(Path, 'replace', transient_lock)
    module.write_json(path, {'new': True})
    assert json.loads(path.read_text()) == {'new': True}
    assert len(attempts) == 3


def test_start_rejects_changed_config_while_own_processes_are_running(configuration):
    module, backend = runtime(), FakeProcesses()
    control = module.Controller(configuration, backend)
    control.start()
    count = len(backend.started)
    changed = {**configuration, 'api_port': 8099}
    with pytest.raises(RuntimeError, match='configuration changed'):
        module.Controller(changed, backend).start()
    assert len(backend.started) == count


def test_base_compose_ai_worker_cannot_inherit_paid_key():
    base = (ROOT / 'compose.yaml').read_text()
    ai = base.split('  ai-worker:', 1)[1].split('  web:', 1)[0]
    assert 'OPENAI_API_KEY: ""' in ai
    assert 'profiles:' not in ai


def test_live_compose_mounts_existing_budget_directory_without_creating_new_volume():
    overlay = (ROOT / 'compose.tunnel.yaml').read_text()
    assert 'profiles: ["live-ai"]' in overlay
    assert 'LIVE_AI_LEDGER_DIR:?' in overlay
    assert 'create_host_path: false' in overlay
    assert '"--budget-usd", "10"' in overlay
    assert 'live_budget:' not in overlay
    ordinary = overlay.split('  ai-worker:', 1)[1].split('  web:', 1)[0]
    paid = overlay.split('  ai-demo-worker:', 1)[1].split('  seed-demo:', 1)[0]
    assert 'profiles: ["unbudgeted-ai"]' in ordinary
    assert 'profiles: ["live-ai"]' in paid
    assert 'profiles: ["live-ai"]' not in ordinary


def test_docker_entry_bootstraps_api_package_with_no_pythonpath(tmp_path):
    repo = tmp_path / 'container-workspace'
    script = repo / 'infra/native_runtime.py'
    script.parent.mkdir(parents=True)
    script.write_bytes((ROOT / 'infra/native_runtime.py').read_bytes())
    api = repo / 'services/api'
    fake_worker = api / 'app/workers/budgeted_reviews.py'
    fake_worker.parent.mkdir(parents=True)
    (api / 'app/__init__.py').touch()
    (api / 'app/workers/__init__.py').touch()
    fake_worker.write_text('def main(argv):\n    print("FAKE_WORKER_BOOTSTRAPPED")\n    return 0\n')
    budget = tmp_path / 'budget'
    budget.mkdir()
    ledger = budget / 'budget.json'
    ledger.write_text('{"limit_usd":"10","spent_or_reserved_usd":"0","calls":[]}')
    (budget / 'frozen.json').write_text('{}')
    env = {k: v for k, v in os.environ.items() if k.upper() in
           ('SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP')}
    result = subprocess.run([sys.executable, '-I', str(script), '--existing-budget-worker',
        '--ledger', str(ledger)], cwd=api, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'FAKE_WORKER_BOOTSTRAPPED'


@pytest.mark.parametrize('marker', ['absent', 'old-token', 'wrong-pid', 'dead'])
def test_native_consumer_wait_refuses_unconfirmed_or_old_startup(tmp_path, marker):
    module = runtime()
    backend = module.WindowsProcesses.__new__(module.WindowsProcesses)
    identity = {'pid': 123, 'created': 'synthetic', 'exe': 'fake-python.exe'}
    backend.identity = lambda pid: None if marker == 'dead' else identity
    record = {'identity': identity, 'readiness_token': 'new-startup'}
    (tmp_path / 'processes.json').write_text(json.dumps({'reviews': record}))
    if marker != 'absent':
        value = dict(pid=123, token='new-startup', service='reviews')
        if marker == 'old-token':
            value['token'] = 'old-startup'
        if marker == 'wrong-pid':
            value['pid'] = 999
        (tmp_path / 'reviews.ready.json').write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match='readiness|startup'):
        backend.wait('reviews', dict(state_dir=str(tmp_path), ready_timeout_seconds=0), {})


def test_native_consumer_wait_accepts_own_confirmed_startup(tmp_path):
    module = runtime()
    backend = module.WindowsProcesses.__new__(module.WindowsProcesses)
    identity = {'pid': 123, 'created': 'synthetic', 'exe': 'fake-python.exe'}
    backend.identity = lambda pid: identity
    (tmp_path / 'processes.json').write_text(json.dumps({'reviews': {
        'identity': identity, 'readiness_token': 'current-startup'}}))
    (tmp_path / 'reviews.ready.json').write_text(json.dumps({
        'pid': 123, 'token': 'current-startup', 'service': 'reviews'}))
    backend.wait('reviews', dict(state_dir=str(tmp_path), ready_timeout_seconds=1), {})


@pytest.mark.parametrize('failure', ['none', 'file-lock', 'frozen', 'database-lock'])
def test_budgeted_callback_occurs_only_after_locks_and_frozen_pass(tmp_path, monkeypatch, failure):
    from app.core import config as settings_module, db as db_module
    from app.modules.ai_review import provider as provider_module
    from app.workers import budgeted_reviews as worker
    settings = settings_module.Settings(_env_file=None, openai_api_key='synthetic')
    monkeypatch.setattr(settings_module, 'settings', settings)
    monkeypatch.setattr(db_module, 'get_engine', lambda: object())
    monkeypatch.setattr(provider_module, 'OpenAIReviewProvider', lambda *args, **kwargs: object())
    ledger = tmp_path / 'budget.json'
    ledger.write_text('{"limit_usd":"10","spent_or_reserved_usd":"0","calls":[]}')
    frozen = dict(models=[settings.ai_light_model, settings.ai_model, settings.ai_complex_model],
        max_output_tokens=settings.ai_max_output_tokens,
        complex_max_output_tokens=settings.ai_complex_max_output_tokens,
        price_date=worker.PRICE_DATE, budget_usd='10')
    (tmp_path / 'frozen.json').write_text(json.dumps({} if failure == 'frozen' else frozen))
    events = []
    @contextmanager
    def database_guard(engine):
        events.append('database-lock')
        if failure == 'database-lock':
            raise RuntimeError('Lock busy')
        yield SimpleNamespace(check=lambda: events.append('ownership-checked'), ledger=None)
    monkeypatch.setattr(worker, 'single_database_consumer', database_guard)
    monkeypatch.setattr(worker, 'run', lambda *args, **kwargs: events.append('run') or 0)
    args = ['--live', '--ordinary-worker-stopped', '--ledger', str(ledger), '--budget-usd', '10']
    if failure == 'file-lock':
        with worker.exclusive_worker(ledger.with_suffix('.lock')):
            result = worker.main(args, on_ready=lambda: events.append('ready'))
    else:
        result = worker.main(args, on_ready=lambda: events.append('ready'))
    if failure == 'none':
        assert result == 0
        assert events == ['database-lock', 'ownership-checked', 'ready', 'run']
    else:
        assert result == 2
        assert 'ready' not in events and 'run' not in events


def test_notification_ready_only_after_successful_database_commit(monkeypatch):
    from app.workers import main as worker
    events = []
    class Session:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def commit(self):
            events.append('commit')
    monkeypatch.setattr(worker, 'get_engine', lambda: object())
    monkeypatch.setattr(worker, 'sessionmaker', lambda *args, **kwargs: Session)
    monkeypatch.setattr(worker, 'dispose_engine', lambda: events.append('dispose'))
    monkeypatch.setattr(worker, 'process_outbox', lambda *args: events.append('outbox'))
    def on_ready():
        events.append('ready')
        raise KeyboardInterrupt()
    worker.main(on_ready=on_ready)
    assert events == ['outbox', 'commit', 'ready', 'dispose']


def test_notification_commit_failure_cannot_publish_ready(monkeypatch):
    from app.workers import main as worker
    events = []
    attempts = []
    class Session:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def commit(self):
            attempts.append(1)
            if len(attempts) == 1:
                events.append('commit-failed')
                raise RuntimeError('Synthetic database outage')
            events.append('commit')
    monkeypatch.setattr(worker, 'get_engine', lambda: object())
    monkeypatch.setattr(worker, 'sessionmaker', lambda *args, **kwargs: Session)
    monkeypatch.setattr(worker, 'dispose_engine', lambda: events.append('dispose'))
    monkeypatch.setattr(worker, 'process_outbox', lambda *args: events.append('outbox'))
    monkeypatch.setattr(worker.time, 'sleep', lambda _: None)
    def stop_after_send(*args, **kwargs):
        events.append('send')
        raise KeyboardInterrupt()
    monkeypatch.setattr(worker, 'send_due_notifications', stop_after_send)
    worker.main(on_ready=lambda: events.append('ready'))
    assert events == ['outbox', 'commit-failed', 'outbox', 'commit', 'ready', 'send', 'dispose']


def test_ready_marker_matches_current_pid_and_start_token(tmp_path, monkeypatch):
    module = runtime()
    monkeypatch.setattr(module.os, 'getpid', lambda: 123)
    module.publish_consumer_ready({'state_dir': str(tmp_path)}, 'reviews', 'current-token')
    value = json.loads((tmp_path / 'reviews.ready.json').read_text())
    assert value == {'pid': 123, 'token': 'current-token', 'service': 'reviews'}
    with pytest.raises(RuntimeError, match='token'):
        module.publish_consumer_ready({'state_dir': str(tmp_path)}, 'reviews', None)


@pytest.mark.parametrize('name', ['notifications', 'reviews'])
def test_consumer_readiness_failure_rolls_back_start(configuration, name):
    module, backend = runtime(), FakeProcesses()
    backend.fail_ready = name
    control = module.Controller(configuration, backend)
    with pytest.raises(RuntimeError, match='ready'):
        control.start(notifications=True, live_ai=True)
    assert not backend.running
    assert control.status() == {}
