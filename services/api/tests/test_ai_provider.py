import base64
from types import SimpleNamespace as NS

import pytest

from test_ai_review import review


def text_review():
    return review(photo_refs=[], problem='Плановый наряд: сверка журнала', checklist=[{'id': 'check_report', 'code': 'report_fields', 'complete': True}])


def parsed_response(**changes):
    raw = dict(status='completed', id='resp_test', output=[], usage=NS(input_tokens=12, output_tokens=9, total_tokens=21, input_tokens_details=NS(cached_tokens=0), output_tokens_details=NS(reasoning_tokens=2)), output_parsed={
        'result': {'verdict': 'accepted', 'score': 5, 'findings': [], 'missing_evidence': [], 'limitations': []},
        'unresolved_conflict': False, 'conflict_refs': [], 'legible_refs': [],
    })
    raw.update(changes)
    return NS(**raw)


class Client:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.responses = self

    def parse(self, **kwargs):
        self.requests.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_sdk_parse_uses_strict_schema_and_stateless_bounded_request():
    from app.modules.ai_review.provider import OpenAIReviewProvider
    from app.modules.ai_review.schemas import StagePlan, StageResponse

    client = Client(parsed_response())
    provider = OpenAIReviewProvider('test-key', client=client)
    outcome = provider.review(text_review(), StagePlan(stage='primary', model='gpt-6-luna', reasoning='low'), images={})
    assert outcome.result.verdict == 'accepted'
    assert outcome.usage == {'input_tokens': 12, 'output_tokens': 9, 'total_tokens': 21, 'cached_tokens': 0, 'reasoning_tokens': 2}
    call = client.requests[0]
    assert call['text_format'] is StageResponse
    assert call['store'] is False
    assert call['max_output_tokens'] == 4096
    assert call['reasoning'] == {'effort': 'low'}
    assert StageResponse.model_json_schema()['additionalProperties'] is False


@pytest.mark.parametrize('response,error', [
    (parsed_response(status='incomplete'), 'incomplete'),
    (parsed_response(output=[NS(type='message', content=[NS(type='refusal', refusal='No')])], output_parsed=None), 'refusal'),
    (parsed_response(output_parsed=None), 'schema_error'),
    (parsed_response(output_parsed={'not': 'the schema'}), 'schema_error'),
])
def test_refusal_incomplete_schema_are_distinct_nonretryable_errors(response, error):
    from app.modules.ai_review.provider import OpenAIReviewProvider
    from app.modules.ai_review.schemas import StagePlan

    outcome = OpenAIReviewProvider('test-key', client=Client(response)).review(text_review(), StagePlan(stage='primary', model='gpt-6.1-sol', reasoning='medium'), images={})
    assert outcome.error_code == error and outcome.result is None
    assert not outcome.retryable and not outcome.unresolved_conflict
    assert outcome.usage['total_tokens'] == 21


def test_missing_actual_image_does_not_certify_from_photo_descriptions():
    from app.modules.ai_review.provider import OpenAIReviewProvider
    from app.modules.ai_review.schemas import StagePlan

    client = Client(parsed_response())
    outcome = OpenAIReviewProvider('test-key', client=client).review(review(), StagePlan(stage='primary', model='gpt-6.1-sol', reasoning='medium'), images={})
    assert outcome.error_code == 'image_unavailable'
    assert client.requests == []


def test_raster_image_encoded_locally_no_urls_or_fixture_metadata_leak():
    from app.modules.ai_review.provider import OpenAIReviewProvider
    from app.modules.ai_review.schemas import ImageEvidence, StagePlan
    from io import BytesIO
    from PIL import Image

    image = BytesIO()
    Image.new('RGB', (8, 8), 'white').save(image, format='PNG')
    value = review()
    client = Client(parsed_response())
    outcome = OpenAIReviewProvider('test-key', client=client).review(value, StagePlan(stage='primary', model='gpt-6.1-sol', reasoning='medium'), images={p['id']: ImageEvidence(media_type='image/png', data=image.getvalue()) for p in value.photo_refs})
    assert outcome.error_code is None
    content = client.requests[0]['input'][0]['content']
    pictures = [item for item in content if item['type'] == 'input_image']
    assert len(pictures) == 2
    assert all(p['image_url'].startswith('data:image/png;base64,') for p in pictures)
    assert 'fixture_path' not in content[0]['text']
    assert 'expected_verdict' not in content[0]['text']


def test_non_image_bytes_fail_before_call():
    from app.modules.ai_review.provider import OpenAIReviewProvider
    from app.modules.ai_review.schemas import ImageEvidence, StagePlan

    client = Client(parsed_response())
    outcome = OpenAIReviewProvider('test-key', client=client).review(review(), StagePlan(stage='primary', model='gpt-6.1-sol', reasoning='medium'), images={p['id']: ImageEvidence(media_type='image/png', data=b'<svg>ignored</svg>') for p in review().photo_refs})
    assert outcome.error_code == 'invalid_image'
    assert client.requests == []


def test_transient_error_exposes_retry_after_without_retrying_sdk():
    import httpx
    import openai
    from app.modules.ai_review.provider import OpenAIReviewProvider
    from app.modules.ai_review.schemas import StagePlan

    response = httpx.Response(429, headers={'retry-after': '7'}, request=httpx.Request('POST', 'https://api.openai.com/v1/responses'))
    error = openai.RateLimitError('rate limit', response=response, body={})
    client = Client(error)
    outcome = OpenAIReviewProvider('test-key', client=client).review(text_review(), StagePlan(stage='primary', model='gpt-6.1-sol', reasoning='medium'), images={})
    assert outcome.retryable and outcome.retry_after_seconds == 7
    assert outcome.error_code == 'api_error' and outcome.result is None
    assert len(client.requests) == 1


