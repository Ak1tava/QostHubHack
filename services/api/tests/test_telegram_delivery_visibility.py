"""Workers cannot inspect another recipient's delivery through a shared brigade order."""
from datetime import datetime, timezone
from uuid import UUID

from conftest import sign_in
from work_order_helpers import add_user, seed_order


def test_worker_delivery_is_owned_while_master_reads_allowed_order(client, database):
    from app.modules.telegram.models import Notification
    member = add_user(database, 'member', brigade_id=database['brigade'].id)
    order = seed_order(database, assignee_id=None, brigade_id=member.brigade_id,
                       responsible_id=database['worker'].id)
    db = database['session']
    now = datetime.now(timezone.utc)
    for recipient in [database['master'], database['worker'], member]:
        db.add(Notification(kind='new', work_order_id=UUID(order['id']), assignment_version=1,
                            recipient_id=recipient.id, due_at=now, next_attempt_at=now,
                            dedup_key=f'test:{recipient.id}', status='PENDING'))
    db.commit()
    path = f"/api/v1/work-orders/{order['id']}/notifications"
    sign_in(client, 'member')
    assert [row['recipient_id'] for row in client.get(path).json()] == [str(member.id)]
    sign_in(client, 'master')
    assert len(client.get(path).json()) == 3
    sign_in(client, 'outsider')
    assert client.get(path).status_code == 404
