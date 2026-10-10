# @lingolix/sdk

TypeScript/JavaScript client for the [Lingolix](https://lingolix.com) pronunciation scoring
API. Send a recording, get back per-syllable accuracy with expected vs. detected IPA, pitch
and timing — in 17 languages.

Get an API key at [lingolix.com/api-portal](https://lingolix.com/api-portal), then set
`LINGOLIX_API_KEY` in your environment. Keep it server-side — never ship it to a browser.

## Install

```bash
npm install @lingolix/sdk      # pnpm add / yarn add / bun add
```

## Usage

```ts
import { readFile } from "node:fs/promises";
import { Lingolix } from "@lingolix/sdk";

const client = new Lingolix();                   // key from $LINGOLIX_API_KEY

const r = await client.check({
  audio: new Blob([await readFile("audio.wav")]),
  sentence: "Guten Morgen",
  language: "de",
});

console.log(r.overall, r.accuracy, r.fluency, r.speaking_rate);
for (const word of r.words) {
  for (const s of word.syllables) {
    console.log(s.text, s.expected_ipa, "→", s.detected_ipa, s.pitch, s.accuracy);
  }
}
```

Drop `sentence` and the audio is transcribed first, then scored against its own
transcription — useful for free-form speech.

Zero runtime dependencies — it uses the platform's `fetch`, `FormData` and `Blob`. Works on
Node 18+, Bun, Deno, Cloudflare Workers and in the browser (bring your own key handling).
`audio` accepts a `Blob`, `Uint8Array` or `ArrayBuffer`.

## Result shape

| Field | Meaning |
| --- | --- |
| `text` | What the audio was scored against — your `sentence`, or the transcription |
| `overall` | The score to show, 0–1: `accuracy` and `fluency` weighted as human raters weigh them |
| `accuracy` | How well the sounds were pronounced, 0–1 |
| `fluency` | Pace and pauses, 0–1; `None`/`null` when the utterance is too short to time (then `overall` = `accuracy`) |
| `completeness` | How much of the expected utterance was actually said, 0–1 |
| `speaking_rate` | Syllables (Japanese: morae) per second |
| `target_speaking_rate` | Pace from which `fluency` gets full credit (60% of a typical native pace) |
| `words[]` | `text`, `accuracy`, `completeness`, `start_ms`, `end_ms`, `char_start`, `char_end`, `hesitation_ms` (pause before or inside the word, else `None`/`null`) |
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

`QuotaExceededError` also carries `plan`, `remainingMinutes`, `quotaPercentage` and
`upgradeUrl`:

```ts
import { Lingolix, QuotaExceededError } from "@lingolix/sdk";

try {
  const r = await new Lingolix().check({ audio, language: "en" });
} catch (e) {
  if (e instanceof QuotaExceededError) {
    console.log(`${e.plan} plan is out of minutes — upgrade at ${e.upgradeUrl}`);
  }
}
```

## Languages

`bg cs de el en es fi fr hu it ja ko nl pl pt sv uk` — the default is `ja`.

## Audio

Anything ffmpeg can read: WAV, MP3, M4A, OGG/Opus, FLAC, WebM. Uploads are capped at
10 MiB, checked client-side before sending. Prefer a compressed format — a single utterance
is well under 1 MiB as MP3 or Opus.

## Links

- [Python client](https://pypi.org/project/lingolix/)
- [API documentation](https://lingolix.com/api-portal/docs)
- [Pricing](https://lingolix.com/api-portal/pricing)
- [Source and issues](https://github.com/lingolix/lingolix-sdk)

MIT licensed.
