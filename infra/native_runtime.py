"""Explicit Windows native runtime. Never adopts existing processes or initializes data."""
import argparse
from contextlib import contextmanager
import ctypes
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ORDER = ('db', 'tunnel', 'asr', 'api', 'nginx', 'notifications', 'reviews')
FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
CONFIG_KEYS = {'repo', 'state_dir', 'env_file', 'python', 'postgres_bin', 'postgres_data',
    'postgres_port', 'api_port', 'web_port', 'asr_port', 'nginx', 'nginx_mime_types',
    'model_path', 'photo_path', 'ledger', 'cloudflared', 'ready_timeout_seconds',
    'manage_postgres', 'public_base_url'}


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        stream.write(json.dumps(value, indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    # Windows scanners can hold a short sharing lock. Keep the previous complete state.
    for attempt in range(20):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(.05)


@contextmanager
def controller_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'controller.lock').open('a+b') as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def load_environment(config, service):
    path = Path(config['env_file'])
    if path.suffix == '.json':
        values = json.loads(path.read_text(encoding='utf-8'))
    else:
        from dotenv import dotenv_values
        values = dotenv_values(path, interpolate=False)
    # Inherited shell secrets, test settings and root dotenv must not affect children.
    allowed = ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT', 'TEMP', 'TMP',
               'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMFILES')
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update({key: str(value) for key, value in values.items() if value is not None})
    env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1',
        PHOTO_STORAGE_PATH=config['photo_path'], SPEECH_MODEL_PATH=config['model_path'],
        SPEECH_SERVICE_URL=f"http://127.0.0.1:{config['asr_port']}",
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    if service != 'reviews':
        env['OPENAI_API_KEY'] = ''
    if service != 'notifications':
        env['TELEGRAM_BOT_TOKEN'] = ''
    if service != 'api':
        env['TELEGRAM_WEBHOOK_SECRET'] = ''
    if config.get('public_base_url'):
        env['PUBLIC_BASE_URL'] = config['public_base_url']
    return env


def validate_budget(path, limit='10'):
    path = Path(path)
    if Decimal(limit) != Decimal('10'):
        raise ValueError('Budget must retain the authorized total ceiling of $10')
    if not path.is_file() or not (path.parent / 'frozen.json').is_file():
        raise ValueError('Existing ledger and frozen budget configuration required')
    if path.with_suffix('.halt.json').exists():
        raise RuntimeError('Budget ownership halt: audit required')
    value = json.loads(path.read_text(encoding='utf-8'))
    saved = Decimal(value['limit_usd'])
    spent = Decimal(value['spent_or_reserved_usd'])
    if saved != Decimal(limit) or not spent.is_finite() or spent < 0 or spent >= saved:
        raise ValueError('Budget mismatch or exhausted ledger: audit required')
    if any(call['state'] != 'settled' or call.get('metadata', {}).get('error_code')
           for call in value['calls']):
        raise RuntimeError('Budget has an unresolved paid call: audit required')


def render_nginx(config, hostname):
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', hostname or ''):
        raise ValueError('Invalid public hostname')
    repo = Path(config['repo'])
    template = (repo / 'infra/nginx.tunnel.conf.template').read_text(encoding='utf-8')
    server = (template.replace('${TUNNEL_HOSTNAME}', hostname)
        .replace('listen 80;', f"listen 127.0.0.1:{config['web_port']};")
        .replace('root /usr/share/nginx/html;', f'root "{(repo / "apps/web/dist").as_posix()}";')
        .replace('http://api:8000', f"http://127.0.0.1:{config['api_port']}"))
    mime = Path(config['nginx_mime_types']).as_posix()
    return ('worker_processes 1;\npid logs/nginx.pid;\nerror_log logs/error.log;\n'
            f'events {{ worker_connections 256; }}\nhttp {{ include "{mime}";\n'
            'access_log off;\n' + server + '\n}\n')


