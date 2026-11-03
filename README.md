# Universal Generative AI

A modular platform for generative AI workflows, designed to support multimodal generation pipelines and extensible model providers.

## Repository status

This repository is being initialized. No production capability is claimed until implementation, automated tests, security checks, and deployment validation are completed.

## Engineering principles

- Modular architecture with explicit interfaces for model providers.
- Configuration through environment variables; never commit secrets.
- Reproducible development and test workflows.
- Input validation, resource limits, and safe failure handling.
- Automated tests and CI before production release.

## Planned capability areas

- Image generation and image asset processing.
- 3D asset generation and conversion (for example, PNG to GLB) through validated model/tool integrations.
- 3D rendering and video generation (for example, GLB to video) through explicit rendering backends.
- Job orchestration, artifact storage, and observability.

These are roadmap areas, not implemented features yet.

## MCP integration status

The MCP server is maintained in [StrategyG/im19-universal-mcp](https://github.com/StrategyG/im19-universal-mcp). UGAI is intended to consume it as an authenticated remote MCP client over HTTPS Streamable HTTP. The integration contract is documented in [docs/IM19_MCP_INTEGRATION.md](docs/IM19_MCP_INTEGRATION.md); no client adapter or live connection is implemented yet.

## Status

**Initialization only — not production-ready.** The MCP integration is currently a documented contract, not a functioning integration.

Next steps: implement the provider-neutral MCP client, OAuth token provider, dynamic tool registry, deny-by-default policy layer, bounded execution and redacted audit interface; then add end-to-end staging tests.