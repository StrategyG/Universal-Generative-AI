import http from "k6/http";
import { Counter } from "k6/metrics";
function uuidv4() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (character) => {
    const random = Math.floor(Math.random() * 16);
    const value = character === "x" ? random : ((random & 0x3) | 0x8);
    return value.toString(16);
  });
}

const BASE_URL = (__ENV.BASE_URL || "").replace(/\/+$/, "");
const AUTH_TOKEN = __ENV.AUTH_TOKEN || "";
const PROJECT_ID = __ENV.PROJECT_ID || "";
const WORKSPACE_ID = __ENV.WORKSPACE_ID || uuidv4();

if (!BASE_URL || !AUTH_TOKEN || !PROJECT_ID) {
  throw new Error("BASE_URL, AUTH_TOKEN and PROJECT_ID are required");
}

// During stress testing, 429/503 are valid protective responses. The load
// profile still asserts 202 acceptance separately.
http.setResponseCallback(http.expectedStatuses(202, 429, 503));

export const controlledRejections = new Counter("controlled_rejections");

export function submitTask() {
  const requestId = uuidv4();
  const idempotencyKey = "load-" + requestId.replace(/-/g, "");
  const payload = {
    project_id: PROJECT_ID,
    workspace_id: WORKSPACE_ID,
    intent: "Performance validation: acknowledge this task without external side effects.",
    context: "Synthetic load-test request.",
    artifacts: [],
    requested_capabilities: ["reasoning:read"],
  };
  const response = http.post(
    BASE_URL + "/api/v1/tasks",
    JSON.stringify(payload),
    {
      headers: {
        Authorization: "Bearer " + AUTH_TOKEN,
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
        "X-Request-ID": requestId,
        "X-Correlation-ID": requestId,
      },
      tags: { endpoint: "durable-task-submit" },
      timeout: "15s",
    }
  );

  if (response.status === 429 || response.status === 503) {
    controlledRejections.add(1);
  }
  return response;
}
