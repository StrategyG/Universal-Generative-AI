import postgres from "npm:postgres@3.4.7";
import {
  buildApprovedEvidence,
  isProductionReleaseGateOpen,
  validateRetrievalRows,
  type ReleaseGate,
} from "./logic.ts";

const MAX_BODY_BYTES = 12_000;
const encoder = new TextEncoder();
let database: ReturnType<typeof postgres> | null = null;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function constantTimeEqual(a: string, b: string): boolean {
  if (!a || !b || a.length !== b.length) return false;
  let mismatch = 0;
  for (let i = 0; i < a.length; i++) mismatch |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return mismatch === 0;
}

function authenticate(req: Request): boolean {
  const expected = Deno.env.get("UGAI_INSTITUTIONAL_SERVICE_KEY") ?? "";
  const supplied = req.headers.get("x-ugai-service-key") ?? "";
  return constantTimeEqual(supplied, expected);
}

function sqlClient() {
  if (!database) {
    const connectionString = Deno.env.get("UGAI_RAG_GATE_DATABASE_URL") ?? "";
    if (!connectionString) throw new Error("Database connection is not configured");
    database = postgres(connectionString, {
      max: 1,
      idle_timeout: 20,
      connect_timeout: 8,
      max_lifetime: 900,
      prepare: false,
      ssl: "require",
    });
  }
  return database;
}

async function readReleaseGate(): Promise<ReleaseGate> {
  // Fixed read-only query against a narrowly granted, non-exposed gate function.
  const rows = await sqlClient().unsafe<ReleaseGate[]>(
    "select * from institutional_rag.ugai_read_production_release_gate_v1()"
  );
  const gate = rows[0];
  if (!gate) throw new Error("Release gate returned no row");
  return gate;
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") {
    return json({ error: { code: "METHOD_NOT_ALLOWED" } }, 405);
  }
  if (!authenticate(req)) {
    return json({ error: { code: "AUTH_REQUIRED" } }, 401);
  }
  if (!(req.headers.get("content-type") ?? "").toLowerCase().includes("application/json")) {
    return json({ error: { code: "INVALID_CONTENT_TYPE" } }, 415);
  }

  let input: Record<string, unknown>;
  try {
    const raw = await req.text();
    if (encoder.encode(raw).byteLength > MAX_BODY_BYTES) {
      return json({ error: { code: "PAYLOAD_TOO_LARGE" } }, 413);
    }
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return json({ error: { code: "INVALID_REQUEST" } }, 400);
    }
    input = parsed as Record<string, unknown>;
  } catch {
    return json({ error: { code: "INVALID_REQUEST" } }, 400);
  }

  const allowed = new Set(["request_id", "query", "limit", "scope"]);
  if (Object.keys(input).some((key) => !allowed.has(key))) {
    return json({ error: { code: "UNKNOWN_REQUEST_FIELD" } }, 400);
  }
  const requestId = typeof input.request_id === "string" ? input.request_id : "";
  const query = typeof input.query === "string" ? input.query.trim() : "";
  const limit = input.limit === undefined ? 5 : Number(input.limit);
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(requestId) ||
    !query || query.length > 2000 ||
    !Number.isInteger(limit) || limit < 1 || limit > 10
  ) {
    return json({ error: { code: "INVALID_REQUEST", request_id: requestId || null } }, 400);
  }

  const scope = input.scope;
  if (
    !scope || typeof scope !== "object" || Array.isArray(scope) ||
    JSON.stringify(scope) !== JSON.stringify({ corpus: ["institutional_approved"] })
  ) {
    return json({ error: { code: "SCOPE_NOT_SUPPORTED", request_id: requestId } }, 400);
  }

  try {
    const gate = await readReleaseGate();
    const gateIsGo = isProductionReleaseGateOpen(gate);
    if (!gateIsGo) {
      return json({
        error: {
          code: "RELEASE_GATE_NO_GO",
          message: "Institutional retrieval is blocked until every release gate passes",
          request_id: requestId,
          technical_passed: gate.technical_passed,
          technical_total: gate.technical_total,
          operational_passed: gate.operational_passed,
          operational_total: gate.operational_total,
        },
      }, 503);
    }

    const supabaseUrl = (Deno.env.get("SUPABASE_URL") ?? "").replace(/\/$/, "");
    const legacyKey = Deno.env.get("RAG_CHATGPT_API_KEY") ?? "";
    if (!supabaseUrl || !legacyKey) throw new Error("Retrieval configuration is incomplete");

    const upstream = await fetch(
      supabaseUrl + "/functions/v1/institutional-rag-search",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-rag-api-key": legacyKey,
        },
        body: JSON.stringify({ query, limit }),
        signal: AbortSignal.timeout(15_000),
      },
    );
    if (!upstream.ok) throw new Error("Institutional retrieval upstream failed");
    const upstreamBody: unknown = await upstream.json();
    const upstreamRecord = upstreamBody && typeof upstreamBody === "object"
      ? upstreamBody as Record<string, unknown>
      : {};
    const rows = validateRetrievalRows(upstreamRecord.results);
    const evidence = buildApprovedEvidence(rows);

    return json({
      request_id: requestId,
      status: evidence.length ? "evidence_found" : "no_evidence",
      retrieval: {
        strategy: "approved_keyword",
        corpora: ["institutional_approved"],
        candidate_count: evidence.length,
      },
      evidence,
      warnings: [],
    });
  } catch {
    return json({
      error: {
        code: "RETRIEVAL_UNAVAILABLE",
        message: "Institutional retrieval is temporarily unavailable",
        request_id: requestId,
      },
    }, 503);
  }
});
