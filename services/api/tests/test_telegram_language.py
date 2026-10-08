"""Durable private-chat locale and recipient-based notification selection."""

import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.modules.telegram.models import TelegramBinding
from app.modules.telegram.service import handle_update, issue_link_token
from test_deadlines import NOW, order_at, rows, deliver
from test_deadlines import ready as ready
from test_telegram_linking import start


def message(text, update_id=2, **changes):
    payload = start('unused', update_id)
    payload['message']['text'] = text
    payload['message']['from']['language_code'] = 'kk'
    payload['message'].update(changes)
    return payload


def bind(database, *, locale='ru', telegram_id=123):
    db = database['session']
    token = issue_link_token(db, database['worker'], NOW)
    payload = start(token, sender=telegram_id, chat=telegram_id)
    payload['message']['from']['language_code'] = locale
    assert handle_update(db, payload, NOW) == 'linked'
    db.commit()
    return db.get(TelegramBinding, database['worker'].id)


@pytest.mark.parametrize('telegram_locale,expected', [('kk','kk'), ('kk-KZ','kk'), ('ru','ru'), ('ru-RU','ru'), ('en','ru'), (None,'ru')])
def test_initial_binding_language_defaults_from_telegram(database, telegram_locale, expected):
    binding = bind(database, locale=telegram_locale)
    assert binding.language == expected


@pytest.mark.parametrize('command,expected', [('/ru','ru'), ('RU','ru'), ('/kz','kk'), ('/kk','kk'), ('KZ','kk'), (' KK ','kk')])
def test_explicit_language_is_persisted_in_fresh_session(database, command, expected):
    bind(database, locale='ru' if expected == 'kk' else 'kk')
    db = database['session']
    assert handle_update(db, message(command), NOW) == 'language_updated'
    db.commit()
    with Session(database['engine']) as fresh:
        assert fresh.get(TelegramBinding, database['worker'].id).language == expected


def test_duplicate_cannot_change_language_or_emit_another_reply(database):
    from app.modules.telegram.service import prepare_reply
    binding = bind(database)
    payload = message('/kz')
    assert handle_update(database['session'], payload, NOW) == 'language_updated'
    database['session'].commit()
    payload['message']['text'] = '/ru'
    result = handle_update(database['session'], payload, NOW)
    assert result == 'duplicate'
    assert prepare_reply(database['session'], payload, result) == {}
    assert binding.language == 'kk'


def test_relink_keeps_explicit_choice_despite_telegram_default(database):
    binding = bind(database, locale='kk')
    db = database['session']
    assert handle_update(db, message('/ru'), NOW) == 'language_updated'
    token = issue_link_token(db, database['worker'], NOW)
    payload = start(token, 3)
    payload['message']['from']['language_code'] = 'kk'
    assert handle_update(db, payload, NOW) == 'linked'
    db.commit()
    assert binding.language == 'ru'


@pytest.mark.parametrize('case', ['group', 'wrong_chat', 'inactive', 'unknown_sender'])
def test_language_change_never_crosses_private_active_binding_boundary(database, case):
    binding = bind(database)
    payload = message('/kz')
    if case == 'group':
        payload['message']['chat']['type'] = 'group'
    elif case == 'wrong_chat':
        payload['message']['chat']['id'] = 124
    elif case == 'unknown_sender':
        payload['message']['from']['id'] = payload['message']['chat']['id'] = 456
    else:
        database['worker'].is_active = False
        database['session'].commit()
    result = handle_update(database['session'], payload, NOW)
    assert result in {'ignored', 'not_linked'}
    database['session'].commit()
    assert binding.language == 'ru'


def test_binding_owner_changed_before_user_lock_is_not_modified(database, monkeypatch):
    from app.modules.auth.models import User
    bind(database)
    db = database['session']
    original_scalar = db.scalar
    moved = False
    def before_lock(statement, *args, **kwargs):
        nonlocal moved
        descriptions = getattr(statement, 'column_descriptions', [])
        if not moved and any(c.get('entity') is User for c in descriptions):
            moved = True
            with Session(database['engine']) as other:
                binding = other.get(TelegramBinding, database['worker'].id)
                binding.user_id = database['outsider'].id
                other.get(User, database['outsider'].id).is_active = False
                other.commit()
        return original_scalar(statement, *args, **kwargs)
    monkeypatch.setattr(db, 'scalar', before_lock)
    assert handle_update(db, message('/kz'), NOW) == 'not_linked'
    db.commit()
    with Session(database['engine']) as fresh:
        assert fresh.get(TelegramBinding, database['outsider'].id).language == 'ru'


