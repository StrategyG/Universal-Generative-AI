-- Tenant-scoped worker heartbeats for task-acceptance gating.
-- A task is accepted only when a registered worker for its tenant advertises its task type.

create table if not exists ugai_workflow.workers (
    tenant_id text not null,
    worker_id text not null check (length(worker_id) between 1 and 128),
    task_types text[] not null check (cardinality(task_types) between 1 and 32),
    status text not null default 'active'
        check (status in ('active', 'draining', 'stopped')),
    heartbeat_at timestamptz not null default clock_timestamp(),
    created_at timestamptz not null default clock_timestamp(),
    updated_at timestamptz not null default clock_timestamp(),
    constraint pk_ugai_workflow_workers primary key (tenant_id, worker_id)
);

create index if not exists ugai_workflow_workers_active_idx
    on ugai_workflow.workers (tenant_id, heartbeat_at desc)
    where status = 'active';

alter table ugai_workflow.workers enable row level security;
alter table ugai_workflow.workers force row level security;

drop policy if exists ugai_workflow_workers_runtime on ugai_workflow.workers;
create policy ugai_workflow_workers_runtime on ugai_workflow.workers
    for all to ugai_workflow_runtime
    using (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''))
    with check (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

revoke all on ugai_workflow.workers from public;
grant select, insert, update on ugai_workflow.workers to ugai_workflow_runtime;

comment on table ugai_workflow.workers is
    'Tenant-scoped worker capability and heartbeat registry used to gate durable task acceptance.';
comment on column ugai_workflow.workers.task_types is
    'Explicit task type allowlist for this worker process; never derived from model output.';
