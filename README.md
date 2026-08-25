# Lingolix SDK

Official clients for the [Lingolix](https://lingolix.com) pronunciation scoring API. Send a
recording, get back per-syllable accuracy with expected vs. detected IPA, pitch and
timing — in 17 languages.

[![PyPI](https://img.shields.io/pypi/v/lingolix)](https://pypi.org/project/lingolix/)
[![npm](https://img.shields.io/npm/v/@lingolix/sdk)](https://www.npmjs.com/package/@lingolix/sdk)

| Client | Install | Docs |
| --- | --- | --- |
| Python (sync + async) | `pip install lingolix` | [python/README.md](python/README.md) |
| TypeScript / JavaScript | `npm install @lingolix/sdk` | [typescript/README.md](typescript/README.md) |

Get an API key at [lingolix.com/api-portal](https://lingolix.com/api-portal), then set
`LINGOLIX_API_KEY` in your environment. Keep it server-side — never ship it to a browser.

```python
from lingolix import Lingolix

with Lingolix() as client:
    r = client.check("audio.wav", sentence="Guten Morgen", language="de")
    print(r.accuracy, [s.text for w in r.words for s in w.syllables])
```

```ts
import { Lingolix } from "@lingolix/sdk";

const r = await new Lingolix().check({ audio, sentence: "Guten Morgen", language: "de" });
console.log(r.accuracy, r.words.flatMap((w) => w.syllables.map((s) => s.text)));
```

Both wrap a single endpoint — `POST /api/pronunciation/v3/check` — with typed results and
typed errors. That is deliberately the whole surface.

## Development

```bash
cd python     && uv sync && uv run pytest && uv run mypy src && uv run ruff check .
cd typescript && npm install && npm run typecheck && npm test
```

Tests mock the transport, so no API key or network is needed.

## Releasing

Tag `py-v0.1.0` to publish the Python package, `ts-v0.1.0` for the npm package. Both use
trusted publishing (OIDC) — no tokens in repository secrets. The two version independently.

## Links

- [API documentation](https://lingolix.com/api-portal/docs)
- [Pricing](https://lingolix.com/api-portal/pricing)
- [Issues](https://github.com/lingolix/lingolix-sdk/issues)

MIT licensed.
