# Universal Generative AI

A modular platform for generative AI workflows, designed to support multimodal generation pipelines and extensible model providers.

## Institutional Decision Intelligence

The feature branches add a deterministic AEPH and Hedge-Bet decision package at `src/ugai_decision/` and a framework-neutral multi-MCP orchestration runtime.

- Evidence provenance and primary-source independence groups prevent derivative sources from inflating corroboration.
- Conflicting claims are surfaced for review rather than resolved by majority vote.
- Alternatives are evaluated using expected value, strategic fit, cost, downside and reversibility.
- System dependencies, stakeholder impacts, assumptions and time horizons are explicitly surfaced.
- Hedge allocation, capped bet allocation, gross downside risk budget and reserve are calculated deterministically.
- The multi-source workflow collects evidence concurrently with timeouts and rejects partial results by default.
- An evidence manifest and digest accompany the decision snapshot to the human approval gateway.
- Execution is a separate step and requires a matching, unexpired, actor-scoped approval receipt tied to the exact execution-plan digest.
- No production audit, approval or execution service is configured. The engine is not yet wired to a deployed agent registry or live MCP services.

See [Institutional Decision Intelligence design](docs/INSTITUTIONAL_DECISION_INTELLIGENCE.md).

## IM19 remote MCP integration

The integration branch contains a reusable UGAI remote MCP adapter under `src/ugai_mcp/`.

- IM19 owns MCP transport, OAuth resource authentication, provider OAuth, encrypted provider credentials, provider-side quotas and audit.
- UGAI owns orchestration, tool discovery, workflow-specific allowlists and execution policy.
- Remote connection uses the deployed IM19 HTTPS Streamable HTTP resource ending in `/mcp`. A GitHub repository URL is not a runtime endpoint.
- The adapter requires an exact DNS hostname allowlist, a deployment-specific OAuth token provider requesting the exact IM19 resource audience and `im19:read` scope, a durable redacted audit sink, and trusted actor identity from UGAI authentication.
- Endpoint and OAuth resource hostnames must match. Wildcards, IP literals, non-default ports and URL credentials are rejected. Network egress controls are still required to block private/metadata destinations and DNS rebinding.
- Supabase may store non-secret integration metadata and redacted audit events; credentials, access tokens, refresh tokens, OAuth codes and encryption keys must remain outside RAG.

### Implemented

- HTTPS endpoint/resource validation and exact DNS host allowlist.
- OAuth token-provider interface requests the exact resource audience and `im19:read` scope; no static token is committed.
- Official MCP SDK session initialization and dynamic `tools/list`.
- Framework-neutral `IM19ToolProvider` facade exposing `discover()` and `execute()` for workflow-registry integration.
- Default-deny operator allowlist plus hard-deny rules for OAuth linking, Drive content/write/approval-status and raw Cloudbrowser task tools.
- Mandatory redacted audit before and after remote tool execution; fail closed if the audit sink is unavailable.
- Bounded calls and tests for configuration, policy and audit lifecycle.

### Not yet complete

This is a tested adapter and orchestration contract, not proof of a live connection. The concrete OAuth token provider, IM19 HTTPS deployment, issuer/client/resource registration, durable audit-sink implementation, deployed approval gateway and verifier, production execution adapter, workflow-registry wiring, network egress protections and end-to-end staging tests remain required.

See [IM19 integration design](docs/IM19_MCP_INTEGRATION.md), [decision intelligence design](docs/INSTITUTIONAL_DECISION_INTELLIGENCE.md), [validation gates](docs/IM19_MCP_VALIDATION.md), and the [IM19 server repository](https://github.com/StrategyG/im19-universal-mcp).

UGAI and this connector must not be described as production-ready until runtime, security, operational and live integration acceptance gates pass.
