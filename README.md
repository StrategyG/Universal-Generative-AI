# Universal Generative AI

A modular platform for generative AI workflows, multimodal generation, and extensible model providers.

## Repository status

**Architecture and contracts are under design review. Runtime capabilities are not yet implemented or production-ready.** This branch establishes the system architecture, security boundaries, integration contracts, and validation rules. It does not claim a deployed application.

## Architecture documentation

- [Reference architecture](docs/REFERENCE_ARCHITECTURE.md)
- [Hybrid architecture overview](docs/ARCHITECTURE.md)
- [Institutional RAG integration contract](docs/INTEGRATION_CONTRACT.md)
- [Modular Agentic RAG execution specification](docs/AGENTIC_RAG_EXECUTION_SPEC.md)
- [Private notebook RAG and tenant isolation](docs/PRIVATE_NOTEBOOK_RAG_AND_TENANCY.md)
- [Secure ingestion and indexing](docs/INGESTION_AND_INDEXING_SPEC.md)
- [Vector store adapter decision](docs/VECTOR_STORE_ADAPTER_DECISION.md)
- [Retrieval and evidence governance](docs/RETRIEVAL_AND_EVIDENCE_GOVERNANCE.md)
- [Workflow and agent control](docs/WORKFLOW_AND_AGENT_CONTROL.md)
- [Application data model](docs/APPLICATION_DATA_MODEL.md)
- [Security threat model](docs/SECURITY_THREAT_MODEL.md)
- [Validation and release gates](docs/VALIDATION_AND_RELEASE_GATES.md)
- [Operations and SRE](docs/OPERATIONS_AND_SRE.md)
- [Institutional RAG backend mapping](docs/INSTITUTIONAL_RAG_BACKEND_MAPPING.md)
- [Service authentication and API security](docs/SERVICE_AUTH_AND_API_SECURITY.md)
- [Application data model](docs/APPLICATION_DATA_MODEL.md)
- [Political, business, holistic and strategic analysis](docs/DOMAIN_INTELLIGENCE_FRAMEWORKS.md)
- [Knowledge graph and multi-source synthesis](docs/KNOWLEDGE_GRAPH_AND_SYNTHESIS.md)
- [Phased implementation plan](docs/IMPLEMENTATION_PLAN.md)

## Machine-readable contracts

- OpenAPI: [contracts/openapi-v1.yaml](contracts/openapi-v1.yaml)
- Workflow plan schema: [contracts/plan-spec.schema.json](contracts/plan-spec.schema.json)
- Evidence record schema: [contracts/evidence-record.schema.json](contracts/evidence-record.schema.json)
- Retrieval plan schema: [contracts/retrieval-plan.schema.json](contracts/retrieval-plan.schema.json)
- Claim ledger schema: [contracts/claim-ledger.schema.json](contracts/claim-ledger.schema.json)
- Retrieval plan schema: [contracts/retrieval-plan.schema.json](contracts/retrieval-plan.schema.json)
- Claim ledger schema: [contracts/claim-ledger.schema.json](contracts/claim-ledger.schema.json)

## Vector database decision

Supabase PostgreSQL + pgvector is the primary active vector backend because it already hosts the project's Institutional RAG, evidence governance, and legacy RAG corpus. Astra DB is an optional future VectorStore adapter, not a configured dependency or a second source of truth.

## Supabase Institutional RAG status

The Supabase readiness view reported **NO_GO** on 2026-11-03. Private staging retrieval is not approved for user-facing citations. The runtime must preserve the distinction between retrieval relevance, source integrity, human review, publication state, and caller authorization.

## Engineering principles

- Explicit interfaces and versioned contracts.
- Environment-based secrets; never commit credentials.
- Least privilege and fail-closed authorization.
- Bounded agent plans, tool calls, time, tokens, and cost.
- Provenance-preserving retrieval and citation validation.
- Reproducible tests, CI, deployment, and rollback.
- Human approval for consequential or irreversible actions.

## Planned capability areas

- Provider-agnostic chat and model routing.
- Institutional RAG and evidence-grounded research.
- Agentic orchestration and controlled tool execution.
- Image, audio, video, and 3D generation pipelines.
- Durable jobs, artifact storage, and observability.

These are roadmap areas, not implemented capabilities.