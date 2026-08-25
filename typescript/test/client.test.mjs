// Client tests against a stubbed global fetch — no network, no test framework.
import assert from "node:assert/strict";
import { after, test } from "node:test";

import {
  AuthenticationError,
  InvalidAudioError,
  Lingolix,
  QuotaExceededError,
  ServiceUnavailableError,
} from "../dist/index.js";

const KEY = "lx_test_key";

// A real-shaped v3 response, plus an unknown field the backend might add later.
const OK_BODY = {
  text: "Guten Morgen",
  speaking_rate: 3.5,
  accuracy: 0.87,
  completeness: 1.0,
  future_field: "ignored",
  words: [
    {
      text: "Guten",
      accuracy: 0.9,
      completeness: 1.0,
      start_ms: 0,
      end_ms: 400,
      char_start: 0,
      char_end: 5,
      syllables: [
        {
          text: "Gu",
          expected_ipa: "ɡuː",
          detected_ipa: "ɡu",
          accuracy: 0.92,
          completeness: 1.0,
          pitch: "high",
          duration_ms: 200,
          start_ms: 0,
          end_ms: 200,
          is_missing: false,
          is_extra: false,
        },
      ],
    },
  ],
};

const QUOTA_BODY = {
  detail: {
    error: "quota_exceeded",
    message: "Monthly quota exhausted.",
    quota_percentage: 100,
    remaining_minutes: 0,
    plan: "free",
    upgrade_url: "https://lingolix.com/api-portal/pricing",
  },
};

const realFetch = globalThis.fetch;
after(() => {
  globalThis.fetch = realFetch;
});

/** Stub fetch, recording the request; returns the captured calls. */
function stubFetch(status, body) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  };
  return calls;
}

const audio = new Blob([new Uint8Array([82, 73, 70, 70])]); // "RIFF"

test("sends the request the backend expects", async () => {
  const calls = stubFetch(200, OK_BODY);
  const client = new Lingolix(KEY);
  await client.check({ audio, sentence: "Guten Morgen", language: "de" });

  const { url, init } = calls[0];
  assert.equal(url, "https://api.lingolix.com/api/pronunciation/v3/check");
  assert.equal(init.method, "POST");
  assert.equal(init.headers.Authorization, `Bearer ${KEY}`);
  assert.equal(init.body.get("sentence"), "Guten Morgen");
  assert.equal(init.body.get("language_code"), "de");
  assert.ok(init.body.get("speechdata") instanceof Blob);
});

test("omits sentence when not given", async () => {
  const calls = stubFetch(200, OK_BODY);
  await new Lingolix(KEY).check({ audio });
  assert.equal(calls[0].init.body.get("sentence"), null);
  assert.equal(calls[0].init.body.get("language_code"), "ja");
});

test("parses the nested result", async () => {
  stubFetch(200, OK_BODY);
  const r = await new Lingolix(KEY).check({ audio, sentence: "Guten Morgen", language: "de" });

  assert.equal(r.accuracy, 0.87);
  assert.equal(r.text, "Guten Morgen");
  assert.equal(r.words[0].text, "Guten");
  assert.equal(r.words[0].syllables[0].expected_ipa, "ɡuː");
  assert.equal(r.words[0].syllables[0].pitch, "high");
});

test("429 throws QuotaExceededError with the upgrade URL", async () => {
  stubFetch(429, QUOTA_BODY);
  await assert.rejects(
    () => new Lingolix(KEY).check({ audio }),
    (err) => {
      assert.ok(err instanceof QuotaExceededError);
      assert.equal(err.status, 429);
      assert.equal(err.plan, "free");
      assert.equal(err.upgradeUrl, "https://lingolix.com/api-portal/pricing");
      assert.match(err.message, /quota/i);
      return true;
    },
  );
});

for (const [status, ErrorClass] of [
  [401, AuthenticationError],
  [400, InvalidAudioError],
  [503, ServiceUnavailableError],
]) {
  test(`${status} throws ${ErrorClass.name}`, async () => {
    stubFetch(status, { detail: "nope" });
    await assert.rejects(
      () => new Lingolix(KEY).check({ audio }),
      (err) => err instanceof ErrorClass && err.message === "nope",
    );
  });
}

test("oversized audio is rejected before any request", async () => {
  globalThis.fetch = async () => assert.fail("request should not have been sent");
  const big = new Blob([new Uint8Array(10 * 1024 * 1024 + 1)]);
  await assert.rejects(
    () => new Lingolix(KEY).check({ audio: big }),
    (err) => err instanceof InvalidAudioError && /10 MiB limit/.test(err.message),
  );
});

test("missing API key fails loudly", () => {
  const saved = process.env.LINGOLIX_API_KEY;
  delete process.env.LINGOLIX_API_KEY;
  try {
    assert.throws(() => new Lingolix(), /LINGOLIX_API_KEY/);
  } finally {
    if (saved !== undefined) process.env.LINGOLIX_API_KEY = saved;
  }
});

test("accepts Uint8Array and ArrayBuffer audio", async () => {
  const calls = stubFetch(200, OK_BODY);
  const client = new Lingolix(KEY);
  await client.check({ audio: new Uint8Array([1, 2, 3]) });
  await client.check({ audio: new ArrayBuffer(8) });
  assert.equal(calls.length, 2);
  assert.ok(calls.every((c) => c.init.body.get("speechdata") instanceof Blob));
});
