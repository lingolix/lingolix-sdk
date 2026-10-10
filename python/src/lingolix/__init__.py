"""Lingolix pronunciation API client.

    from lingolix import Lingolix

    with Lingolix() as client:                    # key from $LINGOLIX_API_KEY
        r = client.check("audio.wav", sentence="Guten Morgen", language="de")
        print(r.accuracy)

Async is the same with ``AsyncLingolix`` and ``await``.
"""

from __future__ import annotations

import dataclasses
import mimetypes
import os
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Literal, TypeVar, Union

import httpx

__version__ = "0.2.0"

__all__ = [
    "Lingolix",
    "AsyncLingolix",
    "PronunciationResult",
    "Word",
    "Syllable",
    "LingolixError",
    "AuthenticationError",
    "SubscriptionError",
    "InvalidAudioError",
    "QuotaExceededError",
    "ServiceUnavailableError",
    "LANGUAGES",
    "Pitch",
    "MAX_UPLOAD_BYTES",
    "__version__",
]

DEFAULT_BASE_URL = "https://api.lingolix.com"
CHECK_PATH = "/api/pronunciation/v3/check"

#: Mirrors the server limit in the backend's pronunciation API.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

#: Languages accepted by the v3 endpoint.
LANGUAGES = (
    "bg", "cs", "de", "el", "en", "es", "fi", "fr",
    "hu", "it", "ja", "ko", "nl", "pl", "pt", "sv", "uk",
)

AudioInput = Union[str, "os.PathLike[str]", bytes, bytearray, BinaryIO]

#: Relative pitch of a syllable.
Pitch = Literal["high", "flat", "low", "unknown"]

T = TypeVar("T")


# --------------------------------------------------------------------------- errors


