# Knowledge Graph and Multi-Source Synthesis Specification

**Status:** target design based on existing Institutional RAG staging structures. No graph tables or publication actions are added here.

## 1. Existing foundation

The current Institutional RAG database includes:
- private knowledge candidate staging;
- knowledge relation staging;
- synthesis staging and synthesis-member provenance;
- source-backed web evidence staging;
- human review and publication gates.

The inspected relation staging model records relation key, source/target knowledge IDs, relation type, rationale, supporting knowledge IDs, review status, trusted, human_approved, publication_authorized, and synthesis method. Existing staged relations default to pending human review and are not trusted or published. Synthesis staging also requires review and publication authorization.

These existing structures should be reused through stable adapters. Do not create a second graph-of-record without a measured requirement.

## 2. Graph primitives

### Node types
- Person/Actor
- Organization/Institution
- Policy/Decision
- Product/Service
- Market/Industry
- Event
- Concept/Capability
- Document/Source
- Claim/KnowledgeUnit

### Edge types
Use current allowed relation types where semantically appropriate:
GUIDES, REQUIRES, DEPENDS_ON, IMPLEMENTS, CONTRASTS_WITH, TRADEOFF_FOR, VALIDATES, PART_OF_WORKFLOW, UPGRADE_PATH_TO, GOVERNED_BY, COMPLEMENTS, SEPARATES_RESPONSIBILITY_FROM, CAN_FEED.

Additional domain relations require a schema/version decision and migration, not free-form edge strings.

## 3. Node and edge provenance

Every candidate node/edge should include:
- stable identifier and entity type;
- canonical name and aliases;
- source evidence IDs;
- source hashes and locators;
- extraction method/model/version;
- observed time and validity interval;
- confidence rationale;
- review status;
- human reviewer identity and decision;
- publication authorization state.

An AI-generated relation is a hypothesis, not a fact. It must be traceable to at least two evidence units where the relation policy requires corroboration. An edge must not become trusted merely because a model assigned a high score.

## 4. Entity resolution

Resolution order:
1. Exact stable identifier from an authoritative source.
2. Exact normalized name plus jurisdiction/organization context.
3. Alias match with provenance.
4. Model-proposed candidate match followed by deterministic checks.
5. Human review for ambiguous high-impact merges.

Never merge people, organizations, policies, or events from name similarity alone. Preserve aliases and source-specific IDs. Entity merges must be reversible and auditable.

## 5. Temporal graph

Relationships need valid time and observation time:
- valid_from / valid_to: when the relationship is believed to apply in the world;
- observed_at: when the system observed it;
- source_published_at: when the source was published;
- captured_at: when the source was captured.

A changed relationship should create a new version or superseding event. Do not overwrite historical facts as though the earlier relationship never existed.

## 6. Multi-source synthesis pipeline

1. Select a narrowly defined capability/question.
2. Retrieve eligible evidence by domain and time window.
3. Normalize claims without removing qualifiers.
4. Deduplicate by source identity/hash, not by textual similarity alone.
5. Extract candidate entities, events, and relationships.
6. Link each candidate to exact evidence IDs and source locators.
7. Group supporting, conflicting, and context-only evidence separately.
8. Generate a synthesis draft with explicit claim/evidence mapping.
9. Run entailment/attribution review and source integrity checks.
10. Submit candidate to human review and quorum rules.
11. Publish only through existing approved promotion mechanisms.
12. Record synthesis version, membership list, and all source hashes.

## 7. Synthesis quality rules

- No source may be represented as supporting a claim it does not actually support.
- Contradictory evidence remains visible.
- Metadata-only retrieval is not direct claim evidence.
- Derived synthesis does not become independent corroboration of its own source documents.
- Repeated copies of one source are not independent sources.
- Time-sensitive claims require valid-time checks.
- If evidence is incomplete, synthesis must be marked incomplete or provisional.

## 8. Querying the graph

Use graph traversal only after authorization filtering. Bound:
- maximum hops;
- maximum nodes/edges;
- maximum path count;
- maximum execution time;
- tenant and evidence-tier scope.

Return an explanation path with each relationship and the evidence supporting it. Never return an edge without provenance to a user-facing answer.

## 9. Publication boundary

The application may:
- query approved/published graph knowledge;
- propose private candidate nodes and edges through a controlled workflow;
- generate a synthesis draft;
- request human review.

The application may not:
- set trusted=true on its own;
- create reviewer identities;
- record a human vote on behalf of a person;
- bypass quorum/veto checks;
- publish staged candidates directly;
- convert AI triage into human approval.

The existing database's promotion functions and readiness views remain authoritative. If the release gate says NO_GO, a model or application flag cannot override it.
