from collections.abc import Mapping
from typing import Any

import pytest

from ugai_decision.models import EvidenceItem
from ugai_decision.mcp_source import (
    EvidenceExtractionError,
    MCPToolEvidenceSource,
    MCPToolQuery,
)


class FakeProvider:
    actor_id = "trusted-user"

    def __init__(self, response: Mapping[str, Any]):
        self.response = response
        self.executed = 0

    async def discover(self) -> list[dict[str, Any]]:
        return [{"name": "search_records"}]

    async def execute(
        self, tool_name: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        self.executed += 1
        return dict(self.response)


def evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="evidence-001",
        topic="market_demand",
        position="positive",
        source_id="mcp-search",
        independence_group="primary-source-1",
        source_reliability=0.7,
        evidence_quality=0.6,
        relevance=0.9,
        freshness=0.8,
        verified=False,
        provenance_uri="https://source.example/record-001",
    )


def source(provider: FakeProvider, extractor_called: list[bool]):
    def extractor(tool_name: str, response: Mapping[str, Any]):
        extractor_called.append(True)
        return (evidence(),)

    return MCPToolEvidenceSource(
        source_id="mcp-search",
        bound_actor_id="trusted-user",
        provider=provider,
        queries=(MCPToolQuery("search_records", lambda question: {"query": question}),),
        extractor=extractor,
    )


@pytest.mark.asyncio
async def test_unclassified_mcp_result_is_rejected_before_extraction():
    provider = FakeProvider({"items": [{"id": "untrusted"}]})
    extractor_called: list[bool] = []
    adapter = source(provider, extractor_called)

    with pytest.raises(EvidenceExtractionError, match="untrusted-data classification"):
        await adapter.collect("market outlook", "trusted-user")

    assert provider.executed == 1
    assert extractor_called == []


@pytest.mark.asyncio
async def test_explicitly_untrusted_mcp_result_can_be_extracted_as_data():
    provider = FakeProvider(
        {
            "trust_classification": "UNTRUSTED_EXTERNAL_DATA",
            "items": [{"id": "record-001"}],
        }
    )
    extractor_called: list[bool] = []
    adapter = source(provider, extractor_called)

    records = await adapter.collect("market outlook", "trusted-user")

    assert len(records) == 1
    assert records[0].verified is False
    assert extractor_called == [True]