class WindowsProcesses:
    """PID + creation stamp + executable identity; termination uses the same open handle."""
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('Native process control supports Windows only')
        from ctypes import wintypes
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        k = self.kernel
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(ctypes.c_ulonglong)] * 4
        k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                               wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]

    @contextmanager
    def handle(self, pid, terminate=False):
        rights = 0x1000 | 0x100000 | (0x0001 if terminate else 0)
        handle = self.kernel.OpenProcess(rights, False, int(pid))
        if not handle and ctypes.get_last_error() != 87:
            raise RuntimeError('Cannot verify process identity; refusing control')
        try:
            yield handle
        finally:
            if handle:
                self.kernel.CloseHandle(handle)

    def _identity(self, handle, pid):
        if not handle or self.kernel.WaitForSingleObject(handle, 0) == 0:
            return None
        stamps = [ctypes.c_ulonglong() for _ in range(4)]
        size = ctypes.c_ulong(32768)
        image = ctypes.create_unicode_buffer(size.value)
        if (not self.kernel.GetProcessTimes(handle, *[ctypes.byref(x) for x in stamps])
                or not self.kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size))):
            raise RuntimeError('Cannot verify process identity')
        return {'pid': int(pid), 'created': str(stamps[0].value),
                'exe': str(Path(image.value).resolve())}

    def identity(self, pid):
        with self.handle(pid) as handle:
            return self._identity(handle, pid)

    def free(self, port):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                raise RuntimeError(f'Port {port} occupied; existing processes are never adopted') from None

    def run(self, command, cwd, env, log):
        with Path(log).open('a', encoding='utf-8') as stream:
            result = subprocess.run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=stream, stderr=stream, creationflags=FLAGS, timeout=40)
        if result.returncode:
            raise RuntimeError('Native command failed; inspect private runtime logs')

    def spawn(self, name, command, cwd, env, log):
        with Path(log).open('a', encoding='utf-8') as stream:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=stream, stderr=stream, creationflags=FLAGS)
        record = self.identity(process.pid)
        if record is None:
            raise RuntimeError(f'{name} exited during startup')
        return record

    def postgres_start(self, config, env, log):
        data = Path(config['postgres_data'])
        # A postmaster.pid also covers a server listening elsewhere: no implicit adoption.
        if (data / 'postmaster.pid').exists():
            raise RuntimeError('PostgreSQL pidfile exists; inspect it without automatic deletion')
        pg = Path(config['postgres_bin'])
        self.run([str(pg / 'pg_ctl.exe'), '-w', '-t', '30', '-D', str(data), '-l', str(log),
            '-o', f"-h 127.0.0.1 -p {config['postgres_port']}", 'start'], data, env, log)
        pid = int((data / 'postmaster.pid').read_text().splitlines()[0])
        record = self.identity(pid)
        if not record or Path(record['exe']).resolve() != (pg / 'postgres.exe').resolve():
            raise RuntimeError('PostgreSQL identity mismatch')
        return record

    def wait(self, name, config, env):
        timeout = config.get('ready_timeout_seconds', 60)
        if name == 'tunnel':
            log = Path(config['state_dir']) / 'tunnel.log'
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                content = log.read_text(encoding='utf-8', errors='replace')
                match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', content)
                if match:
                    config['public_base_url'] = match.group()
                    return
                time.sleep(.25)
            raise RuntimeError('Quick Tunnel hostname unavailable')
        if name == 'db':
            pg = Path(config['postgres_bin'])
            self.run([str(pg / 'pg_isready.exe'), '-h', '127.0.0.1', '-p',
                str(config['postgres_port']), '-t', '20'], config['postgres_data'], env,
                Path(config['state_dir']) / 'ready.log')
            return
        if name not in ('api', 'asr', 'nginx'):
            return
        port = config[{'api': 'api_port', 'asr': 'asr_port', 'nginx': 'web_port'}[name]]
        headers = {'Host': urlparse(env['PUBLIC_BASE_URL']).hostname} if name == 'nginx' else {}
        request = Request(f'http://127.0.0.1:{port}/health/ready', headers=headers)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with urlopen(request, timeout=2) as response:
                    if response.status == 200:
                        return
            except (OSError, ValueError):
                pass
            time.sleep(.25)
        raise RuntimeError(f'{name} readiness failed; inspect private logs')

    def stop(self, name, record, config):
        # Holding this handle prevents PID reuse between identity check and termination.
        with self.handle(record['pid'], terminate=True) as handle:
            if self._identity(handle, record['pid']) != record:
                return
            env = load_environment(config, name)
            log = Path(config['state_dir']) / 'stop.log'
            if name in ('db', 'nginx'):
                if name == 'db':
                    pidfile = Path(config['postgres_data']) / 'postmaster.pid'
                    command = [str(Path(config['postgres_bin']) / 'pg_ctl.exe'), '-D',
                        config['postgres_data'], '-w', '-t', '30', '-m', 'fast', 'stop']
                else:
                    prefix = Path(config['state_dir']) / 'nginx'
                    pidfile = prefix / 'logs/nginx.pid'
                    command = [config['nginx'], '-p', prefix.as_posix() + '/',
                               '-c', 'nginx.conf', '-s', 'quit']
                if int(pidfile.read_text().splitlines()[0]) != record['pid']:
                    raise RuntimeError('Owned process and pidfile differ; refusing stop')
                self.run(command, config['repo'], env, log)
            elif not self.kernel.TerminateProcess(handle, 0):
                raise RuntimeError('Owned process termination failed')
            if self.kernel.WaitForSingleObject(handle, 30000) != 0:
                raise RuntimeError('Owned process did not stop; ownership retained')


