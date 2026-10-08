"""Fixed visible-work requirements; issued orders hold independent JSON snapshots."""
from copy import deepcopy

from app.modules.work_orders.schemas import WorkOrderTemplate


DEFINITIONS = {
    'visible_leak': {
        'id': 'visible_leak', 'version': 1, 'title': 'Устранение видимой течи',
        'initial_description': 'Устранить видимую течь и описать выполненную работу.',
        'instructions': [
            'Зафиксируйте видимое место течи на фото до работы.',
            'Опишите выполненную работу и снимите тот же участок после работы.',
            'Отметьте только проверенные видимые признаки; фото не подтверждает скрытое состояние или безопасность эксплуатации.',
        ],
        'checklist': [
            {'id': 'identify_leak', 'label': 'Видимое место течи указано и зафиксировано.', 'required': True},
            {'id': 'describe_repair', 'label': 'Выполненная работа по устранению течи описана.', 'required': True},
            {'id': 'inspect_result', 'label': 'Результат осмотрен визуально и зафиксирован.', 'required': True},
        ],
        'photo_requirements': {'before': 1, 'after': 1},
    },
    'visible_element': {
        'id': 'visible_element', 'version': 1, 'title': 'Восстановление видимого элемента',
        'initial_description': 'Восстановить видимый элемент и описать выполненную работу.',
        'instructions': [
            'Зафиксируйте видимый элемент и повреждение на фото до работы.',
            'Опишите восстановление и снимите тот же элемент после работы.',
            'Отметьте только проверенные видимые признаки; фото не подтверждает скрытое состояние или безопасность эксплуатации.',
        ],
        'checklist': [
            {'id': 'identify_element', 'label': 'Видимый элемент и повреждение указаны и зафиксированы.', 'required': True},
            {'id': 'describe_restoration', 'label': 'Выполненная работа по восстановлению описана.', 'required': True},
            {'id': 'inspect_result', 'label': 'Результат осмотрен визуально и зафиксирован.', 'required': True},
        ],
        'photo_requirements': {'before': 1, 'after': 1},
    },
}


def snapshot(template_id):
    return deepcopy(DEFINITIONS[template_id])


def list_templates():
    return [WorkOrderTemplate.model_validate(snapshot(template_id)) for template_id in DEFINITIONS]


def missing_evidence(saved_snapshot, saved_answers, before_count, after_count):
    """Validate persisted requirements, never a later live definition."""
    if saved_snapshot is None:
        return ['template_answers'] if saved_answers else []
    checklist = saved_snapshot['checklist']
    known = {item['id'] for item in checklist}
    checked = {item['id']: item['checked'] for item in saved_answers}
    missing = []
    if len(checked) != len(saved_answers) or set(checked) - known:
        missing.append('template_answers')
    if any(item['required'] and checked.get(item['id']) is not True for item in checklist):
        missing.append('template_checklist')
    requirements = saved_snapshot['photo_requirements']
    if before_count < requirements['before']:
        missing.append('before_photo')
    if after_count < requirements['after']:
        missing.append('after_photo')
    return missing
