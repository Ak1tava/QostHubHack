"""Security review of the opt-in tunnel overlay; runtime Nginx still needs acceptance."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_only_tunnel_hostname_is_substituted_and_other_nginx_variables_survive():
    template = (ROOT / 'infra/nginx.tunnel.conf.template').read_text(encoding='utf-8')
    rendered = template.replace('${TUNNEL_HOSTNAME}', 'synthetic.trycloudflare.com')
    assert '${' not in rendered
    assert '$remote_addr' in rendered and '$uri' in rendered and '$http_upgrade' in rendered
    overlay = (ROOT / 'compose.tunnel.yaml').read_text(encoding='utf-8')
    assert 'NGINX_ENVSUBST_FILTER: "^TUNNEL_HOSTNAME$"' in overlay
    assert 'nginx.tunnel.conf.template:/etc/nginx/templates/default.conf.template:ro' in overlay


def test_tunnel_rejects_other_hosts_and_overwrites_only_trusted_proxy_headers():
    template = (ROOT / 'infra/nginx.tunnel.conf.template').read_text(encoding='utf-8')
    assert 'default 0;' in template and '"${TUNNEL_HOSTNAME}" 1;' in template
    assert 'return 421;' in template
    assert 'proxy_set_header Host ${TUNNEL_HOSTNAME};' in template
    assert 'proxy_set_header X-Forwarded-Proto https;' in template
    for header in ['X-Forwarded-For', 'X-Real-IP']:
        assert f'proxy_set_header {header} $remote_addr;' in template
    for header in ['CF-Connecting-IP', 'True-Client-IP', 'Forwarded']:
        assert f'proxy_set_header {header} "";' in template
    overlay = (ROOT / 'compose.tunnel.yaml').read_text(encoding='utf-8')
    assert 'SESSION_COOKIE_SECURE: "true"' in overlay
    assert 'PUBLIC_BASE_URL: https://${TUNNEL_HOSTNAME' in overlay
    assert '--header=Host: ${TUNNEL_HOSTNAME}' in overlay
    assert 'FORWARDED_ALLOW_IPS: 172.30.42.10' in (ROOT / 'compose.yaml').read_text(encoding='utf-8')


def test_ordinary_ai_worker_unpaid_and_existing_budget_and_private_seed_mounted():
    overlay = (ROOT / 'compose.tunnel.yaml').read_text(encoding='utf-8')
    assert 'OPENAI_API_KEY: ""' in overlay
    assert 'profiles: ["unbudgeted-ai"]' in overlay
    assert '--existing-budget-worker' in overlay
    assert 'LIVE_AI_LEDGER_DIR:?' in overlay
    assert 'create_host_path: false' in overlay
    assert 'photo_data:/workspace/data/photos:ro' in overlay
    assert './data/demo:/workspace/data/demo:ro' in overlay
    assert 'DEMO_AS_OF' in overlay
    assert 'expected_anomalies' not in overlay
