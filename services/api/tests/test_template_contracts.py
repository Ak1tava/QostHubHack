from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.work_orders.schemas import SubmissionCreate, WorkOrderCreate


def order_body(**changes):
    body = dict(work_type="planned", description="Видимая течь",
                area_id=uuid4(), equipment_id=uuid4(), assignee_id=uuid4(),
                due_at=datetime.now(timezone.utc))
    return body | changes


def report_body(**changes):
    return dict(expected_version=1, assignment_version=1, work_description="Описание работ",
                fault_code_id=uuid4(), no_materials_used=True) | changes


@pytest.mark.parametrize("template_id", ["visible_leak", "visible_element", None])
def test_creation_accepts_only_known_optional_template_selection(template_id):
    assert WorkOrderCreate(**order_body(template_id=template_id)).template_id == template_id


def test_unknown_template_and_client_requirements_are_rejected():
    with pytest.raises(ValidationError):
        WorkOrderCreate(**order_body(template_id="hidden_safety_check"))
    with pytest.raises(ValidationError):
        WorkOrderCreate(**order_body(template_snapshot={"photo_requirements": {"after": 0}}))


def test_legacy_report_has_no_template_answers():
    assert SubmissionCreate(**report_body()).template_answers == []


def test_report_accepts_explicit_checkbox_boolean():
    answer = SubmissionCreate(**report_body(template_answers=[{"id": "inspect_result", "checked": True}]))
    assert answer.template_answers[0].checked is True


@pytest.mark.parametrize("checked", ["true", "false", 1, 0, None])
def test_report_does_not_coerce_checkbox_answers(checked):
    with pytest.raises(ValidationError):
        SubmissionCreate(**report_body(template_answers=[{"id": "inspect_result", "checked": checked}]))
