"""Restricted MCP tool-to-evidence adapter for the decision workflow.

Tool names and argument builders are operator-owned configuration. The model
never chooses an MCP tool or invents raw tool arguments in this adapter.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .models import EvidenceItem


class MCPToolProvider(Protocol):
    actor_id: str

    async def discover(self) -> list[dict[str, Any]]:
        """Return the provider's currently policy-approved tools."""

    async def execute(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Execute one already-approved tool."""


class EvidenceExtractionError(RuntimeError):
    """Raised when a connector response cannot be mapped to trusted evidence."""


@dataclass(frozen=True, slots=True)
class MCPToolQuery:
    """One operator-configured tool call.

    The argument builder is trusted application code. It may use the user
    question as a search term, but it must not choose a tool or change scope.
    """

    tool_name: str
    arguments_builder: Callable[[str], Mapping[str, Any]]

    def __post_init__(self) -> None:
        if not isinstance(self.tool_name, str) or not self.tool_name.strip():
            raise ValueError("tool_name must be a non-empty string")
        if not callable(self.arguments_builder):
            raise TypeError("arguments_builder must be callable")


EvidenceExtractor = Callable[[str, Mapping[str, Any]], Sequence[EvidenceItem]]


class MCPToolEvidenceSource:
    """Collect normalized evidence through a single authenticated MCP provider.

    Construct this source for one authenticated actor and keep the provider
    session open for the duration of DecisionWorkflow.run(). The provider's
    actor_id is checked against the trusted workflow actor. The extractor
    must resolve primary-source independence groups and attach stable locators.
    """

    def __init__(
        self,
        *,
        source_id: str,
        bound_actor_id: str,
        provider: MCPToolProvider,
        queries: Sequence[MCPToolQuery],
        extractor: EvidenceExtractor,
    ) -> None:
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("source_id must be a non-empty string")
        if not isinstance(bound_actor_id, str) or not bound_actor_id.strip():
            raise ValueError("bound_actor_id must be a non-empty trusted actor ID")
        if not queries:
            raise ValueError("at least one operator-configured MCP query is required")
        names = [query.tool_name for query in queries]
        if len(set(names)) != len(names):
            raise ValueError("MCP query tool names must be unique per source")
        if not callable(extractor):
            raise TypeError("extractor must be callable")
        provider_actor_id = getattr(provider, "actor_id", None)
        if provider_actor_id != bound_actor_id:
            raise PermissionError("MCP provider identity does not match the trusted actor")

        self.source_id = source_id
        self.bound_actor_id = bound_actor_id
        self._provider = provider
        self._queries = tuple(queries)
        self._extractor = extractor

    async def collect(self, question: str, actor_id: str) -> tuple[EvidenceItem, ...]:
        if actor_id != self.bound_actor_id:
            raise PermissionError("MCP provider actor does not match the trusted workflow actor")
        tools = await self._provider.discover()
        discovered_names = {
            item.get("name")
            for item in tools
            if isinstance(item, Mapping) and isinstance(item.get("name"), str)
        }
        missing = sorted({query.tool_name for query in self._queries} - discovered_names)
        if missing:
            raise EvidenceExtractionError(
                "Configured MCP tools are unavailable or not approved: " + ", ".join(missing)
            )

        records: list[EvidenceItem] = []
        seen_ids: set[str] = set()
        for query in self._queries:
            arguments = query.arguments_builder(question)
            if not isinstance(arguments, Mapping):
                raise EvidenceExtractionError("MCP argument builder must return a mapping")
            response = await self._provider.execute(query.tool_name, dict(arguments))
            if not isinstance(response, Mapping):
                raise EvidenceExtractionError("MCP provider returned a non-mapping result")
            extracted = self._extractor(query.tool_name, response)
            if not isinstance(extracted, Sequence) or isinstance(extracted, (str, bytes)):
                raise EvidenceExtractionError("Evidence extractor must return a sequence")
            for item in extracted:
                if not isinstance(item, EvidenceItem):
                    raise EvidenceExtractionError("Evidence extractor returned an invalid record")
                if item.source_id != self.source_id:
                    raise EvidenceExtractionError("Evidence source_id does not match its MCP source")
                if not item.provenance_uri or not item.provenance_uri.strip():
                    raise EvidenceExtractionError("Evidence must include a stable provenance locator")
                if item.evidence_id in seen_ids:
                    raise EvidenceExtractionError("Evidence IDs must be unique within an MCP source")
                seen_ids.add(item.evidence_id)
                records.append(item)
        return tuple(records)
