# External GPU Operations — Kaggle and Google Colab

## Execution model

Kaggle and Colab runtimes are ephemeral GPU workers. The notebook initiates outbound HTTPS polling. The API does not remotely start a notebook, extend its runtime, or guarantee GPU availability.

## API setup

1. Install the base application and optional PostgreSQL dependency:
   `pip install -e ".[postgres]"`
2. Set `DATABASE_URL` in the API host using a secret manager.
3. Apply every ordered SQL migration in `migrations/` to the target database before starting the API. Startup checks for the queue table and idempotency column.
4. Set `ENVIRONMENT=production`; startup then fails closed if `DATABASE_URL` is absent.
5. Set `WORKER_ADMIN_TOKEN` in the API environment. Use it only for trusted operator actions. `EXTERNAL_WORKER_TOKEN` is a development-only shared-token compatibility setting and must not be used in production.

The database migration is not applied automatically. Use a dedicated migration identity with least privilege. Restrict the application DB role to required table operations.

## Notebook setup

1. Open the corresponding template under `notebooks/` in Kaggle or Colab.
2. Have an operator provision the worker using `POST /api/v1/external-gpu/workers/provision` with `X-Worker-Admin-Token`. Store the returned one-time token as `EXTERNAL_WORKER_TOKEN`, then set `API_URL`, `WORKER_ID`, and `WORKER_SUPPORTED_TASKS` (comma-separated approved task names) in the notebook's secret/environment facility.
3. Install the optional client: `pip install requests` or `pip install -e ".[worker]"`.
4. Install only reviewed, version-pinned framework/model dependencies. The template discovers runtime/GPU details and registers them before it begins polling.
5. Implement a reviewed `handle_job(job)` function that checks task/model compatibility, fetches input only through a trusted signed URL, executes inference, uploads output to approved storage, and returns the immutable asset reference plus provenance metadata.
6. Call the template's `run_with_handler(handle_job)` function only after the handler and storage path have been tested.

The templates do not contain model inference code, storage credentials, model weights, or API secrets. They are deliberately not self-starting.

## Current worker protocol

- `POST /api/v1/external-gpu/jobs`: enqueue a platform-targeted job.
- `POST /api/v1/external-gpu/claim`: claim a job for the notebook worker.
- `POST /api/v1/external-gpu/jobs/{job_id}/heartbeat`: renew the current lease.
- `POST /api/v1/external-gpu/jobs/{job_id}/complete`: report output reference and metadata.
- `POST /api/v1/external-gpu/jobs/{job_id}/fail`: report an execution failure.
- `GET /api/v1/external-gpu/jobs/{job_id}`: inspect job state.

In production, the protocol authenticates workers with unique short-lived random tokens. The API stores token hashes, checks expiry/revocation, binds authenticated requests to the provisioned worker ID, and schedules tasks by the registered platform, supported task list, VRAM/RAM availability and capacity. Operators can re-provision a worker to rotate its token or revoke it explicitly. The legacy shared token is development-only. The lease still uses worker ID and an expiry timestamp; cryptographic per-lease tokens are not yet implemented.

## Lease and heartbeat caution

The configured lease duration is 15 minutes. `run_forever()` starts a dedicated heartbeat thread while a handler runs (default interval: 300 seconds) and stops it before reporting completion. Keep the interval below the lease duration. If the server rejects a heartbeat with an authorization or lease conflict response, the client treats the lease as lost and does not report success. Temporary network failures use bounded backoff; an extended outage can still outlast the lease.

## Failure handling

- Worker interruption: allow lease expiry and server retry; do not assume notebook process state survives.
- GPU out-of-memory: report a bounded error and retry with a compatible resource profile only when policy allows.
- Model download failure: stop the handler; verify revision/source/license before retry.
- Storage failure: do not report success; retry upload safely using an idempotent asset strategy.
- Invalid artifact: keep the job failed/quarantined; do not pass it downstream.
- Credential suspected compromised: disable worker access and rotate the shared prototype secret.

## Operational limitations

The PostgreSQL backend stores jobs and worker credential/capability records when configured and fully migrated; otherwise it runs in development-only memory mode. General `/api/v1/generate` jobs are not yet stored in the PostgreSQL external queue. Actual Kaggle/Colab inference, object storage upload, image-to-3D and GLB-to-MP4 execution remain **NOT RUN**.
