"""Opt-in single-consumer live demo; explicit budget amendments, ceiling $10."""
import argparse
import json
import os
import time
from contextlib import contextmanager
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.modules.ai_review.eval_runner import (
    BudgetExceeded, BudgetLedger, BudgetedProvider, PRICE_DATE, PRICES,
    freeze_configuration, write_json,
)

LOCK_KEY = 71007010
LIVE_BUDGET_CEILING = Decimal('10')


def validate_live_limit(value):
    limit = Decimal(value)
    if not limit.is_finite() or not Decimal('0') < limit <= LIVE_BUDGET_CEILING:
        raise ValueError('Live worker budget limit must be >0 and <=10 USD')
    return limit


class LiveBudgetLedger(BudgetLedger):
    """Keep generic evaluation's $5 ceiling; only this opt-in worker allows $10."""

    def __init__(self, path, limit):
        limit = validate_live_limit(limit)
        super().__init__(path, str(min(limit, Decimal('5'))))
        self.limit = limit


def _amendment(path):
    amendment_path = path.with_suffix('.budget-amendment.json')
    if not amendment_path.exists():
        return None
    value = json.loads(amendment_path.read_text(encoding='utf-8'))
    previous, new = validate_live_limit(value['from_usd']), validate_live_limit(value['to_usd'])
    if (value['version'] != 1 or new <= previous
            or Decimal(value['ledger_before']['limit_usd']) != previous
            or Decimal(value['frozen_before']['budget_usd']) != previous):
        raise ValueError('Invalid budget amendment: audit required')
    return value


def freeze_live_configuration(path, config):
    amendment = _amendment(path)
    if amendment is None:
        return freeze_configuration(path.parent, config)
    frozen = json.loads((path.parent / 'frozen.json').read_text(encoding='utf-8'))
    effective = {**amendment['frozen_before'], 'budget_usd': amendment['to_usd']}
    if frozen != amendment['frozen_before'] or config != effective:
        raise ValueError('Frozen live configuration changed: audit required')


class DatabaseLockLost(RuntimeError):
    pass


class DatabaseConsumerGuard:
    def __init__(self, connection):
        self.connection = connection
        # Pin the actual driver, not a SQLAlchemy proxy that could reconnect.
        self.driver = connection.connection.driver_connection
        self.backend_pid = self.driver.info.backend_pid
        self.lost = False
        self.ledger = None

    def _lose(self):
        self.lost = True
        if self.ledger is not None:
            write_json(self.ledger.path.with_suffix('.halt.json'),
                       {'reason': 'database_lock_lost', 'backend_pid': self.backend_pid,
                        'audit_required': True})
        if not self.connection.closed and not self.connection.invalidated:
            self.connection.invalidate()
        raise DatabaseLockLost('Original database lock session lost: audit required') from None

    def check(self):
        if self.lost:
            raise DatabaseLockLost('Original database lock session lost: audit required')
        if (self.connection.closed or self.connection.invalidated
                or self.driver.closed or self.driver.broken):
            self._lose()
        try:
            with self.driver.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid(), EXISTS (SELECT 1 FROM pg_locks "
                               "WHERE locktype='advisory' AND pid=pg_backend_pid() "
                               "AND classid=0 AND objid=%s AND objsubid=1 "
                               "AND mode='ExclusiveLock' AND granted)", (LOCK_KEY,))
                pid, owned = cursor.fetchone()
        except Exception:
            self._lose()
        if pid != self.backend_pid or not owned:
            self._lose()

    def release(self):
        if self.lost:
            return
        self.check()
        try:
            with self.driver.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
        except Exception:
            self._lose()


class OwnershipCheckedProvider:
    def __init__(self, provider, check):
        self.provider, self.check = provider, check

    @property
    def last_diagnostics(self):
        return getattr(self.provider, 'last_diagnostics', None)

    def review(self, *args, **kwargs):
        # BudgetedProvider invokes this only AFTER durable reservation, directly
        # before the underlying provider can start billed I/O.
        self.check()
        return self.provider.review(*args, **kwargs)