class Controller:
    def __init__(self, config, backend=None):
        self.config = dict(config)
        self.backend = backend if backend is not None else WindowsProcesses()
        self.state_dir = Path(config['state_dir'])
        self.state_file = self.state_dir / 'processes.json'

    def state(self):
        return json.loads(self.state_file.read_text()) if self.state_file.exists() else {}

    def owned(self, record):
        identity = record.get('identity')
        return bool(identity and self.backend.identity(identity['pid']) == identity)

    def status(self):
        return {name: 'running' if self.owned(record) else 'stale'
                for name, record in self.state().items()}

    def preflight(self, names):
        config = self.config
        if set(config) - CONFIG_KEYS:
            raise ValueError('Unknown configuration keys; keep secrets in the external env file')
        for key in ('repo', 'state_dir', 'env_file', 'python', 'postgres_bin', 'postgres_data',
                    'nginx', 'nginx_mime_types', 'model_path', 'photo_path'):
            if not Path(config[key]).is_absolute():
                raise ValueError(f'{key} must be an absolute path')
        for key in ('postgres_port', 'api_port', 'web_port', 'asr_port'):
            if not isinstance(config[key], int) or not 1 <= config[key] <= 65535:
                raise ValueError('Invalid loopback port')
        if len({config[key] for key in ('postgres_port', 'api_port', 'web_port', 'asr_port')}) != 4:
            raise ValueError('Runtime ports must differ')
        for key in ('python', 'nginx', 'nginx_mime_types', 'env_file'):
            if not Path(config[key]).is_file():
                raise ValueError(f'{key} file missing')
        if not (Path(config['repo']) / 'apps/web/dist/index.html').is_file():
            raise ValueError('Build the frontend before starting the runtime')
        if not (Path(config['postgres_data']) / 'PG_VERSION').is_file():
            raise ValueError('Existing PostgreSQL cluster required; no automatic initdb')
        if not Path(config['photo_path']).is_dir():
            raise ValueError('Existing private photo directory required')
        for file in ('model.bin', 'config.json', 'tokenizer.json'):
            if not (Path(config['model_path']) / file).is_file():
                raise ValueError('Complete local Whisper model required; downloads disabled')
        env = load_environment(config, 'api')
        db = urlparse(env.get('DATABASE_URL', ''))
        if db.hostname != '127.0.0.1' or db.port != config['postgres_port']:
            raise ValueError('Native DATABASE_URL must use the configured loopback PostgreSQL port')
        if not env.get('SPEECH_SERVICE_TOKEN') or env.get('SESSION_COOKIE_SECURE', '').lower() != 'true':
            raise ValueError('ASR token and secure session cookies required')
        if urlparse(env.get('PUBLIC_BASE_URL', '')).scheme != 'https':
            raise ValueError('HTTPS public URL required')
        if 'reviews' in names:
            validate_budget(config['ledger'])
            if not load_environment(config, 'reviews').get('OPENAI_API_KEY'):
                raise ValueError('Budgeted worker key unavailable')
        if 'notifications' in names and not load_environment(config, 'notifications').get('TELEGRAM_BOT_TOKEN'):
            raise ValueError('Notification worker token unavailable')
        if 'tunnel' in names and not Path(config['cloudflared']).is_file():
            raise ValueError('Portable cloudflared binary required')

    def start(self, *, live_ai=False, notifications=False, tunnel=False):
        names = [name for name in ORDER if name not in ('reviews', 'notifications', 'tunnel')
                 or {'reviews': live_ai, 'notifications': notifications, 'tunnel': tunnel}[name]]
        if not self.config.get('manage_postgres', True):
            names.remove('db')
        with controller_lock(self.state_dir):
            self.preflight(names)
            state = self.state()
            for record in state.values():
                before = record.get('config', self.config)
                keys = (set(before) | set(self.config)) - {'public_base_url', 'ready_timeout_seconds'}
                if self.owned(record) and any(before.get(key) != self.config.get(key) for key in keys):
                    raise RuntimeError('Runtime configuration changed; stop owned processes first')
            if not self.config.get('manage_postgres', True):
                self.backend.wait('db', self.config, load_environment(self.config, 'db'))
            ports = dict(db='postgres_port', asr='asr_port', api='api_port', nginx='web_port')
            for name in names:
                if name in ports and not (name in state and self.owned(state[name])):
                    self.backend.free(self.config[ports[name]])
            snapshot = self.state_dir / 'runtime.json'
            write_json(snapshot, self.config)
            started = []
            try:
                for name in names:
                    if name in state and self.owned(state[name]):
                        self.backend.wait(name, self.config, load_environment(self.config, name))
                        continue
                    env = load_environment(self.config, name)
                    log = self.state_dir / f'{name}.log'
                    if name == 'db':
                        identity = self.backend.postgres_start(self.config, env, log)
                    else:
                        if name == 'nginx':
                            prefix = self.state_dir / 'nginx'
                            (prefix / 'logs').mkdir(parents=True, exist_ok=True)
                            (prefix / 'temp').mkdir(exist_ok=True)
                            rendered = render_nginx(self.config, urlparse(env['PUBLIC_BASE_URL']).hostname)
                            (prefix / 'nginx.conf').write_text(rendered, encoding='utf-8')
                            command = [self.config['nginx'], '-p', prefix.as_posix() + '/',
                                '-c', 'nginx.conf', '-g', 'daemon off;']
                        elif name == 'tunnel':
                            # Truncate old quick-tunnel URLs before starting a new tunnel.
                            log.write_text('', encoding='utf-8')
                            command = [self.config['cloudflared'], 'tunnel', '--url',
                                f"http://127.0.0.1:{self.config['web_port']}", '--no-autoupdate']
                        else:
                            command = [self.config['python'], str(Path(__file__).resolve()),
                                '--config', str(snapshot), '--entry', name]
                        identity = self.backend.spawn(name, command,
                            str(Path(self.config['repo']) / 'services/api'), env, log)
                    if not identity:
                        raise RuntimeError('Process identity unavailable')
                    state[name] = {'identity': identity, 'config': dict(self.config)}
                    started.append(name)
                    write_json(self.state_file, state)
                    self.backend.wait(name, self.config, env)
                    write_json(snapshot, self.config)
            except Exception:
                self._stop(state, started)
                raise

    def _stop(self, state, names):
        for name in reversed(ORDER):
            if name not in names or name not in state:
                continue
            if self.owned(state[name]):
                self.backend.stop(name, state[name]['identity'], state[name].get('config', self.config))
            state.pop(name)
            write_json(self.state_file, state)

    def stop(self, *, keep_db=False):
        with controller_lock(self.state_dir):
            self._stop(self.state(), [name for name in ORDER if not keep_db or name != 'db'])