class LingolixError(Exception):
    """Base class for every error this client raises."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.detail = detail


class AuthenticationError(LingolixError):
    """The API key is missing, malformed or unknown (HTTP 401)."""


class SubscriptionError(LingolixError):
    """No active API subscription for this key (HTTP 403)."""


class InvalidAudioError(LingolixError):
    """The audio could not be decoded, or was too large (HTTP 400 / 413)."""


class QuotaExceededError(LingolixError):
    """The monthly quota is exhausted (HTTP 429)."""

    def __init__(self, message: str, *, status: int | None = None, detail: Any = None) -> None:
        super().__init__(message, status=status, detail=detail)
        d = detail if isinstance(detail, dict) else {}
        self.error: str | None = d.get("error")
        self.plan: str | None = d.get("plan")
        self.upgrade_url: str | None = d.get("upgrade_url")
        self.remaining_minutes: float | None = d.get("remaining_minutes")
        self.quota_percentage: float | None = d.get("quota_percentage")


class ServiceUnavailableError(LingolixError):
    """The scoring service is temporarily unreachable (HTTP 503)."""


_ERRORS: dict[int, type[LingolixError]] = {
    400: InvalidAudioError,
    401: AuthenticationError,
    403: SubscriptionError,
    413: InvalidAudioError,
    429: QuotaExceededError,
    503: ServiceUnavailableError,
}


# --------------------------------------------------------------------------- results


@dataclass(frozen=True)
class Syllable:
    """One syllable of a word, with expected vs. detected pronunciation."""

    text: str
    expected_ipa: str
    detected_ipa: str
    accuracy: float
    completeness: float
    pitch: Pitch
    duration_ms: float
    start_ms: float
    end_ms: float
    is_missing: bool
    is_extra: bool


@dataclass(frozen=True)
class Word:
    """One word, broken into syllables."""

    text: str
    syllables: list[Syllable]
    accuracy: float
    completeness: float
    start_ms: float
    end_ms: float
    char_start: int = -1
    char_end: int = -1
    #: Pause before or inside this word, in ms beyond the speaker's usual gap; None if none.
    hesitation_ms: float | None = None


@dataclass(frozen=True)
class PronunciationResult:
    """The scored utterance.

    ``text`` is the reference the audio was scored against: the ``sentence`` you
    passed, or the transcription when you passed none. ``overall`` is the score to
    show; ``accuracy`` (the sounds) and ``fluency`` (pace and pauses) explain it.
    ``fluency`` is None for utterances too short to time; ``overall`` then equals
    ``accuracy``.
    """

    text: str
    speaking_rate: float
    accuracy: float
    completeness: float
    overall: float
    words: list[Word] = field(default_factory=list)
    fluency: float | None = None
    target_speaking_rate: float | None = None


def _mk(cls: type[T], data: dict[str, Any]) -> T:
    # ponytail: drop unknown keys so a new backend field doesn't break installed clients
    names = {f.name for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
    return cls(**{k: v for k, v in data.items() if k in names})


def _to_result(data: dict[str, Any]) -> PronunciationResult:
    words = [
        _mk(Word, {**w, "syllables": [_mk(Syllable, s) for s in w.get("syllables", [])]})
        for w in data.get("words", [])
    ]
    # An API from before fluency scoring sends no overall: the sounds are all it judged.
    overall = data.get("overall", data.get("accuracy"))
    return _mk(PronunciationResult, {**data, "words": words, "overall": overall})


# --------------------------------------------------------------------------- clients


class _BaseClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float | httpx.Timeout | None = None,
    ) -> None:
        key = api_key or os.environ.get("LINGOLIX_API_KEY")
        if not key:
            raise LingolixError(
                "No API key. Pass Lingolix(api_key=...) or set the LINGOLIX_API_KEY "
                "environment variable. Create a key at https://lingolix.com/api-portal"
            )
        self.api_key = key
        self.base_url = (
            base_url or os.environ.get("LINGOLIX_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        # Scoring is slow; a short default timeout would just cause spurious failures.
        self.timeout = timeout if timeout is not None else httpx.Timeout(120.0, connect=10.0)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": f"lingolix-python/{__version__}",
        }

    @staticmethod
    def _multipart(
        audio: AudioInput, sentence: str | None, language: str
    ) -> tuple[dict[str, Any], dict[str, str]]:
        if isinstance(audio, (bytes, bytearray)):
            content: Any = bytes(audio)
            name, mime = "audio.wav", "application/octet-stream"
        elif isinstance(audio, (str, os.PathLike)):
            path = os.fspath(audio)
            with open(path, "rb") as fh:
                content = fh.read()
            name = os.path.basename(path) or "audio.wav"
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        else:  # file-like
            content = audio.read()
            name = os.path.basename(getattr(audio, "name", "") or "") or "audio.wav"
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"

        if len(content) > MAX_UPLOAD_BYTES:
            raise InvalidAudioError(
                f"Audio is {len(content) / 1048576:.1f} MiB, over the "
                f"{MAX_UPLOAD_BYTES // 1048576} MiB limit. Send a compressed format "
                "(MP3, Opus/WebM, AAC) instead of WAV — a single utterance is well "
                "under 1 MiB when encoded."
            )

        data = {"language_code": language}
        if sentence is not None:
            data["sentence"] = sentence
        return {"speechdata": (name, content, mime)}, data

    @staticmethod
    def _parse(response: httpx.Response) -> PronunciationResult:
        if response.status_code == 200:
            return _to_result(response.json())

        try:
            # FastAPI puts a string here normally, and a dict for the 429 quota payload.
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text or None

        if isinstance(detail, dict):
            message = detail.get("message") or detail.get("error") or str(detail)
        else:
            message = detail or f"HTTP {response.status_code}"

        cls = _ERRORS.get(response.status_code, LingolixError)
        raise cls(str(message), status=response.status_code, detail=detail)


class Lingolix(_BaseClient):
    """Synchronous client. Usable as a context manager."""

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        self._client = httpx.Client(
            base_url=self.base_url, headers=self._headers, timeout=self.timeout
        )

    def check(
        self,
        audio: AudioInput,
        *,
        sentence: str | None = None,
        language: str = "ja",
    ) -> PronunciationResult:
        """Score ``audio``.

        Pass ``sentence`` to score against known text; omit it to have the audio
        transcribed first and scored against its own transcription.
        """
        files, data = self._multipart(audio, sentence, language)
        return self._parse(self._client.post(CHECK_PATH, files=files, data=data))

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Lingolix:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class AsyncLingolix(_BaseClient):
    """Asynchronous client. Usable as an async context manager."""

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        self._client = httpx.AsyncClient(
            base_url=self.base_url, headers=self._headers, timeout=self.timeout
        )

    async def check(
        self,
        audio: AudioInput,
        *,
        sentence: str | None = None,
        language: str = "ja",
    ) -> PronunciationResult:
        """Score ``audio``. See :meth:`Lingolix.check`."""
        files, data = self._multipart(audio, sentence, language)
        return self._parse(await self._client.post(CHECK_PATH, files=files, data=data))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncLingolix:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()
