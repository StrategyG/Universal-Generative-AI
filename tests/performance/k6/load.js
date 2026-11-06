import { check } from "k6";
import { submitTask } from "./common.js";

const rate = Number(__ENV.RPS || 50);
const duration = __ENV.DURATION || "10m";
const preAllocatedVUs = Number(__ENV.PREALLOCATED_VUS || 100);
const maxVUs = Number(__ENV.MAX_VUS || 200);

export const options = {
  scenarios: {
    baseline_task_submission: {
      executor: "constant-arrival-rate",
      rate,
      timeUnit: "1s",
      duration,
      preAllocatedVUs,
      maxVUs,
    },
  },
  thresholds: {
    checks: ["rate>0.99"],
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<2000", "p(99)<5000"],
    dropped_iterations: ["count==0"],
  },
};

export default function () {
  const response = submitTask();
  check(response, {
    "task accepted with HTTP 202": (r) => r.status === 202,
  });
}
