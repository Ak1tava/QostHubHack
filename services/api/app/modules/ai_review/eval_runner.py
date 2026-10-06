"""Synthetic-only, budgeted evaluation. No live requests without --live and a key."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, prompt_payload
from .provider import OpenAIReviewProvider
from .rules import RULES_VERSION
from .schemas import ImageEvidence, ProviderOutcome, ReviewInput, StageResponse
from .service import evaluate_submission

ROOT = Path(__file__).resolve().parents[5]
# Standard long-context/cache-write upper rates + 10% regional uplift.
# Verified 2026-10-06 https://developers.openai.com/api/docs/pricing
PRICES = {'gpt-6.1-sol': ('5.50', '16.50'), 'gpt-6-astra': ('27.50', '82.50'), 'gpt-6-luna': ('0.275', '0.825')}
PRICE_DATE = '2026-10-06'
IMAGE_TOKEN_RESERVE = 32768  # Conservative at <=1024 pixels; no low-detail discount.


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def write_json(path: Path, value, *, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open('x', encoding='utf-8') as target:
            target.write(json_text(value))
            target.flush()
            os.fsync(target.fileno())
        return
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as target:
        target.write(json_text(value))
        target.flush()
        os.fsync(target.fileno())
    for attempt in range(5):
        try:
            temporary.replace(path)
            return
        except PermissionError as error:
            if getattr(error, 'winerror', None) not in {5, 32, 33} or attempt == 4:
                raise
            time.sleep(0.05 * 2 ** attempt)


def safe_fixture_path(evals: Path, relative: str) -> Path:
    path = (evals / relative).resolve()
    root = (evals / 'fixtures').resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Fixture must resolve within fixtures directory')
    return path


def load_case_input(evals: Path, case: dict) -> tuple[ReviewInput, dict[str, ImageEvidence]]:
    import resvg_py
    from io import BytesIO
    from PIL import Image

    fixture = json.loads(safe_fixture_path(evals, case['input_fixture']).read_text(encoding='utf-8'))
    if fixture.get('synthetic') is not True:
        raise ValueError('Eval runner accepts only synthetic fixtures')
    # Select only C5 input, never scenario/variant/provenance/answers/forbidden findings.
    raw = fixture['review_input']
    images = {}
    photos = []
    for source in raw['photo_refs']:
        path = safe_fixture_path(evals, source['fixture_path'])
        if path.suffix.lower() != '.svg':
            raise ValueError('Synthetic eval media must be SVG')
        svg = path.read_text(encoding='utf-8')
        if 'SYNTHETIC' not in svg or 'href=' in svg.lower() or '<!entity' in svg.lower():
            raise ValueError('SVG must be synthetic and contain no external resources')
        png = resvg_py.svg_to_bytes(svg_string=svg, width=1024, log_information=False)
        with Image.open(BytesIO(png)) as decoded:
            decoded.thumbnail((1024, 1024))
            normalized = BytesIO()
            decoded.convert('RGB').save(normalized, format='PNG')
        images[source['id']] = ImageEvidence(media_type='image/png', data=normalized.getvalue())
        photos.append({key: value for key, value in source.items() if key != 'fixture_path'})
    return ReviewInput.model_validate({**raw, 'photo_refs': photos}), images


def corpus_hash(evals: Path) -> str:
    digest = hashlib.sha256()
    paths = [evals / 'cases.jsonl', *sorted((evals / 'fixtures').rglob('*'))]
    for path in paths:
        if path.is_file():
            digest.update(path.relative_to(evals).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def frozen_config(evals: Path) -> dict:
    from app.core.config import settings

    source = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        source.update(path.name.encode())
        source.update(path.read_bytes())
    return {'corpus_hash': corpus_hash(evals), 'provider_source_hash': source.hexdigest(),
            'prompt_version': PROMPT_VERSION, 'rules_version': RULES_VERSION,
            'models': {'light': settings.ai_light_model, 'primary': settings.ai_model or 'gpt-6.1-sol', 'complex': settings.ai_complex_model},
            'reasoning': {'light': settings.ai_light_reasoning_effort, 'primary': settings.ai_reasoning_effort, 'complex': settings.ai_complex_reasoning_effort},
            'timeout_seconds': settings.ai_request_timeout_seconds,
            'max_output_tokens': settings.ai_max_output_tokens, 'complex_max_output_tokens': settings.ai_complex_max_output_tokens,
            'prices_per_million_conservative': {model: list(prices) for model, prices in PRICES.items()},
            'price_date': PRICE_DATE, 'image_token_reserve': IMAGE_TOKEN_RESERVE,
            'openai_sdk': importlib.metadata.version('openai'), 'resvg_py': importlib.metadata.version('resvg-py'),
            'schema_hash': hashlib.sha256(json_text(StageResponse.model_json_schema()).encode()).hexdigest()}


def freeze_configuration(directory: Path, config: dict):
    path = directory / 'frozen.json'
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != config:
            raise ValueError('Frozen configuration changed; holdout cannot be reused for tuning')
        return
    write_json(path, config, exclusive=True)


def claim_holdout(directory: Path, config: dict):
    path = directory / 'frozen.json'
    if not path.exists() or json.loads(path.read_text(encoding='utf-8')) != config:
        raise ValueError('Freeze dev configuration and corpus before the holdout run')
    write_json(directory / 'holdout.started.json', {'started_at': datetime.now(timezone.utc).isoformat(), 'config': config}, exclusive=True)


@contextmanager
def exclusive_run(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'evaluation.lock'
    with path.open('x', encoding='utf-8') as marker:
        marker.write(str(os.getpid()))
    try:
        yield
    finally:
        path.unlink()


class BudgetExceeded(RuntimeError):
    pass


def load_dev_checkpoint(path: Path, config: dict, selected_case_ids: set[str], previous_source_hash=None):
    saved = json.loads(path.read_text(encoding='utf-8'))
    if saved.get('mode') != 'live':
        raise ValueError('Only a live dev checkpoint can be resumed')
    previous = saved['config']
    history = list(saved.get('previous_configs', []))
    if previous != config:
        old_hash = previous.get('provider_source_hash')
        compatible = {**previous, 'provider_source_hash': config.get('provider_source_hash')} == config
        if not previous_source_hash or previous_source_hash != old_hash or not compatible:
            raise ValueError('Dev configuration changed; source transition must be explicit and other fields identical')
        history.append(previous)
    elif previous_source_hash is not None and previous_source_hash != previous.get('provider_source_hash'):
        raise ValueError('Declared previous source hash does not match the checkpoint')
    rows = saved['rows']
    ids = [row['case_id'] for row in rows]
    if len(ids) != len(set(ids)) or not set(ids) <= selected_case_ids:
        raise ValueError('Checkpoint contains duplicate or unrelated cases')
    return rows, history


class BudgetLedger:
    def __init__(self, path: Path, limit='5'):
        self.path = path
        self.limit = Decimal(limit)
        if not Decimal('0') < self.limit <= Decimal('5'):
            raise ValueError('Total eval budget must be >0 and <=5 USD')
        self.records = json.loads(path.read_text(encoding='utf-8'))['calls'] if path.exists() else []

    @property
    def spent(self) -> Decimal:
        return sum((Decimal(r['charged_usd']) for r in self.records), Decimal('0'))

    def reserve(self, call_id: str, amount, metadata=None):
        amount = Decimal(amount)
        if not amount.is_finite() or amount <= 0:
            raise ValueError('Reservation must be finite and positive')
        if self.spent + amount > self.limit:
            raise BudgetExceeded('Remaining budget cannot cover this complete bounded call')
        if any(r['call_id'] == call_id for r in self.records):
            raise ValueError('Call id already reserved')
        self.records.append({'call_id': call_id, 'reserved_usd': str(amount), 'charged_usd': str(amount),
                             'state': 'reserved', 'metadata': metadata or {}})
        self.save()

    def settle(self, call_id: str, actual, metadata=None):
        record = next(r for r in self.records if r['call_id'] == call_id)
        if metadata is not None:
            record['metadata'] = metadata
        if actual is not None:
            amount = Decimal(actual)
            if not amount.is_finite() or amount < 0:
                raise ValueError('Cost must be finite and nonnegative')
            record['charged_usd'] = str(amount)
            if amount > Decimal(record['reserved_usd']):
                record['state'] = 'bound_exceeded'
                self.save()
                raise BudgetExceeded('Observed usage exceeded conservative reservation; stop and audit pricing')
        record['state'] = 'settled' if actual is not None else 'unknown_usage_reserved'
        self.save()

    def save(self):
        write_json(self.path, {'limit_usd': str(self.limit), 'spent_or_reserved_usd': str(self.spent), 'calls': self.records})


def persisted_calls(ledger: BudgetLedger, case_ids: set[str]) -> list[dict]:
    calls = []
    for record in ledger.records:
        metadata = record['metadata']
        if metadata.get('case_id') not in case_ids:
            continue
        calls.append({'call_id': record['call_id'], 'usage': {}, 'latency_ms': 0,
                      'error_code': 'interrupted_call', 'is_mock': False, 'response_id': None,
                      'reserved_usd': record['reserved_usd'], 'estimated_cost_usd': None, **metadata})
    return calls


def usage_cost(model: str, usage: dict[str, int]) -> Decimal | None:
    if 'input_tokens' not in usage or 'output_tokens' not in usage:
        return None
    input_price, output_price = (Decimal(p) for p in PRICES[model])
    return (Decimal(usage['input_tokens']) * input_price + Decimal(usage['output_tokens']) * output_price) / Decimal(1_000_000)


class BudgetedProvider:
    def __init__(self, provider, ledger: BudgetLedger, max_output_tokens=4096, complex_max_output_tokens=8192):
        self.provider = provider
        self.ledger = ledger
        self.max_output_tokens = max_output_tokens
        self.complex_max_output_tokens = complex_max_output_tokens
        self.calls = []
        self.case_id = None

    def review(self, value, plan, *, images, previous=None) -> ProviderOutcome:
        if plan.model not in PRICES:
            raise ValueError('Unknown model pricing: no paid request is allowed')
        input_price, output_price = (Decimal(p) for p in PRICES[plan.model])
        # UTF8 bytes are an upper bound for byte-BPE text tokens; include schema + wrappers.
        text_bytes = len((SYSTEM_PROMPT + prompt_payload(value, plan, previous) + json_text(StageResponse.model_json_schema())).encode('utf-8'))
        image_tokens = sum(max(IMAGE_TOKEN_RESERVE, len(image.data) * 2) for image in images.values())
        cap = self.complex_max_output_tokens if plan.stage == 'escalation' else self.max_output_tokens
        reservation = (Decimal(text_bytes + image_tokens + 4096) * input_price + Decimal(cap) * output_price) / Decimal(1_000_000)
        call_id = str(uuid4())
        self.ledger.reserve(call_id, reservation, {'case_id': self.case_id, **plan.model_dump(), 'state': 'calling'})
        outcome = self.provider.review(value, plan, images=images, previous=previous)
        actual = usage_cost(plan.model, outcome.usage)
        # Unknown transport/schema usage consumes the complete reservation, even after crash.
        record = {'call_id': call_id, 'case_id': self.case_id, **plan.model_dump(), 'usage': outcome.usage,
                  'latency_ms': outcome.latency_ms, 'error_code': outcome.error_code, 'is_mock': outcome.is_mock,
                  'response_id': outcome.response_id, 'reserved_usd': str(reservation),
                  'estimated_cost_usd': str(actual) if actual is not None else None}
        self.calls.append(record)
        self.ledger.settle(call_id, actual, record)
        return outcome


def metrics(rows: list[dict], calls: list[dict], spent: Decimal) -> dict:
    total = len(rows)
    latency = sorted(call['latency_ms'] for call in calls)
    count = lambda key: sum(bool(row.get(key)) for row in rows)
    return {'cases': total, 'verdict_accuracy': count('verdict_match') / total if total else None,
            'required_findings_recall': sum(row['required_found'] for row in rows) / max(1, sum(row['required_total'] for row in rows)),
            'false_acceptance': sum(row['verdict'] in {'accepted', 'accepted_with_notes'} and row['expected_verdict'] in {'requires_rework', 'human_review'} for row in rows),
            'false_rework': sum(row['verdict'] == 'requires_rework' and row['expected_verdict'] != 'requires_rework' for row in rows),
            'human_review': sum(row['verdict'] == 'human_review' for row in rows),
            'invalid_evidence_refs': sum(row['invalid_evidence_refs'] for row in rows),
            'forbidden_findings': sum(len(row['forbidden_findings']) for row in rows),
            'schema_refusal_api_errors': dict(Counter(call['error_code'] for call in calls if call['error_code'])),
            'calls_by_model': dict(Counter(call['model'] for call in calls)),
            'input_tokens': sum(call['usage'].get('input_tokens', 0) for call in calls),
            'output_tokens': sum(call['usage'].get('output_tokens', 0) for call in calls),
            'reasoning_tokens': sum(call['usage'].get('reasoning_tokens', 0) for call in calls),
            'call_latency_p50_ms': latency[len(latency) // 2] if latency else None,
            'call_latency_p95_ms': latency[min(len(latency) - 1, int(len(latency) * .95))] if latency else None,
            'spent_or_reserved_usd': str(spent), 'is_live': bool(calls) and not any(call['is_mock'] for call in calls)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--freeze', action='store_true', help='Freeze source/config/corpus without any model call')
    parser.add_argument('--split', choices=('dev', 'holdout'), default='dev')
    parser.add_argument('--evals-dir', type=Path, default=ROOT / 'evals')
    parser.add_argument('--output-dir', type=Path, default=ROOT / '.tooling' / 't07' / 'evals')
    parser.add_argument('--resume-dev', action='store_true', help='Resume completed live dev cases; never resume holdout')
    parser.add_argument('--resume-from-source-hash', help='Explicit previous dev source hash after a compatible recovery fix')
    args = parser.parse_args(argv)
    if args.resume_dev and (not args.live or args.split != 'dev' or args.freeze):
        parser.error('--resume-dev requires --live --split dev and cannot freeze or resume holdout')
    if args.resume_from_source_hash and not args.resume_dev:
        parser.error('--resume-from-source-hash requires --resume-dev')
    from app.core.config import settings

    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else os.environ.get('OPENAI_API_KEY')
    if args.live and not key:
        print('BLOCKED: OPENAI_API_KEY отсутствует; модельных вызовов нет.', file=sys.stderr)
        return 2
    if args.split == 'holdout' and not args.live and not args.freeze:
        print('Holdout разрешён только один раз после --freeze, с --live.', file=sys.stderr)
        return 2
    try:
        config = frozen_config(args.evals_dir)
        # Changing result destination must not reset the shared $5 or holdout guards.
        state_directory = ROOT / '.tooling' / 't07' / 'evals'
        with exclusive_run(state_directory):
            if args.freeze:
                freeze_configuration(state_directory, config)
                print('Конфигурация и корпус зафиксированы; вызовов нет.')
                return 0
            if args.split == 'holdout':
                claim_holdout(state_directory, config)
            cases = [json.loads(line) for line in (args.evals_dir / 'cases.jsonl').read_text(encoding='utf-8').splitlines()]
            selected = [case for case in cases if case['split'] == args.split]
            case_ids = {case['case_id'] for case in selected}
            rows, previous_configs = [], []
            if args.resume_dev:
                if (state_directory / 'holdout.started.json').exists():
                    raise ValueError('Dev cannot be resumed after holdout has started')
                rows, previous_configs = load_dev_checkpoint(args.output_dir / 'dev.results.json', config,
                    case_ids, args.resume_from_source_hash)
                completed = {row['case_id'] for row in rows}
                selected = [case for case in selected if case['case_id'] not in completed]
            ledger = BudgetLedger(state_directory / 'budget.json')
            provider = BudgetedProvider(OpenAIReviewProvider(key, timeout=settings.ai_request_timeout_seconds,
                max_output_tokens=settings.ai_max_output_tokens, complex_max_output_tokens=settings.ai_complex_max_output_tokens),
                ledger, settings.ai_max_output_tokens, settings.ai_complex_max_output_tokens) if args.live else None
            aborted = False
            for case in selected:
                value, images = load_case_input(args.evals_dir, case)
                if provider:
                    provider.case_id = case['case_id']
                try:
                    result = evaluate_submission(value, provider, images)
                except BudgetExceeded:
                    aborted = True
                    break
                codes = {finding.code for finding in result.findings}
                fixture = json.loads(safe_fixture_path(args.evals_dir, case['input_fixture']).read_text(encoding='utf-8'))
                rows.append({'case_id': case['case_id'], 'verdict': result.verdict, 'expected_verdict': case['expected_verdict'],
                    'verdict_match': result.verdict == case['expected_verdict'], 'required_total': len(case['required_findings']),
                    'required_found': len(codes & set(case['required_findings'])),
                    'forbidden_findings': sorted(codes & set(fixture['forbidden_findings'])),
                    'invalid_evidence_refs': sum(ref not in value.evidence_ids() for f in result.findings for ref in f.evidence_refs),
                    'result': result.model_dump(mode='json')})
                calls = persisted_calls(ledger, case_ids) if provider else []
                write_json(args.output_dir / f'{args.split}.results.json', {'mode': 'live' if args.live else 'rules_only',
                    'config': config, 'previous_configs': previous_configs, 'rows': rows, 'calls': calls,
                    'metrics': metrics(rows, calls, ledger.spent), 'aborted_budget': False})
            calls = persisted_calls(ledger, case_ids) if provider else []
            aggregate = metrics(rows, calls, ledger.spent)
            write_json(args.output_dir / f'{args.split}.results.json', {'mode': 'live' if args.live else 'rules_only', 'config': config,
                'previous_configs': previous_configs, 'rows': rows, 'calls': calls, 'metrics': aggregate, 'aborted_budget': aborted})
            print(json_text(aggregate))
            return 3 if aborted else 0
    except (ValueError, FileExistsError) as error:
        print(f'Eval остановлен: {error}', file=sys.stderr)
        return 2
    except OSError as error:
        print(f'Eval остановлен: ошибка файловой системы ({type(error).__name__}, {getattr(error, "winerror", error.errno)}).', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
