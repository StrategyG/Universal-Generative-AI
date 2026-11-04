# ADR-0003: Canonical Cataran platform contract home and change control

- **Status:** Accepted as the transitional canonical source
- **Decision date:** 2026-11-05
- **Decision owner:** Cataran Master Architect
- **Repository:** `StrategyG/Universal-Generative-AI`
- **Canonical path:** `contracts/v1/`

## Context

UGAI, IM19, Notebook Studio, Cloudbrowser, RAG_Cerdas and the Android Connector had overlapping task, event, identity, approval and provenance DTOs. Two competing UGAI proposals existed: a broad multi-schema contract package and a standalone event-envelope proposal. No verified need exists to add an eighth repository or another runtime service.

## Decision

1. Use `StrategyG/Universal-Generative-AI/contracts/v1/` as the single canonical, versioned contract source for the Cataran platform.
2. Keep this as a contract package only. It is not a runtime service, task orchestrator, policy engine, identity provider or MCP gateway.
3. UGAI owns task lifecycle and decision orchestration. IM19 is the sole MCP gateway. Notebook Studio is a client and projection. Cloudbrowser is a worker. RAG_Cerdas owns knowledge ingestion/retrieval and provenance. Android Connector is an adapter behind IM19.
4. Consolidate the common platform event envelope into the same package as task, identity, approval, tool-invocation, evidence, error and A2A schemas. No separate event schema repository or competing canonical directory is created.
5. Consumer repositories may keep generated types or pinned schema snapshots for build reproducibility, but must record the source contract version and immutable source revision and run compatibility checks against the canonical fixtures.
6. No consumer may modify the semantics locally. A contract change must be proposed in UGAI, reviewed by the Architecture Owner and affected consumer owners, and versioned before rollout.
7. No new repository is created by this decision.

## Version and release policy

- The current v1 candidate remains **under PR review**. This ADR does not publish a release tag and does not authorize production adoption by itself.
- A v1 release requires schema/fixture CI, owner review, a consumer compatibility matrix, pinned consumer evidence, migration/rollback instructions and a tagged immutable revision.
- Backward-compatible optional changes increment the minor version. Clarifications or corrections with no semantic effect increment patch. Breaking payload or lifecycle changes require a new major version.
- Every cross-service payload carries contract version, tenant and actor context where applicable, task/correlation/causation identifiers, timestamp and digest/provenance. No secrets or private model chain-of-thought may be included.
- Unknown fields are rejected where the specific schema sets `additionalProperties=false`. Security-sensitive consumers must still enforce authorization and tenant ownership at runtime; schema validation is not authorization.

## Consequences

- UGAI becomes the change-control location and canonical source for v1 schemas.
- Existing IM19/Notebook/Cloudbrowser/RAG/Android snapshots are provisional until compared against and pinned to a released canonical revision.
- The delivery tracker remains open until each active consumer passes compatibility CI and the release candidate completes staging end-to-end validation.
- No live database, identity provider, connector secret or production deployment is modified by this architecture decision.

## Acceptance evidence

- This file is version-controlled with the contract package.
- The consolidated package CI validates all positive and negative fixtures.
- Issue #32 tracks the remaining consumer adoption and release evidence.
