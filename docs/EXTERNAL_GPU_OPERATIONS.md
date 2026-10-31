# External GPU Operations — Kaggle and Google Colab

## Execution model

Kaggle and Colab runtimes are ephemeral GPU workers. The notebook initiates outbound HTTPS polling. The API does not remotely start a notebook, extend its runtime, or guarantee GPU availability.

## API setup

1. Install the base application and optional PostgreSQL dependency:
   `pip install -e ".[postgres]"`
2. Set `DATABASE_URL` in the API host using a secret manager.
3. Apply `migrations/0001_create_external_gpu_jobs.sql` to the target database before starting the API.
4. Set `ENVIRONMENT=production`; startup then fails closed if `DATABASE_URL` is absent.
5. Set the prototype `EXTERNAL_WORKER_TOKEN` in the API environment. Do not commit it.

The database migration is not applied automatically. Use a dedicated migration identity with least privilege. Restrict the application DB role to required table operations.

## Notebook setup

1. Open the corresponding template under `notebooks/` in Kaggle or Colab.
2. Configure `API_URL`, `EXTERNAL_WORKER_TOKEN`, and `WORKER_ID` in the notebook's secret/environment facility.
3. Install the optional client: `pip install requests` or `pip install -e ".[worker]"`.
4. Install only reviewed, version-pinned framework/model dependencies.
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

The current protocol authenticates with one shared prototype token and associates a lease with a worker ID. It does not yet issue per-worker scoped credentials or cryptographic lease tokens.

## Lease and heartbeat caution

The configured lease duration is 15 minutes. The current polling client exposes `heartbeat(job_id)`, but `run_forever()` does not run an independent heartbeat while a long inference handler is executing. Long-running jobs must therefore implement heartbeat calls during inference, or they may be reclaimed by the API after lease expiry. Do not assume an active notebook session means the job lease is valid.

## Failure handling

- Worker interruption: allow lease expiry and server retry; do not assume notebook process state survives.
- GPU out-of-memory: report a bounded error and retry with a compatible resource profile only when policy allows.
- Model download failure: stop the handler; verify revision/source/license before retry.
- Storage failure: do not report success; retry upload safely using an idempotent asset strategy.
- Invalid artifact: keep the job failed/quarantined; do not pass it downstream.
- Credential suspected compromised: disable worker access and rotate the shared prototype secret.

## Operational limitations

The queue can use PostgreSQL when configured and migrated; otherwise it runs in development-only memory mode. General `/api/v1/generate` jobs are not yet stored in the PostgreSQL external queue. Actual Kaggle/Colab inference, object storage upload, image-to-3D and GLB-to-MP4 execution remain **NOT RUN**.
