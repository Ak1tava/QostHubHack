"""These checks consume trusted server facts, never client supplied checks."""
from decimal import Decimal, InvalidOperation
import re

from .schemas import Finding, ReviewInput, ReviewResult, RuleAssessment

RULES_VERSION = 't07-rules-v1'


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def assess_rules(value: ReviewInput) -> RuleAssessment:
    findings: list[Finding] = []
    missing: list[str] = []
    human = False
    anomalies = False
    limitations = ['ИИ не подтверждает скрытые дефекты и безопасность запуска. Решение принимает мастер.']

    def add(code, message, refs, severity='warning'):
        findings.append(Finding(code=code, severity=severity, message=message, evidence_refs=refs))

    # An explanatory signal for obvious attacks; safety never depends on this heuristic.
    attack = re.compile(r'(игнориру[йя].{0,40}инструкц|ignore.{0,40}instructions|автоматически\s+закро[йе])', re.IGNORECASE)
    texts = [('problem', value.problem), ('work_description', value.work_description)]
    texts.extend((p['id'], str(p.get('untrusted_caption', p.get('caption', '')))) for p in value.photo_refs)
    for ref, text in texts:
        if attack.search(text):
            add('untrusted_instruction_ignored', 'Встроенная команда обработана как недоверенные данные.', [ref], 'info')

    if not value.work_description.strip():
        add('missing_work_description', 'Отсутствует описание выполненных работ.', ['work_description'], 'error')
        missing.append('work_description')
    after = [photo for photo in value.photo_refs if photo.get('phase') == 'after']
    for check in value.checklist:
        if check.get('code') == 'mandatory_after_photo' and check.get('required', True) and not after:
            add('missing_required_photo', 'Не приложено обязательное фото после выполнения.', [check['id']], 'error')
            missing.append(check['id'])
        elif check.get('required', True) and check.get('complete') is False:
            add('report_incomplete', 'Обязательные поля отчёта не заполнены.', [check['id']], 'error')
            missing.append(check['id'])
    if not missing:
        add('report_complete', 'Обязательные поля отчёта заполнены.', ['work_description'], 'info')

    fingerprints: dict[str, str] = {}
    for photo in value.photo_refs:
        ref = photo['id']
        fingerprint = photo.get('content_fingerprint')
        if photo.get('duplicate_of') or (fingerprint and fingerprint in fingerprints):
            add('duplicate_evidence', 'Фото повторяет ранее предоставленное доказательство.', [ref])
            human = True
        if fingerprint:
            fingerprints[fingerprint] = ref
        if photo.get('quality') == 'unusable':
            add('photo_unusable', 'По фото нельзя проверить видимый результат.', [ref])
            human = True
    if human:
        add('completion_unverified', 'Результат требует проверки мастером.', [photo['id'] for photo in after])

    for material in value.material_checks:
        norm = number(material.get('norm_quantity'))
        quantity = number(material.get('quantity'))
        if norm is None:
            add('norm_unavailable', 'Сопоставимой нормы расхода нет; превышение не оценивается.', [material['id']])
        elif quantity is not None and norm >= 0 and quantity > norm:
            add('material_overuse', 'Расход выше сопоставимой нормы; требуется пояснение.', [material['id']])
            anomalies = True
    for timing in value.timing_checks:
        duration = number(timing.get('duration_minutes'))
        if timing.get('status') == 'inconsistent' or (duration is not None and duration < 0):
            add('timing_inconsistent', 'Журнал времени содержит противоречие.', [timing['id']])
            human = anomalies = True
        late = number(timing.get('late_minutes'))
        if late is not None and late > 0:
            add('late_submission', 'Отчёт сдан после срока; качество проверяется отдельно.', [timing['id']])
            anomalies = True

    result = None
    if missing or human:
        result = ReviewResult(verdict='requires_rework' if missing else 'human_review', score=None,
                              findings=findings, missing_evidence=list(dict.fromkeys(missing)), limitations=limitations)
    return RuleAssessment(result=result, findings=findings, limitations=limitations, anomalies=anomalies)