def test_unlinked_help_and_choice_are_bilingual_and_do_not_create_binding(database):
    from app.modules.telegram.service import prepare_reply
    db = database['session']
    for index, text in enumerate(('/start', '/help', '/language', 'KZ'), 10):
        payload = message(text, index)
        result = handle_update(db, payload, NOW)
        reply = prepare_reply(db, payload, result)
        assert reply['method'] == 'sendMessage' and reply['chat_id'] == 123
        assert 'PWA' in reply['text'] and 'Привяжите' in reply['text'] and 'байланыстырыңыз' in reply['text']
    assert db.get(TelegramBinding, database['worker'].id) is None


def test_webhook_replies_after_commit_without_http_and_preserves_contract(client, database, monkeypatch):
    from app.core.config import settings
    from app.modules.telegram.client import TelegramClient
    monkeypatch.setattr(settings, 'telegram_webhook_secret', SecretStr('synthetic-secret'))
    def forbidden(*args, **kwargs):
        pytest.fail('Bot command reply must use webhook JSON, not HTTP')
    monkeypatch.setattr(TelegramClient, '_call', forbidden)
    bind(database)
    response = client.post('/api/v1/telegram/webhook', json=message('/language'), headers={'X-Telegram-Bot-Api-Secret-Token': 'synthetic-secret'})
    assert response.status_code == 200
    reply = response.json()
    assert reply['result'] == 'language_menu' and reply['method'] == 'sendMessage'
    assert reply['reply_markup']['keyboard'] == [[{'text': 'RU'}, {'text': 'KZ'}]]
    response = client.post('/api/v1/telegram/webhook', json=message('KZ', 3), headers={'X-Telegram-Bot-Api-Secret-Token': 'synthetic-secret'})
    assert response.json()['result'] == 'language_updated'
    assert 'қазақ' in response.json()['text'].lower()
    with Session(database['engine']) as fresh:
        assert fresh.get(TelegramBinding, database['worker'].id).language == 'kk'
    assert client.post('/api/v1/telegram/webhook', json=message('KZ', 3), headers={'X-Telegram-Bot-Api-Secret-Token': 'synthetic-secret'}).json() == {'result': 'duplicate'}


def test_notification_and_button_follow_each_recipient_language(database, ready):
    from datetime import timedelta
    from app.workers.notifications import schedule_notifications
    db = database['session']
    db.get(TelegramBinding, database['worker'].id).language = 'kk'
    order = order_at(database)
    schedule_notifications(order, NOW)
    db.commit()
    for job in rows(db):
        if job.kind != 'overdue':
            job.status = 'CANCELLED'
    db.commit()
    class Capture:
        def __init__(self):
            self.messages = []
        def send_message(self, chat, text, url, *, language='ru'):
            self.messages.append((chat, text, url, language))
    capture = Capture()
    assert deliver(ready, order.due_at + timedelta(minutes=1), client=capture) == 2
    by_chat = {m[0]: m for m in capture.messages}
    assert by_chat[1][3] == 'kk' and 'Мерзімі өтті' in by_chat[1][1]
    assert 'Жабдық: Насос' in by_chat[1][1] and 'PWA' in by_chat[1][1]
    assert by_chat[2][3] == 'ru' and 'Срок истёк' in by_chat[2][1]


@pytest.mark.parametrize('kind,label', [('new','Жаңа наряд'), ('reminder','Мерзімге 30 минут қалды'), ('unaccepted','Наряд қабылданбады'), ('overdue','Мерзімі өтті'), ('emergency_queued','Апаттық наряд кезекте')])
def test_all_notification_kinds_have_kazakh_labels_and_keep_untrusted_content(database, kind, label):
    from app.modules.telegram.formatter import format_notification
    order = order_at(database, description='Синтетический ремонт')
    text = format_notification(kind=kind, order=order, equipment=database['equipment'], area=database['area'], responsible=database['worker'], brigade=None, now=NOW, timezone='Asia/Qyzylorda', language='kk')
    assert text.startswith(label) and 'Жабдық: Насос' in text
    assert 'PWA' in text


def test_transport_localizes_inline_open_button_without_changing_pwa_url(monkeypatch):
    import json
    from app.core.config import settings
    from app.modules.telegram.client import TelegramClient
    monkeypatch.setattr(settings, 'telegram_bot_token', SecretStr('synthetic-token'))
    captured = []
    def transport(request, timeout):
        captured.append(json.loads(request.data))
        return 200, {'ok': True, 'result': {}}
    TelegramClient(transport=transport).send_message(123, 'Синтетикалық наряд', 'https://synthetic.invalid/orders/1', language='kk')
    button = captured[0]['reply_markup']['inline_keyboard'][0][0]
    assert button == {'text': 'Нарядты ашу', 'url': 'https://synthetic.invalid/orders/1'}
