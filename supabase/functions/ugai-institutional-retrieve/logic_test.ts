import {
  buildApprovedEvidence,
  isProductionReleaseGateOpen,
  validateRetrievalRows,
} from "./logic.ts";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function assertThrows(fn: () => unknown, message: string): void {
  let thrown = false;
  try {
    fn();
  } catch {
    thrown = true;
  }
  assert(thrown, message);
}

function goodRow(overrides: Record<string, unknown> = {}) {
  return {
    chunk_id: "chunk-001",
    document_id: "document-001",
    title: "Institutional source",
    page: 7,
    excerpt: "A sufficiently long and page-scoped approved evidence excerpt.",
    relevance_score: 0.91,
    content_sha256: "a".repeat(64),
    ...overrides,
  };
}

Deno.test("release gate opens only at exact GO 9/9 plus 4/4", () => {
  const gate = {
    decision: "GO",
    technical_passed: 9,
    technical_total: 9,
    operational_passed: 4,
    operational_total: 4,
  };
  assert(isProductionReleaseGateOpen(gate), "exact GO gate should open");
  assert(!isProductionReleaseGateOpen({ ...gate, decision: "NO_GO" }), "NO_GO must block");
  assert(!isProductionReleaseGateOpen({ ...gate, technical_passed: 8 }), "8/9 must block");
  assert(!isProductionReleaseGateOpen({ ...gate, operational_passed: 3 }), "3/4 must block");
  assert(!isProductionReleaseGateOpen({ ...gate, technical_total: 10 }), "wrong total must block");
  assert(
    !isProductionReleaseGateOpen({ ...gate, technical_passed: "9" as unknown as number }),
    "string counts must block"
  );
});

Deno.test("evidence validation preserves document SHA and exact page locator", () => {
  const rows = validateRetrievalRows([goodRow()]);
  const [evidence] = buildApprovedEvidence(rows, "2026-11-03T00:00:00.000Z");
  assert(evidence.source_hash === "a".repeat(64), "document content hash must be preserved");
  assert(evidence.source_id === "document-001", "source id must be preserved");
  assert(evidence.chunk_id === "chunk-001", "chunk id must be preserved");
  assert(evidence.locator.page_start === 7 && evidence.locator.page_end === 7, "exact page locator required");
  assert(evidence.trusted && evidence.user_citation_eligible, "eligible evidence must be marked after gate");
  assert(evidence.review_status === "approved", "review state must be explicit");
  assert(evidence.publication_state === "published", "publication state must be explicit");
});

Deno.test("malformed hashes and page locations fail closed", () => {
  assertThrows(
    () => validateRetrievalRows([goodRow({ content_sha256: "not-a-hash" })]),
    "malformed hash should be rejected"
  );
  assertThrows(
    () => validateRetrievalRows([goodRow({ page: 0 })]),
    "invalid page should be rejected"
  );
  assertThrows(
    () => validateRetrievalRows([goodRow({ excerpt: "too short" })]),
    "short excerpt should be rejected"
  );
});

Deno.test("duplicate evidence chunk identifiers are rejected", () => {
  assertThrows(
    () => validateRetrievalRows([goodRow(), goodRow()]),
    "duplicate chunks should be rejected"
  );
});

Deno.test("non-array upstream payload is rejected", () => {
  assertThrows(
    () => validateRetrievalRows({ results: [] }),
    "unexpected upstream shape should be rejected"
  );
});
