"""Two actual clients behind Nginx; arbitrary forwarded headers cannot evade limits."""
import json
import os
import secrets
import subprocess

from verify_stack import compose


PROBE = '''
import json, sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError
statuses = []
for number in range(int(sys.argv[1])):
    request = Request('http://web/api/v1/auth/csrf', headers={
        'Host': 'localhost:5173', 'X-Forwarded-For': f'198.51.100.{number + 1}',
        'X-Real-IP': f'203.0.113.{number + 1}',
    })
    try:
        with urlopen(request, timeout=10) as response:
            statuses.append(response.status)
    except HTTPError as error:
        assert error.code == 429 and int(error.headers['Retry-After']) > 0
        statuses.append(error.code)
print(json.dumps(statuses))
'''
DIRECT = '''
from urllib.request import Request, urlopen
from urllib.error import HTTPError
statuses = []
for number in range(62):
    try:
        with urlopen(Request('http://api:8000/api/v1/auth/csrf', headers={
            'X-Forwarded-For': f'192.0.2.{number + 1}'
        }), timeout=10) as response:
            statuses.append(response.status)
    except HTTPError as error:
        statuses.append(error.code)
assert statuses[:60] == [200] * 60 and statuses[60:] == [429, 429], statuses
print('PASS: direct untrusted peer cannot spoof forwarded addresses')
'''


def main():
    if os.environ.get("CI") != "true":
        raise SystemExit("Disposable CI stack required")
    suffix = secrets.token_hex(4)
    clients = [f"qosthub-proxy-{suffix}-{i}" for i in range(3)]
    python = "/workspace/services/api/.venv/bin/python"
    try:
        for client in clients:
            compose("run", "-d", "--no-deps", "--name", client, "api", "sleep", "180")
        first = json.loads(subprocess.check_output(["docker", "exec", clients[0], python, "-c", PROBE, "62"], text=True, timeout=90))
        assert first[:60] == [200] * 60 and first[60:] == [429, 429], first
        second = json.loads(subprocess.check_output(["docker", "exec", clients[1], python, "-c", PROBE, "1"], text=True, timeout=20))
        assert second == [200], "Distinct real client shared the blocked client's IP limit"
        subprocess.run(["docker", "exec", clients[2], python, "-c", DIRECT], check=True, timeout=90)
        print("PASS: real client IPs have separate limits; Nginx strips spoofed forwarded headers")
    finally:
        subprocess.run(["docker", "rm", "-f", *clients], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


if __name__ == "__main__":
    main()