def open_ledger(path: Path, limit='2') -> BudgetLedger:
    if path.with_suffix('.halt.json').exists():
        raise RuntimeError('Persisted database ownership halt: audit required')
    limit = validate_live_limit(limit)
    amendment = _amendment(path)
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if Decimal(saved['limit_usd']) != limit:
            raise ValueError('Persisted budget limit cannot change on restart')
        if amendment:
            before_calls = amendment['ledger_before']['calls']
            if limit != Decimal(amendment['to_usd']) or saved['calls'][:len(before_calls)] != before_calls:
                raise ValueError('Incomplete or altered budget amendment: audit required')
        ids = set()
        for record in saved['calls']:
            reserved, charged = Decimal(record['reserved_usd']), Decimal(record['charged_usd'])
            if (not reserved.is_finite() or reserved <= 0 or not charged.is_finite()
                    or charged < 0 or record['call_id'] in ids):
                raise ValueError('Invalid persisted budget: audit required')
            ids.add(record['call_id'])
            if record['state'] != 'settled' or record.get('metadata', {}).get('error_code'):
                raise RuntimeError('Unresolved paid call: audit required; reservation remains charged')
    elif amendment:
        raise ValueError('Budget amendment without ledger: audit required')
    ledger = LiveBudgetLedger(path, str(limit))
    if ledger.spent > limit:
        raise BudgetExceeded('Persisted budget exceeded: audit required')
    return ledger


def increase_budget(engine, path, *, previous_limit, new_limit, config):
    """Amend only; preserve immutable frozen.json and the complete old ledger."""
    previous, new = validate_live_limit(previous_limit), validate_live_limit(new_limit)
    if new <= previous or Decimal(config['budget_usd']) != new:
        raise ValueError('Explicit amendment must increase the matching budget')
    with exclusive_worker(path.with_suffix('.lock')):
        with single_database_consumer(engine) as guard:
            if not path.is_file() or _amendment(path) is not None:
                raise ValueError('Existing unamended ledger required: audit required')
            ledger = open_ledger(path, str(previous))
            guard.ledger = ledger
            before = json.loads(path.read_text(encoding='utf-8'))
            frozen = json.loads((path.parent / 'frozen.json').read_text(encoding='utf-8'))
            if (Decimal(before['spent_or_reserved_usd']) != ledger.spent
                    or Decimal(frozen['budget_usd']) != previous
                    or {**frozen, 'budget_usd': str(new)} != config):
                raise ValueError('Budget/configuration mismatch: audit required')
            amendment = dict(
                version=1, from_usd=str(previous), to_usd=str(new),
                authorized_at=datetime.now(timezone.utc).isoformat(),
                ledger_before=before, frozen_before=frozen,
            )
            guard.check()
            # Immutable evidence first. A crash between writes fails closed on
            # restart; audit can inspect both snapshots without resetting costs.
            write_json(path.with_suffix('.budget-amendment.json'), amendment, exclusive=True)
            guard.check()
            write_json(path, {**before, 'limit_usd': str(new)})
            return open_ledger(path, str(new))