def entry(config, name):
    environment = load_environment(config, name)
    os.environ.clear()
    os.environ.update(environment)
    sys.path.insert(0, str(Path(config['repo']) / 'services/api'))
    from app.core import config as app_config
    app_config.settings = app_config.Settings(_env_file=None)
    if name in ('api', 'asr'):
        import uvicorn
        uvicorn.run('app.main:app' if name == 'api' else 'app.modules.speech.internal:app',
            host='127.0.0.1', port=config['api_port' if name == 'api' else 'asr_port'],
            access_log=False, proxy_headers=False)
    elif name == 'notifications':
        import runpy
        runpy.run_module('app.workers.main', run_name='__main__')
    else:
        validate_budget(config['ledger'])
        from app.workers.budgeted_reviews import main
        raise SystemExit(main(['--live', '--ordinary-worker-stopped', '--ledger', config['ledger'],
            '--budget-usd', '10', '--max-seconds', '86400', '--max-stages', '10000']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('start', 'stop', 'status'))
    parser.add_argument('--config', type=Path)
    parser.add_argument('--entry', choices=('api', 'asr', 'notifications', 'reviews'))
    parser.add_argument('--live-ai', action='store_true')
    parser.add_argument('--notifications', action='store_true')
    parser.add_argument('--tunnel', action='store_true')
    parser.add_argument('--keep-db', action='store_true')
    parser.add_argument('--existing-budget-worker', action='store_true')
    parser.add_argument('--ledger', type=Path)
    parser.add_argument('--budget-usd', default='10')
    args = parser.parse_args()
    try:
        if args.existing_budget_worker:
            validate_budget(args.ledger, args.budget_usd)
            from app.workers.budgeted_reviews import main as worker_main
            return worker_main(['--live', '--ordinary-worker-stopped', '--ledger', str(args.ledger),
                '--budget-usd', args.budget_usd, '--max-seconds', '86400', '--max-stages', '10000'])
        if args.config is None:
            parser.error('--config is required')
        config = json.loads(args.config.read_text(encoding='utf-8'))
        if args.entry:
            entry(config, args.entry)
            return 0
        control = Controller(config)
        if args.action == 'start':
            control.start(live_ai=args.live_ai, notifications=args.notifications, tunnel=args.tunnel)
        elif args.action == 'stop':
            control.stop(keep_db=args.keep_db)
        elif args.action != 'status':
            parser.error('start, stop or status required')
        print(json.dumps(control.status(), ensure_ascii=False))
        return 0
    except Exception:
        # Settings/SDK/subprocess errors may include credential-bearing values.
        print('Runtime command failed; inspect private logs/configuration (credentials suppressed)', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
