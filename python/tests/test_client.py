"""Client tests against a mocked transport — no network, no extra dependencies."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from lingolix import (
    AsyncLingolix,
    AuthenticationError,
    InvalidAudioError,
    Lingolix,
    QuotaExceededError,
    ServiceUnavailableError,
)

KEY = "lx_test_key"

# A real-shaped v3 response, plus an unknown field the backend might add later.
OK_BODY = {
    "text": "Guten Morgen",
    "speaking_rate": 3.5,
    "accuracy": 0.87,
    "completeness": 1.0,
    "future_field": "ignored",
    "words": [
        {
            "text": "Guten",
            "accuracy": 0.9,
            "completeness": 1.0,
            "start_ms": 0.0,
            "end_ms": 400.0,
            "char_start": 0,
            "char_end": 5,
            "syllables": [
                {
                    "text": "Gu",
                    "expected_ipa": "ɡuː",
                    "detected_ipa": "ɡu",
                    "accuracy": 0.92,
                    "completeness": 1.0,
                    "pitch": "high",
                    "duration_ms": 200.0,
                    "start_ms": 0.0,
                    "end_ms": 200.0,
                    "is_missing": False,
                    "is_extra": False,
                    "future_field": "ignored",
                }
            ],
        }
    ],
}

QUOTA_BODY = {
    "detail": {
        "error": "quota_exceeded",
        "message": "Monthly quota exhausted.",
        "quota_percentage": 100.0,
        "remaining_minutes": 0.0,
        "plan": "free",
        "upgrade_url": "https://lingolix.com/api-portal/pricing",
    }
}


def make_client(handler, *, cls=Lingolix):
    """Build a client whose HTTP layer is `handler` instead of the network."""
    client = cls(KEY)
    transport = httpx.MockTransport(handler)
    inner = client._client
    client._client = type(inner)(
        base_url=inner.base_url, headers=inner.headers, transport=transport
    )
    return client


def test_request_shape():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.content.decode("utf-8", "replace")
        return httpx.Response(200, json=OK_BODY)

    with make_client(handler) as client:
        client.check(b"RIFFfake", sentence="Guten Morgen", language="de")

    assert seen["url"] == "https://api.lingolix.com/api/pronunciation/v3/check"
    assert seen["auth"] == f"Bearer {KEY}"
    assert 'name="speechdata"' in seen["body"]
    assert 'name="sentence"' in seen["body"] and "Guten Morgen" in seen["body"]
    assert 'name="language_code"' in seen["body"] and "de" in seen["body"]


def test_sentence_omitted_when_none():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode("utf-8", "replace")
        return httpx.Response(200, json=OK_BODY)

    with make_client(handler) as client:
        client.check(b"RIFFfake")

    assert 'name="sentence"' not in seen["body"]
    assert 'name="language_code"' in seen["body"]


def test_parses_nested_result_and_ignores_unknown_fields():
    with make_client(lambda r: httpx.Response(200, json=OK_BODY)) as client:
        result = client.check(b"RIFFfake", sentence="Guten Morgen", language="de")

    assert result.accuracy == 0.87
    assert result.text == "Guten Morgen"
    assert result.words[0].text == "Guten"
    syllable = result.words[0].syllables[0]
    assert syllable.expected_ipa == "ɡuː"
    assert syllable.pitch == "high"
    assert syllable.is_missing is False


def test_fluency_fields_and_overall_from_an_older_api():
    new = {**OK_BODY, "overall": 0.9, "fluency": 1.0, "target_speaking_rate": 3.0}
    new["words"] = [{**OK_BODY["words"][0], "hesitation_ms": 820.0}]
    with make_client(lambda r: httpx.Response(200, json=new)) as client:
        result = client.check(b"RIFFfake", sentence="Guten Morgen", language="de")
    assert (result.overall, result.fluency, result.target_speaking_rate) == (0.9, 1.0, 3.0)
    assert result.words[0].hesitation_ms == 820.0
    with make_client(lambda r: httpx.Response(200, json=OK_BODY)) as client:
        old = client.check(b"RIFFfake", sentence="Guten Morgen", language="de")
    assert (old.overall, old.fluency, old.words[0].hesitation_ms) == (0.87, None, None)


def test_quota_error_exposes_upgrade_url():
    handler = lambda r: httpx.Response(429, json=QUOTA_BODY)  # noqa: E731
    with make_client(handler) as client:
        with pytest.raises(QuotaExceededError) as excinfo:
            client.check(b"RIFFfake")

    err = excinfo.value
    assert err.status == 429
    assert err.plan == "free"
    assert err.upgrade_url == "https://lingolix.com/api-portal/pricing"
    assert "quota" in str(err).lower()


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, AuthenticationError),
        (400, InvalidAudioError),
        (503, ServiceUnavailableError),
    ],
)
def test_string_detail_errors(status, expected):
    handler = lambda r: httpx.Response(status, json={"detail": "nope"})  # noqa: E731
    with make_client(handler) as client:
        with pytest.raises(expected, match="nope"):
            client.check(b"RIFFfake")


def test_oversized_audio_rejected_before_request():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("request should not have been sent")

    with make_client(handler) as client:
        with pytest.raises(InvalidAudioError, match="10 MiB limit"):
            client.check(b"x" * (10 * 1024 * 1024 + 1))


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("LINGOLIX_API_KEY", raising=False)
    with pytest.raises(Exception, match="LINGOLIX_API_KEY"):
        Lingolix()


def test_file_path_upload(tmp_path):
    path = tmp_path / "sample.wav"
    path.write_bytes(b"RIFFfake")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode("utf-8", "replace")
        return httpx.Response(200, json=OK_BODY)

    with make_client(handler) as client:
        client.check(path, language="ja")

    assert "sample.wav" in seen["body"]
    assert "RIFFfake" in seen["body"]


def test_async_client():
    async def run():
        client = make_client(lambda r: httpx.Response(200, json=OK_BODY), cls=AsyncLingolix)
        async with client:
            return await client.check(b"RIFFfake", sentence="Guten Morgen", language="de")

    result = asyncio.run(run())
    assert result.accuracy == 0.87
    assert result.words[0].syllables[0].text == "Gu"


def test_async_quota_error():
    async def run():
        client = make_client(
            lambda r: httpx.Response(429, json=QUOTA_BODY), cls=AsyncLingolix
        )
        async with client:
            await client.check(b"RIFFfake")

    with pytest.raises(QuotaExceededError):
        asyncio.run(run())
