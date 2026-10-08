"""Native lifecycle safety, with no real processes, network or paid I/O."""
import importlib.util
import json
from pathlib import Path

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
