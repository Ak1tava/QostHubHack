"""The persisted master score must use the same scale as review and rating."""
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from test_work_order_internal import make_order, make_submission


@pytest.mark.parametrize('score', [0, 6, 100])
def test_database_rejects_master_score_outside_five_point_scale(database, score):
    from app.modules.work_orders.models import MasterDecision
    order = make_order(database)
    submission = make_submission(database, order)
    db = database['session']
    db.add(MasterDecision(work_order_id=order.id, submission_id=submission.id,
                          master_id=database['master'].id, decision='accept', score=score))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_upgrade_rejects_legacy_score_without_reinterpreting_history():
    url = os.environ.get('MIGRATION_TEST_DATABASE_URL')
    if not url:
        pytest.fail('Set MIGRATION_TEST_DATABASE_URL to qosthub_migration_test*')
    parsed = make_url(url)
    if parsed.get_backend_name() != 'postgresql' or not (parsed.database or '').startswith('qosthub_migration_test'):
        pytest.fail('Refusing migration reset outside qosthub_migration_test*')
    from app.modules.auth.models import User
    from app.modules.catalog.models import Area, Equipment, WorkCode
    from app.modules.work_orders.models import MasterDecision, Submission, WorkOrder, utcnow
    engine = create_engine(url)
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    try:
        with engine.begin() as connection:
            config.attributes['connection'] = connection
            command.downgrade(config, 'base')
            command.upgrade(config, '0004')
            user, area, equipment, code, order, submission, decision = [uuid4() for _ in range(7)]
            connection.execute(User.__table__.insert().values(id=user, login='migration-master',
                password_hash='synthetic', display_name='Synthetic', role='master'))
            connection.execute(Area.__table__.insert().values(id=area, name='Synthetic'))
            connection.execute(Equipment.__table__.insert().values(id=equipment, area_id=area, name='Synthetic'))
            connection.execute(WorkCode.__table__.insert().values(id=code, code='SYN', name='Synthetic'))
            connection.execute(WorkOrder.__table__.insert().values(id=order, number='SYN-1',
                work_type='planned', description='Synthetic', area_id=area, equipment_id=equipment,
                assignee_id=user, master_id=user, due_at=utcnow()))
            connection.execute(Submission.__table__.insert().values(id=submission, work_order_id=order,
                revision=1, worker_id=user, work_description='Synthetic', work_code_id=code))
            connection.execute(MasterDecision.__table__.insert().values(id=decision, work_order_id=order,
                submission_id=submission, master_id=user, decision='accept', score=100))
            with pytest.raises(RuntimeError, match='1..5'):
                command.upgrade(config, 'head')
            assert connection.scalar(select(MasterDecision.score).where(MasterDecision.id == decision)) == 100
            assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0004'
            assert 'review_jobs' not in inspect(connection).get_table_names()
            # A human resolves legacy data; the migration itself never changes it.
            connection.execute(MasterDecision.__table__.update().where(MasterDecision.id == decision).values(score=5))
            command.upgrade(config, 'head')
            assert connection.scalar(select(MasterDecision.score).where(MasterDecision.id == decision)) == 5
            assert {'review_jobs', 'review_receipts'} <= set(inspect(connection).get_table_names())
            command.downgrade(config, '0004')
            assert connection.scalar(select(MasterDecision.score).where(MasterDecision.id == decision)) == 5
            assert 'review_jobs' not in inspect(connection).get_table_names()
            command.downgrade(config, 'base')
    finally:
        engine.dispose()
