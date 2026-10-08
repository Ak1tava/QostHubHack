from types import SimpleNamespace

import pytest


def completed(**changes):
    return dict(status="completed", model="gpt-6.1-sol", is_mock=False,
                response_id="resp_verified", error_code=None, **changes)


@pytest.mark.parametrize("model,usage,expected", [
    ("rules", {}, "rules"),
    ("t18-prepared-demo-provider-v2", {"is_mock": True}, "prepared"),
    ("test-provider", {"is_mock": True}, "mock"),
    ("gpt-6.1-sol", {"is_mock": False, "calls": [completed()]}, "provider"),
    ("gpt-6.1-sol", {"is_mock": False}, "unknown"),
    ("gpt-6.1-sol", {"calls": [{**completed(), "response_id": None}]}, "unknown"),
    ("gpt-6.1-sol", {"calls": [{**completed(), "error_code": "invalid_output"}]}, "unknown"),
    ("gpt-6.1-sol", {"calls": [{**completed(), "status": "started"}]}, "unknown"),
    ("gpt-6.1-sol", {"calls": [{**completed(), "is_mock": True}]}, "unknown"),
    ("gpt-6-astra", {"calls": [completed()]}, "unknown"),
    ("gpt-6.1-sol", {"calls": [completed(), {**completed(), "error_code": "timeout"}]}, "unknown"),
    ("gpt-6.1-sol", {"calls": "invalid"}, "unknown"),
    ("gpt-6.1-sol", {"calls": [None]}, "unknown"),
    ("gpt-6.1-sol", None, "unknown"),
    ("t18-prepared-demo-provider-v2", {}, "unknown"),
])
def test_source_requires_evidence_of_successful_real_call(model, usage, expected):
    from app.modules.ai_review.views import review_source
    assert review_source(SimpleNamespace(model=model, usage=usage)) == expected


def test_human_review_can_still_have_provider_origin():
    from app.modules.ai_review.views import review_source
    review = SimpleNamespace(model="gpt-6.1-sol", verdict="human_review",
                             usage={"calls": [completed()]})
    assert review_source(review) == "provider"
