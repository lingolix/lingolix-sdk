# lingolix

Python client for the [Lingolix](https://lingolix.com) pronunciation scoring API. Send a
recording, get back per-syllable accuracy with expected vs. detected IPA, pitch and
timing — in 17 languages.

Get an API key at [lingolix.com/api-portal](https://lingolix.com/api-portal), then set
`LINGOLIX_API_KEY` in your environment. Keep it server-side — never ship it to a browser.

## Install

```bash
pip install lingolix      # or: uv add lingolix
```

## Usage

```python
from lingolix import Lingolix

with Lingolix() as client:                       # key from $LINGOLIX_API_KEY
    r = client.check("audio.wav", sentence="Guten Morgen", language="de")

    print(r.accuracy, r.completeness, r.speaking_rate)
    for word in r.words:
        for s in word.syllables:
            print(s.text, s.expected_ipa, "→", s.detected_ipa, s.pitch, round(s.accuracy, 2))
```

Async is the same class with an `Async` prefix:

```python
from lingolix import AsyncLingolix

async with AsyncLingolix() as client:
    r = await client.check(audio_bytes, sentence="こんにちは", language="ja")
```

`check()` takes a path, `bytes`, or any file-like object. Drop `sentence` and the audio is
transcribed first, then scored against its own transcription — useful for free-form speech.

## Result shape

| Field | Meaning |
| --- | --- |
| `text` | What the audio was scored against — your `sentence`, or the transcription |
| `accuracy` | Overall pronunciation accuracy, 0–1 |
| `completeness` | How much of the expected utterance was actually said, 0–1 |
| `speaking_rate` | Syllables per second |
| `words[]` | `text`, `accuracy`, `completeness`, `start_ms`, `end_ms`, `char_start`, `char_end` |
| `words[].syllables[]` | `text`, `expected_ipa`, `detected_ipa`, `accuracy`, `completeness`, `pitch`, `duration_ms`, `start_ms`, `end_ms`, `is_missing`, `is_extra` |

`pitch` is one of `"high"`, `"flat"`, `"low"`, `"unknown"`.

## Errors

Every failure is a subclass of `LingolixError` carrying `.status` and `.detail`.

| Class | HTTP | Cause |
| --- | --- | --- |
| `InvalidAudioError` | 400, 413 | Undecodable audio, or over the 10 MiB limit |
| `AuthenticationError` | 401 | Missing, malformed or unknown API key |
| `SubscriptionError` | 403 | No active API subscription |
| `QuotaExceededError` | 429 | Monthly quota exhausted |
| `ServiceUnavailableError` | 503 | Scoring service temporarily down |

`QuotaExceededError` also carries `plan`, `remaining_minutes`, `quota_percentage` and
`upgrade_url`:

```python
from lingolix import Lingolix, QuotaExceededError

try:
    r = Lingolix().check("audio.wav", language="en")
except QuotaExceededError as e:
    print(f"{e.plan} plan is out of minutes — upgrade at {e.upgrade_url}")
```

## Languages

`bg cs de el en es fi fr hu it ja ko nl pl pt sv uk` — the default is `ja`.

## Audio

Anything ffmpeg can read: WAV, MP3, M4A, OGG/Opus, FLAC, WebM. Uploads are capped at
10 MiB, checked client-side before sending. Prefer a compressed format — a single utterance
is well under 1 MiB as MP3 or Opus.

## Links

- [TypeScript client](https://www.npmjs.com/package/@lingolix/sdk)
- [API documentation](https://lingolix.com/api-portal/docs)
- [Pricing](https://lingolix.com/api-portal/pricing)
- [Source and issues](https://github.com/lingolix/lingolix-sdk)

MIT licensed.