@contextmanager
def exclusive_worker(path: Path):
    """OS lock releases on crash; the persistent file is never removed or reset."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as marker:
        try:
            marker.seek(0)
            if not marker.read(1):
                marker.write(b'0')
                marker.flush()
            marker.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(marker.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(marker.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('Budgeted worker is already running') from error
        try:
            yield
        finally:
            marker.seek(0)
            if os.name == 'nt':
                msvcrt.locking(marker.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(marker.fileno(), fcntl.LOCK_UN)


class DemoBudgetedProvider(BudgetedProvider):
    def __init__(self, provider, ledger, *args, lock_guard=None, **kwargs):
        self.lock_guard, self.stop_reason = lock_guard, None
        super().__init__(OwnershipCheckedProvider(provider, self.check_ownership), ledger, *args, **kwargs)

    def check_ownership(self):
        if self.lock_guard is not None:
            self.lock_guard.ledger = self.ledger
            try:
                self.lock_guard.check()
            except DatabaseLockLost:
                self.stop_reason = 'database_lock_lost'
                raise

    def review(self, *args, **kwargs):
        if self.stop_reason:
            raise RuntimeError('Live worker stopped: audit required')
        outcome = super().review(*args, **kwargs)
        if outcome.error_code or self.ledger.records[-1]['state'] != 'settled':
            self.stop_reason = 'provider_error' if outcome.error_code else 'unknown_usage'
        return outcome


@contextmanager
def single_database_consumer(engine):
    # Different ledger paths still cannot run two budgeted consumers against one DB.
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        if not connection.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': LOCK_KEY}):
            raise RuntimeError('Budgeted worker is already running for this database')
        connection.commit()
        guard = DatabaseConsumerGuard(connection)
        try:
            yield guard
        finally:
            guard.release()


def run(engine, provider, *, max_stages=100, max_seconds=600, poll_seconds=1):
    from app.workers.reviews import process_once
    processed, deadline = 0, time.monotonic() + max_seconds
    while processed < max_stages and time.monotonic() < deadline:
        try:
            provider.check_ownership()
            processed += bool(process_once(engine, provider=provider))
        except DatabaseLockLost:
            return 2
        if provider.stop_reason:
            return 2
        if provider.ledger.spent >= provider.ledger.limit:
            return 2
        time.sleep(poll_seconds)
    return 0


def main(argv=None, *, on_ready=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--ordinary-worker-stopped', action='store_true')
    parser.add_argument('--ledger', type=Path)
    parser.add_argument('--budget-usd', default='2')
    parser.add_argument('--increase-budget-from', help='Amend persisted total ceiling only; no provider calls')
    parser.add_argument('--max-stages', type=int, default=100)
    parser.add_argument('--max-seconds', type=int, default=600)
    args = parser.parse_args(argv)
    if not args.live or not args.ordinary_worker_stopped or args.ledger is None:
        parser.error('Require --live, --ordinary-worker-stopped and persistent --ledger; disable ordinary ai-worker first')
    if args.max_stages < 1 or args.max_seconds < 1:
        parser.error('Stage and time bounds must be positive')
    from app.core.config import settings
    from app.core.db import get_engine
    from app.modules.ai_review.provider import OpenAIReviewProvider
    if settings.openai_api_key is None and args.increase_budget_from is None:
        parser.error('OPENAI_API_KEY is required in the local environment')
    config = dict(models=[settings.ai_light_model, settings.ai_model, settings.ai_complex_model],
                  max_output_tokens=settings.ai_max_output_tokens,
                  complex_max_output_tokens=settings.ai_complex_max_output_tokens,
                  price_date=PRICE_DATE, budget_usd=str(Decimal(args.budget_usd)))
    if any(model not in PRICES for model in config['models']):
        parser.error('Unknown model pricing: no paid request is allowed')
    try:
        if args.increase_budget_from is not None:
            ledger = increase_budget(get_engine(), args.ledger,
                previous_limit=args.increase_budget_from, new_limit=args.budget_usd, config=config)
            print(f'Budget amendment recorded: total ceiling USD {ledger.limit}; historical spent/reserved USD {ledger.spent}. No provider calls.')
            return 0
        with exclusive_worker(args.ledger.with_suffix('.lock')):
            ledger = open_ledger(args.ledger, args.budget_usd)
            ledger.save()
            freeze_live_configuration(args.ledger, config)
            engine = get_engine()
            with single_database_consumer(engine) as guard:
                provider = DemoBudgetedProvider(OpenAIReviewProvider(
                    settings.openai_api_key.get_secret_value(), timeout=settings.ai_request_timeout_seconds,
                    max_output_tokens=settings.ai_max_output_tokens,
                    complex_max_output_tokens=settings.ai_complex_max_output_tokens), ledger,
                    lock_guard=guard,
                    max_output_tokens=settings.ai_max_output_tokens,
                    complex_max_output_tokens=settings.ai_complex_max_output_tokens)
                if on_ready is not None:
                    provider.check_ownership()
                    on_ready()
                result = run(engine, provider, max_stages=args.max_stages, max_seconds=args.max_seconds,
                             poll_seconds=settings.ai_review_poll_seconds)
                print(f'Live worker finished: budget spent/reserved USD {ledger.spent}; status {result}')
                return result
    except (RuntimeError, ValueError, OSError):
        # Do not dump SDK, connection, prompt or secret-bearing exception details.
        print('Live worker stopped. Audit the persistent ledger; ordinary ai-worker must remain disabled.')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
