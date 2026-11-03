from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, model_validator


Corpus = Literal[
    "institutional_approved", "legacy_rag", "private_notebook", "private_research"
]
EvidenceTier = Literal["approved", "legacy", "private_notebook", "private_staging"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceLocator(StrictModel):
    locator_type: Literal["pdf_page", "section", "web_anchor", "timestamp", "record"]
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    section: str | None = Field(default=None, max_length=1000)
    anchor: str | None = Field(default=None, max_length=2048)
    timestamp_start_ms: int | None = Field(default=None, ge=0)
    timestamp_end_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_locator(self) -> "EvidenceLocator":
        if self.locator_type == "pdf_page":
            if self.page_start is None or self.page_end != self.page_start:
                raise ValueError("Institutional PDF citations require one exact page")
        if self.page_start is not None and self.page_end is not None:
            if self.page_end < self.page_start:
                raise ValueError("page_end cannot precede page_start")
        if self.locator_type == "section" and not self.section:
            raise ValueError("Section locator requires section")
        if self.locator_type == "web_anchor" and not self.anchor:
            raise ValueError("Web anchor locator requires anchor")
        if self.locator_type == "timestamp":
            if self.timestamp_start_ms is None:
                raise ValueError("Timestamp locator requires timestamp_start_ms")
        return self


class EmbeddingProfile(StrictModel):
    model_id: str = Field(min_length=1, max_length=256)
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dimension: int = Field(ge=1)
    verified: bool


class EvidenceRecord(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=256)
    corpus_id: Corpus
    source_id: str = Field(min_length=1, max_length=256)
    chunk_id: str | None = Field(default=None, max_length=256)
    source_title: str = Field(min_length=1, max_length=1000)
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_url: AnyUrl | None = None
    locator: EvidenceLocator
    excerpt: str = Field(min_length=1, max_length=12000)
    retrieval_method: Literal["keyword", "semantic", "hybrid_rrf", "reranked"]
    relevance_score: float = Field(allow_inf_nan=False)
    rank: int = Field(ge=1)
    evidence_tier: EvidenceTier
    review_status: Literal["approved", "pending", "rejected", "unknown"]
    publication_state: Literal["published", "unpublished", "revoked", "unknown"]
    trusted: bool
    user_citation_eligible: bool
    retrieved_at: datetime
    embedding_profile: EmbeddingProfile | None = None
    warnings: tuple[Annotated[str, Field(max_length=500)], ...] = Field(
        default_factory=tuple, max_length=20
    )

    @model_validator(mode="after")
    def enforce_trust_boundaries(self) -> "EvidenceRecord":
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        if self.evidence_tier == "approved":
            if not (
                self.corpus_id == "institutional_approved"
                and self.review_status == "approved"
                and self.publication_state == "published"
                and self.trusted is True
                and self.user_citation_eligible is True
            ):
                raise ValueError("Approved evidence must be server-governed and published")
        if self.evidence_tier == "private_notebook":
            if self.trusted or self.publication_state != "unpublished":
                raise ValueError("Private notebook evidence is not institutionally trusted")
        if self.evidence_tier == "private_staging":
            if self.trusted or self.user_citation_eligible:
                raise ValueError("Private staging can never be user-citation eligible")
            if self.publication_state != "unpublished":
                raise ValueError("Private staging must remain unpublished")
        if self.corpus_id == "private_research" and self.user_citation_eligible:
            raise ValueError("Private research cannot enter the ordinary citation path")
        return self


class RetrievalMetadata(StrictModel):
    strategy: Literal["approved_keyword"]
    corpora: tuple[Literal["institutional_approved"], ...] = Field(
        min_length=1, max_length=1
    )
    candidate_count: int = Field(ge=0)


class RetrievalResult(StrictModel):
    request_id: str = Field(
        min_length=36,
        max_length=36,
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$",
    )
    status: Literal["evidence_found", "no_evidence"]
    retrieval: RetrievalMetadata
    evidence: tuple[EvidenceRecord, ...]
    warnings: tuple[Annotated[str, Field(max_length=500)], ...] = Field(
        default_factory=tuple, max_length=20
    )

    @model_validator(mode="after")
    def validate_result_consistency(self) -> "RetrievalResult":
        if self.status == "evidence_found" and not self.evidence:
            raise ValueError("evidence_found requires at least one evidence record")
        if self.status == "no_evidence" and self.evidence:
            raise ValueError("no_evidence cannot contain evidence records")
        if self.retrieval.candidate_count != len(self.evidence):
            raise ValueError("candidate_count must equal returned evidence count")
        if any(item.corpus_id != "institutional_approved" for item in self.evidence):
            raise ValueError("This adapter accepts only Institutional Approved evidence")
        return self
