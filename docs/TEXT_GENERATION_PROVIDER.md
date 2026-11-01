# OpenAI-Compatible Text Generation

## Supported inference path

The API exposes `POST /api/v1/ai/complete` for domain-specialist text generation in coding, film, and workflow domains. It uses an OpenAI-compatible `/chat/completions` endpoint, so it can connect to hosted services, vLLM, or a local Ollama endpoint.

The provider is disabled unless both `TEXT_GENERATION_BASE_URL` and `TEXT_GENERATION_MODEL` are configured. Remote endpoints must use HTTPS. Plain HTTP is accepted only for localhost. Redirects and environment-proxy inheritance are disabled, and provider response bodies are not returned in public error messages.

## Quality modes

- `single`: one generation call.
- `rigorous`: three sequential calls using the configured model: initial draft, domain-specific critique, and revision.

The rigorous pass asks the model to inspect omissions, contradictions, edge cases, risks, and untestable claims, then revise the draft. It is a same-model critique loop, not an independent reviewer and not proof of correctness. Responses explicitly set `verified=false`. Code must still be executed in a sandbox and tested; film assets must still be rendered and checked; workflow actions must still be independently reconciled.

## Configuration

Example local Ollama configuration:

```dotenv
TEXT_GENERATION_BASE_URL=http://localhost:11434/v1
TEXT_GENERATION_API_KEY=
TEXT_GENERATION_MODEL=qwen2.5:14b
TEXT_GENERATION_TIMEOUT_SECONDS=90
```

For hosted providers, use their HTTPS OpenAI-compatible base URL and store the API key only in the runtime secret manager. Never commit API keys.

## Production governance

When production mode or model-registry enforcement is active, the endpoint requires `TEXT_GENERATION_MODEL_ID` and `TEXT_GENERATION_MODEL_REVISION` and verifies that exact immutable revision against the model registry before inference. The registry approval record must contain the required license, validation, and evaluation evidence. The registry evidence is operator-supplied and is not independent certification.

## Limitations

- This adds inference integration, not foundation-model training or fine-tuning.
- It does not provide function/tool execution, repository write access, code execution, media rendering, or autonomous deployment.
- It does not persist prompts or completions as project artifacts.
- The same model critiques its own output in rigorous mode; self-review can repeat the same blind spots.
- External model quality, context window, structured-output support, rate limits, and data-retention behavior depend on the configured provider.
