/**
 * Lingolix pronunciation API client.
 *
 * ```ts
 * import { Lingolix } from "@lingolix/sdk";
 *
 * const client = new Lingolix();            // key from $LINGOLIX_API_KEY
 * const r = await client.check({ audio, sentence: "Guten Morgen", language: "de" });
 * console.log(r.accuracy);
 * ```
 */

export const VERSION = "0.2.0";

const DEFAULT_BASE_URL = "https://api.lingolix.com";
const CHECK_PATH = "/api/pronunciation/v3/check";

/** Mirrors the server limit in the backend's pronunciation API. */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

/** Languages accepted by the v3 endpoint. */
export const LANGUAGES = [
  "bg", "cs", "de", "el", "en", "es", "fi", "fr",
  "hu", "it", "ja", "ko", "nl", "pl", "pt", "sv", "uk",
] as const;

export type Language = (typeof LANGUAGES)[number];
export type Pitch = "high" | "flat" | "low" | "unknown";

// --------------------------------------------------------------------------- results

/** One syllable of a word, with expected vs. detected pronunciation. */
export interface Syllable {
  text: string;
  expected_ipa: string;
  detected_ipa: string;
  accuracy: number;
  completeness: number;
  pitch: Pitch;
  duration_ms: number;
  start_ms: number;
  end_ms: number;
  is_missing: boolean;
  is_extra: boolean;
}

/** One word, broken into syllables. */
export interface Word {
  text: string;
  syllables: Syllable[];
  accuracy: number;
  completeness: number;
  start_ms: number;
  end_ms: number;
  char_start: number;
  char_end: number;
  /** Pause before or inside this word, in ms beyond the speaker's usual gap; null if none. */
  hesitation_ms?: number | null;
}

/**
 * The scored utterance. `text` is the reference the audio was scored against:
 * the `sentence` you passed, or the transcription when you passed none.
 * `overall` is the score to show; `accuracy` (the sounds) and `fluency` (pace
 * and pauses) explain it. `fluency` is null for utterances too short to time;
 * `overall` then equals `accuracy`.
 */
export interface PronunciationResult {
  text: string;
  /** The headline score, 0-1. */
  overall: number;
  /** How well the sounds were pronounced, 0-1. */
  accuracy: number;
  /** Pace and pauses, 0-1; null when the utterance is too short to time. */
  fluency?: number | null;
  completeness: number;
  /** Syllables (Japanese: morae) per second. */
  speaking_rate: number;
  /** Pace from which fluency gets full credit, in the same unit. */
  target_speaking_rate?: number | null;
  words: Word[];
}

// --------------------------------------------------------------------------- errors

/** Base class for every error this client throws. */
export class LingolixError extends Error {
  readonly status?: number;
  readonly detail?: unknown;

  constructor(message: string, status?: number, detail?: unknown) {
    super(message);
    this.name = new.target.name;
    this.status = status;
    this.detail = detail;
  }
}

/** The API key is missing, malformed or unknown (HTTP 401). */
export class AuthenticationError extends LingolixError {}

/** No active API subscription for this key (HTTP 403). */
export class SubscriptionError extends LingolixError {}

/** The audio could not be decoded, or was too large (HTTP 400 / 413). */
export class InvalidAudioError extends LingolixError {}

/** The scoring service is temporarily unreachable (HTTP 503). */
export class ServiceUnavailableError extends LingolixError {}

/** The monthly quota is exhausted (HTTP 429). */
export class QuotaExceededError extends LingolixError {
  readonly error?: string;
  readonly plan?: string;
  readonly upgradeUrl?: string;
  readonly remainingMinutes?: number;
  readonly quotaPercentage?: number;

  constructor(message: string, status?: number, detail?: unknown) {
    super(message, status, detail);
    const d = (detail ?? {}) as Record<string, unknown>;
    this.error = d.error as string | undefined;
    this.plan = d.plan as string | undefined;
    this.upgradeUrl = d.upgrade_url as string | undefined;
    this.remainingMinutes = d.remaining_minutes as number | undefined;
    this.quotaPercentage = d.quota_percentage as number | undefined;
  }
}

