import { check } from "k6";
import { Counter } from "k6/metrics";
import { submitTask } from "./common.js";

const unexpectedServerErrors = new Counter("unexpected_server_errors");

export const options = {
  scenarios: {
    controlled_overload: {
      executor: "ramping-arrival-rate",
      startRate: 25,
      timeUnit: "1s",
      preAllocatedVUs: 100,
      maxVUs: 400,
      stages: [
        { target: 25, duration: "2m" },
        { target: 50, duration: "2m" },
        { target: 100, duration: "2m" },
        { target: 150, duration: "2m" },
        { target: 150, duration: "2m" },
        { target: 0, duration: "1m" },
      ],
    },
  },
  thresholds: {
    checks: ["rate>0.98"],
    unexpected_server_errors: ["count==0"],
    http_req_duration: ["p(95)<5000"],
  },
};

export default function () {
  const response = submitTask();
  if (response.status >= 500 && response.status !== 503) {
    unexpectedServerErrors.add(1);
  }
  check(response, {
    "accepted or safely rejected under overload": (r) =>
      r.status === 202 || r.status === 429 || r.status === 503,
  });
}
