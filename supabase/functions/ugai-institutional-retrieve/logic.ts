export type ReleaseGate = {
  decision: string;
  technical_passed: number;
  technical_total: number;
  operational_passed: number;
  operational_total: number;
};

export type RetrievalRow = {
  chunk_id: string;
  document_id: string;
  title: string;
  page: number;
  excerpt: string;
  relevance_score: number;
  content_sha256: string;
};

export function isProductionReleaseGateOpen(gate: ReleaseGate): boolean {
  return gate.decision === "GO" &&
    Number.isInteger(gate.technical_passed) &&
    Number.isInteger(gate.technical_total) &&
    Number.isInteger(gate.operational_passed) &&
    Number.isInteger(gate.operational_total) &&
    gate.technical_passed === 9 &&
    gate.technical_total === 9 &&
    gate.operational_passed === 4 &&
    gate.operational_total === 4;
}

export function validateRetrievalRows(value: unknown): RetrievalRow[] {
  if (!Array.isArray(value)) throw new Error("Invalid retrieval result shape");
  const output: RetrievalRow[] = [];
  const seen = new Set<string>();

  for (const row of value) {
    if (!row || typeof row !== "object" || Array.isArray(row)) {
      throw new Error("Malformed approved evidence row");
    }
    const item = row as Record<string, unknown>;
    if (
      typeof item.chunk_id !== "string" || !item.chunk_id ||
      typeof item.document_id !== "string" || !item.document_id ||
      typeof item.title !== "string" || !item.title ||
      typeof item.page !== "number" || !Number.isInteger(item.page) || item.page < 1 ||
      typeof item.excerpt !== "string" || item.excerpt.trim().length < 20 ||
      typeof item.relevance_score !== "number" || !Number.isFinite(item.relevance_score) ||
      typeof item.content_sha256 !== "string" ||
      !/^[a-f0-9]{64}$/.test(item.content_sha256)
    ) {
      throw new Error("Malformed approved evidence row");
    }
    if (seen.has(item.chunk_id)) throw new Error("Duplicate approved evidence chunk");
    seen.add(item.chunk_id);

    output.push({
      chunk_id: item.chunk_id,
      document_id: item.document_id,
      title: item.title.slice(0, 1000),
      page: item.page,
      excerpt: item.excerpt.slice(0, 12_000),
      relevance_score: item.relevance_score,
      // The existing trusted RPC returns d.content_sha256 (document-level SHA-256).
      content_sha256: item.content_sha256,
    });
  }
  return output;
}

export function buildApprovedEvidence(
  rows: RetrievalRow[],
  retrievedAt = new Date().toISOString(),
) {
  return rows.map((item, index) => ({
    evidence_id: item.chunk_id,
    corpus_id: "institutional_approved" as const,
    source_id: item.document_id,
    chunk_id: item.chunk_id,
    source_title: item.title,
    source_hash: item.content_sha256,
    locator: {
      locator_type: "pdf_page" as const,
      page_start: item.page,
      page_end: item.page,
    },
    excerpt: item.excerpt,
    retrieval_method: "keyword" as const,
    relevance_score: item.relevance_score,
    rank: index + 1,
    evidence_tier: "approved" as const,
    review_status: "approved" as const,
    publication_state: "published" as const,
    trusted: true,
    user_citation_eligible: true,
    retrieved_at: retrievedAt,
    warnings: [],
  }));
}