const ERRORS: Record<number, typeof LingolixError> = {
  400: InvalidAudioError,
  401: AuthenticationError,
  403: SubscriptionError,
  413: InvalidAudioError,
  429: QuotaExceededError,
  503: ServiceUnavailableError,
};

// --------------------------------------------------------------------------- client

export interface LingolixOptions {
  /** Defaults to `process.env.LINGOLIX_API_KEY`. */
  apiKey?: string;
  /** Defaults to `https://api.lingolix.com`. */
  baseUrl?: string;
  /** Request timeout. Scoring is slow, so this defaults to 120 000 ms. */
  timeoutMs?: number;
}

export interface CheckOptions {
  /** The recording to score. */
  audio: Blob | Uint8Array | ArrayBuffer;
  /** Score against this text. Omit to transcribe first, then score against that. */
  sentence?: string;
  /** Defaults to `"ja"`. */
  language?: Language | (string & {});
  /** Multipart filename. Cosmetic — the server sniffs the actual format. */
  filename?: string;
}

function env(name: string): string | undefined {
  // ponytail: works in Node/Bun/Deno, absent in browsers — hence the guard
  return typeof process !== "undefined" ? process.env?.[name] : undefined;
}

export class Lingolix {
  readonly apiKey: string;
  readonly baseUrl: string;
  readonly timeoutMs: number;

  constructor(options: LingolixOptions | string = {}) {
    const opts = typeof options === "string" ? { apiKey: options } : options;
    const key = opts.apiKey ?? env("LINGOLIX_API_KEY");
    if (!key) {
      throw new LingolixError(
        "No API key. Pass new Lingolix({ apiKey }) or set the LINGOLIX_API_KEY " +
          "environment variable. Create a key at https://lingolix.com/api-portal",
      );
    }
    this.apiKey = key;
    this.baseUrl = (opts.baseUrl ?? env("LINGOLIX_BASE_URL") ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.timeoutMs = opts.timeoutMs ?? 120_000;
  }

  /** Score a recording. */
  async check(options: CheckOptions): Promise<PronunciationResult> {
    const { audio, sentence, language = "ja", filename = "audio.wav" } = options;
    const blob = audio instanceof Blob ? audio : new Blob([audio as BlobPart]);

    if (blob.size > MAX_UPLOAD_BYTES) {
      throw new InvalidAudioError(
        `Audio is ${(blob.size / 1048576).toFixed(1)} MiB, over the ` +
          `${MAX_UPLOAD_BYTES / 1048576} MiB limit. Send a compressed format ` +
          "(MP3, Opus/WebM, AAC) instead of WAV — a single utterance is well " +
          "under 1 MiB when encoded.",
      );
    }

    const form = new FormData();
    form.append("speechdata", blob, filename);
    form.append("language_code", language);
    if (sentence !== undefined) form.append("sentence", sentence);

    const response = await fetch(this.baseUrl + CHECK_PATH, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        "User-Agent": `lingolix-js/${VERSION}`,
      },
      body: form,
      signal: AbortSignal.timeout(this.timeoutMs),
    });

    if (response.ok) {
      const r = await response.json();
      // An API from before fluency scoring sends no overall: the sounds are all it judged.
      return { ...r, overall: r.overall ?? r.accuracy } as PronunciationResult;
    }

    // FastAPI puts a string in `detail` normally, and an object for the 429 quota payload.
    let detail: unknown;
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail;
    } catch {
      detail = undefined;
    }

    const message =
      detail && typeof detail === "object"
        ? ((detail as Record<string, string>).message ??
          (detail as Record<string, string>).error ??
          JSON.stringify(detail))
        : ((detail as string | undefined) ?? `HTTP ${response.status}`);

    const ErrorClass = ERRORS[response.status] ?? LingolixError;
    throw new ErrorClass(message, response.status, detail);
  }
}

export default Lingolix;
