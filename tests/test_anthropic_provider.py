from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest

from app.services import ai_provider
from tests.test_ai import IDS, good_output


def msg(text, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])


def provider(responses, calls):
    p = ai_provider.AnthropicProvider("k", "claude-haiku-5-5", 4000, 10, 2)
    it = iter(responses)

    def create(**kwargs):
        calls.append(kwargs)
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r

    p.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return p


def status_error(cls, code):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("err", response=httpx.Response(code, request=req), body=None)


def test_request_shape_uses_structured_output():
    calls = []
    res = provider([msg(good_output())], calls).explain("ctx", IDS)
    kw = calls[0]
    assert kw["model"] == "claude-haiku-5-5" and kw["max_tokens"] == 4000
    fmt = kw["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["properties"]["explanations"]["items"]["properties"]["recommendation_id"]["enum"] == IDS
    assert kw["output_config"]["effort"] == "low"
    assert kw["system"] == ai_provider.SYSTEM_PROMPT
    assert [e.recommendation_id for e in res.explanation.explanations] == IDS


def test_invalid_output_then_retry_succeeds():
    calls = []
    res = provider([msg(good_output(IDS + ["XX-invented"])), msg(good_output())], calls).explain("ctx", IDS)
    assert res.attempts == 2 and len(calls) == 2


def test_refusal_and_truncation():
    with pytest.raises(ai_provider.AIUnavailable) as ei:
        provider([msg("", "refusal")], []).explain("ctx", IDS)
    assert ei.value.code == "ai_refused"
    with pytest.raises(ai_provider.AIUnavailable) as ei:
        provider([msg("{", "max_tokens"), msg("{", "max_tokens")], []).explain("ctx", IDS)
    assert ei.value.code == "ai_failed" and "output limit" in ei.value.message


def test_auth_error_not_retried():
    calls = []
    with pytest.raises(ai_provider.AIUnavailable) as ei:
        provider([status_error(anthropic.AuthenticationError, 401)], calls).explain("ctx", IDS)
    assert ei.value.code == "ai_misconfigured" and len(calls) == 1


def test_rate_limit_and_server_errors_bounded():
    calls = []
    with pytest.raises(ai_provider.AIUnavailable) as ei:
        provider([status_error(anthropic.RateLimitError, 429), status_error(anthropic.InternalServerError, 500)], calls).explain("ctx", IDS)
    assert ei.value.code == "ai_failed" and len(calls) == 2


def test_provider_factory(app):
    from app.routes import ai as ai_route

    with app.app_context():
        assert isinstance(ai_route.get_provider(), ai_provider.AnthropicProvider)
