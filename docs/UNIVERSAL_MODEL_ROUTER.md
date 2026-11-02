# Universal Text Model Router

## Scope

This release adds a provider-neutral routing boundary for text generation. It
supports an ordered primary provider and one explicitly configured fallback
using OpenAI-compatible chat-completions endpoints. This is a routing foundation,
not a claim that native Anthropic, Gemini, or other provider adapters are already
implemented.

## Configuration

The primary route uses:

- TEXT_GENERATION_BASE_URL
- TEXT_GENERATION_API_KEY
- TEXT_GENERATION_MODEL
- TEXT_GENERATION_MODEL_ID and TEXT_GENERATION_MODEL_REVISION in production

The optional fallback uses:

- TEXT_GENERATION_FALLBACK_BASE_URL
- TEXT_GENERATION_FALLBACK_API_KEY
- TEXT_GENERATION_FALLBACK_MODEL
- TEXT_GENERATION_FALLBACK_MODEL_ID and TEXT_GENERATION_FALLBACK_MODEL_REVISION in production

Both fallback URL and model must be configured together. Remote endpoints must
use HTTPS; plain HTTP is allowed only for localhost. Secrets belong in the
runtime secret manager or deployment environment, never in source control.

## Retry and fallback policy

The router retries only failures classified as transient (timeouts, connection
failures, HTTP 408/409/425/429 and selected 5xx responses). It honors a bounded
Retry-After value and applies capped exponential backoff. It does not retry
invalid credentials, malformed requests, or model/endpoint not-found errors.
After a route is exhausted, the router may try the explicitly configured
fallback. It never silently invents a model ID or chooses an unconfigured model.

Production model-registry enforcement is applied to every configured route.
Each configured route must have its own immutable model ID and revision approved
before inference or streaming begins.

## Model discovery

GET /api/v1/ai/models checks the /models catalog on each configured route and
reports whether the configured model ID is listed. Catalog discovery is
provider-dependent: an unsupported catalog endpoint is reported as
discovery_unavailable and must not be interpreted as definitive proof that a
model cannot be used.

## Streaming

POST /api/v1/ai/complete/stream returns Server-Sent Events and supports
quality_mode=single. Events are:

- token: a JSON object containing a text content fragment
- done: the generation has ended
- error: a sanitized error code and message

Fallback is allowed only before the first token. Once output has been sent,
the router never joins a second provider's generation to the first provider's
partial answer. Clients should treat an error event as an incomplete response.

## Capability boundaries

The OpenAI-compatible adapter advertises streaming support only. It does not
advertise tool calling, structured outputs, vision, audio, or video. Provider
capabilities must be declared and tested per adapter; OpenAI compatibility
alone is not proof that every endpoint implements every optional feature.

## Observability

Each HTTP request receives a validated X-Request-ID (or a generated ID). The ID
is returned in the response and included in metadata-only JSON request logs. The
ASGI middleware retains the request context until streaming responses finish.
The formatter uses an allow-list and does not serialize arbitrary log extras,
request bodies, authorization headers, or API keys.

## Operational limits

The router currently supports ordered primary/fallback routing, not cost-optimal
multi-model selection, provider health scoring, dynamic model discovery, or
cross-model independent evaluation. Those remain separate implementation work.