def test_sdk_schema_parse_failure_retains_raw_billed_usage():
    from pydantic import ValidationError
    from app.modules.ai_review.provider import OpenAIReviewProvider
    from app.modules.ai_review.schemas import StagePlan, StageResponse

    class Raw:
        def json(self):
            return {'id': 'resp_bad', 'usage': {'input_tokens': 40, 'output_tokens': 20, 'total_tokens': 60}}

        def parse(self):
            StageResponse.model_validate({'bad': True})

    client = Client(Raw())
    client.with_raw_response = client
    outcome = OpenAIReviewProvider('test-key', client=client).review(text_review(), StagePlan(stage='primary', model='gpt-6.1-sol', reasoning='medium'), images={})
    assert outcome.error_code == 'schema_error'
    assert outcome.usage['total_tokens'] == 60
    assert outcome.response_id == 'resp_bad'


def test_real_sdk_http_boundary_has_no_automatic_retries(monkeypatch):
    import json
    import httpx2
    import openai
    from app.modules.ai_review.provider import OpenAIReviewProvider
    from app.modules.ai_review.schemas import StagePlan

    actual_client = openai.OpenAI
    received = []

    def handler(request):
        received.append(json.loads(request.content))
        return httpx2.Response(500, json={'error': {'message': 'synthetic failure', 'type': 'server_error'}})

    def factory(**kwargs):
        return actual_client(**kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))

    monkeypatch.setattr(openai, 'OpenAI', factory)
    provider = OpenAIReviewProvider('test-key')
    outcome = provider.review(text_review(), StagePlan(stage='primary', model='gpt-6.1-sol', reasoning='medium'), images={})
    assert outcome.retryable and outcome.error_code == 'api_error'
    assert len(received) == 1
    payload = received[0]
    assert payload['store'] is False
    assert payload['text']['format']['strict'] is True
    assert payload['max_output_tokens'] == 4096
    assert payload['service_tier'] == 'default'


def test_real_sdk_completed_parse_preserves_raw_usage(monkeypatch):
    import json
    import httpx2
    import openai
    from app.modules.ai_review.provider import OpenAIReviewProvider
    from app.modules.ai_review.schemas import StagePlan

    actual_client = openai.OpenAI
    envelope = parsed_response().output_parsed

    def handler(request):
        body = {'id': 'resp_sdk', 'created_at': 0, 'object': 'response', 'status': 'completed',
                'model': 'gpt-6.1-sol', 'output': [{'id': 'msg_sdk', 'type': 'message', 'role': 'assistant', 'status': 'completed',
                    'content': [{'type': 'output_text', 'text': json.dumps(envelope), 'annotations': []}]}],
                'usage': {'input_tokens': 25, 'output_tokens': 14, 'total_tokens': 39}}
        return httpx2.Response(200, json=body)

    monkeypatch.setattr(openai, 'OpenAI', lambda **kwargs: actual_client(**kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))))
    outcome = OpenAIReviewProvider('test-key').review(text_review(), StagePlan(stage='primary', model='gpt-6.1-sol', reasoning='medium'), images={})
    assert outcome.result.verdict == 'accepted'
    assert outcome.response_id == 'resp_sdk'
    assert outcome.usage['total_tokens'] == 39


def test_real_sdk_truncated_incomplete_is_not_schema_error(monkeypatch):
    import httpx2
    import openai
    from app.modules.ai_review.provider import OpenAIReviewProvider
    from app.modules.ai_review.schemas import StagePlan

    actual_client = openai.OpenAI

    def handler(request):
        return httpx2.Response(200, json={'id': 'resp_incomplete', 'created_at': 0, 'object': 'response', 'status': 'incomplete',
            'model': 'gpt-6.1-sol', 'incomplete_details': {'reason': 'max_output_tokens'},
            'output': [{'id': 'msg', 'type': 'message', 'role': 'assistant', 'status': 'incomplete',
                'content': [{'type': 'output_text', 'text': '{"result":', 'annotations': []}]}],
            'usage': {'input_tokens': 25, 'output_tokens': 4096, 'total_tokens': 4121}})

    monkeypatch.setattr(openai, 'OpenAI', lambda **kwargs: actual_client(**kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))))
    outcome = OpenAIReviewProvider('test-key').review(text_review(), StagePlan(stage='primary', model='gpt-6.1-sol', reasoning='medium'), images={})
    assert outcome.error_code == 'incomplete'
    assert outcome.usage['output_tokens'] == 4096
    assert not outcome.retryable


@pytest.mark.parametrize('score', [True, '5', 4.5])
def test_score_requires_a_json_integer_not_coercible_input(score):
    from app.modules.ai_review.provider import OpenAIReviewProvider
    from app.modules.ai_review.schemas import StagePlan

    response = parsed_response()
    response.output_parsed['result']['score'] = score
    outcome = OpenAIReviewProvider('test-key', client=Client(response)).review(text_review(), StagePlan(stage='primary', model='gpt-6.1-sol', reasoning='medium'), images={})
    assert outcome.error_code == 'schema_error'
