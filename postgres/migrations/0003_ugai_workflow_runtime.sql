-- UGAI workflow runtime schema migration.
-- Apply through the deployment's reviewed PostgreSQL migration process.
-- The runtime login must be a non-owner member of ugai_workflow_runtime and must not
-- own this schema, tables, or use a superuser/BYPASSRLS credential.

create schema if not exists ugai_workflow;

do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'ugai_workflow_runtime') then
        execute 'create role ugai_workflow_runtime nologin nobypassrls';
    end if;
end
$$;

revoke all on schema ugai_workflow from public;
grant usage on schema ugai_workflow to ugai_workflow_runtime;

create table if not exists ugai_workflow.tasks (
    task_id uuid primary key default gen_random_uuid(),
    tenant_id text not null,
    actor_id text not null,
    task_type text not null,
    state text not null default 'received'
        check (state = any (array[
            'received','observing','planning','executing','verifying',
            'awaiting_approval','awaiting_clarification','blocked',
            'blocked','outcome_unknown','failed','succeeded','cancelled'
        ])),
    version bigint not null default 0 check (version >= 0),
    retry_count integer not null default 0 check (retry_count between 0 and 2),
    max_retries integer not null default 2 check (max_retries between 0 and 2),
    retryable boolean not null default false,
    idempotency_key text not null,
    input_digest text not null check (input_digest ~ '^[0-9a-f]{64}$'),
    priority smallint not null default 0 check (priority between -100 and 100),
    available_at timestamptz not null default now(),
    lease_owner text,
    lease_token uuid,
    lease_expires_at timestamptz,
    approval_reference text,
    decision_digest text check (decision_digest is null or decision_digest ~ '^[0-9a-f]{64}$'),
    plan_digest text check (plan_digest is null or plan_digest ~ '^[0-9a-f]{64}$'),
    error_code text,
    metadata jsonb not null default '{}'::jsonb check (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint uq_ugai_workflow_task_idempotency unique (tenant_id, idempotency_key),
    constraint ck_ugai_workflow_lease_consistency check (
        (lease_owner is null and lease_token is null and lease_expires_at is null)
        or
        (lease_owner is not null and lease_token is not null and lease_expires_at is not null)
    ),
    constraint ck_ugai_workflow_retry_count check (retry_count <= max_retries)
);

create index if not exists ugai_workflow_claim_idx
    on ugai_workflow.tasks (priority desc, available_at, created_at)
    where state in ('received','observing','planning','executing','verifying');

create index if not exists ugai_workflow_lease_expiry_idx
    on ugai_workflow.tasks (lease_expires_at)
    where lease_token is not null;

create index if not exists ugai_workflow_tenant_created_idx
    on ugai_workflow.tasks (tenant_id, created_at desc);

create table if not exists ugai_workflow.events (
    event_id bigint generated always as identity primary key,
    event_uuid uuid not null default gen_random_uuid() unique,
    task_id uuid not null references ugai_workflow.tasks(task_id),
    task_version bigint not null check (task_version >= 0),
    actor_id text not null,
    worker_id text,
    event_type text not null,
    from_state text,
    to_state text not null,
    details jsonb not null default '{}'::jsonb check (jsonb_typeof(details) = 'object'),
    occurred_at timestamptz not null default now()
);

create index if not exists ugai_workflow_events_task_idx
    on ugai_workflow.events (task_id, event_id);

create table if not exists ugai_workflow.artifacts (
    artifact_id uuid primary key default gen_random_uuid(),
    task_id uuid not null references ugai_workflow.tasks(task_id),
    artifact_type text not null,
    artifact_uri text not null,
    sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
    media_type text,
    created_at timestamptz not null default now(),
    metadata jsonb not null default '{}'::jsonb check (jsonb_typeof(metadata) = 'object')
);

create index if not exists ugai_workflow_artifacts_task_idx
    on ugai_workflow.artifacts (task_id, created_at);

alter table ugai_workflow.tasks enable row level security;
alter table ugai_workflow.events enable row level security;
alter table ugai_workflow.artifacts enable row level security;
alter table ugai_workflow.tasks force row level security;
alter table ugai_workflow.events force row level security;
alter table ugai_workflow.artifacts force row level security;

drop policy if exists ugai_workflow_tasks_runtime on ugai_workflow.tasks;
create policy ugai_workflow_tasks_runtime on ugai_workflow.tasks
    for all to ugai_workflow_runtime
    using (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''))
    with check (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

drop policy if exists ugai_workflow_events_runtime on ugai_workflow.events;
create policy ugai_workflow_events_runtime on ugai_workflow.events
    for select to ugai_workflow_runtime
    using (exists (
        select 1 from ugai_workflow.tasks task
        where task.task_id = events.task_id
          and task.tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
    ));
create policy ugai_workflow_events_insert on ugai_workflow.events
    for insert to ugai_workflow_runtime
    with check (exists (
        select 1 from ugai_workflow.tasks task
        where task.task_id = events.task_id
          and task.tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
    ));

drop policy if exists ugai_workflow_artifacts_runtime on ugai_workflow.artifacts;
create policy ugai_workflow_artifacts_runtime on ugai_workflow.artifacts
    for select to ugai_workflow_runtime
    using (exists (
        select 1 from ugai_workflow.tasks task
        where task.task_id = artifacts.task_id
          and task.tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
    ));
create policy ugai_workflow_artifacts_insert on ugai_workflow.artifacts
    for insert to ugai_workflow_runtime
    with check (exists (
        select 1 from ugai_workflow.tasks task
        where task.task_id = artifacts.task_id
          and task.tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
    ));

revoke all on all tables in schema ugai_workflow from public;
grant select, insert on ugai_workflow.tasks to ugai_workflow_runtime;
grant update (
    state, version, retry_count, retryable, available_at,
    lease_owner, lease_token, lease_expires_at, approval_reference,
    decision_digest, plan_digest, error_code, updated_at
) on ugai_workflow.tasks to ugai_workflow_runtime;
grant select, insert on ugai_workflow.events to ugai_workflow_runtime;
grant select, insert on ugai_workflow.artifacts to ugai_workflow_runtime;
grant usage, select on all sequences in schema ugai_workflow to ugai_workflow_runtime;

create or replace function ugai_workflow.reject_event_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
    raise exception 'UGAI workflow events are append-only';
end;
$$;

revoke all on function ugai_workflow.reject_event_mutation() from public;
drop trigger if exists ugai_workflow_events_immutable on ugai_workflow.events;
create trigger ugai_workflow_events_immutable
    before update or delete on ugai_workflow.events
    for each row execute function ugai_workflow.reject_event_mutation();
drop trigger if exists ugai_workflow_events_no_truncate on ugai_workflow.events;
create trigger ugai_workflow_events_no_truncate
    before truncate on ugai_workflow.events
    for each statement execute function ugai_workflow.reject_event_mutation();

create or replace function ugai_workflow.reject_artifact_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
    raise exception 'UGAI workflow artifact registry is append-only';
end;
$$;

revoke all on function ugai_workflow.reject_artifact_mutation() from public;
drop trigger if exists ugai_workflow_artifacts_immutable on ugai_workflow.artifacts;
create trigger ugai_workflow_artifacts_immutable
    before update or delete on ugai_workflow.artifacts
    for each row execute function ugai_workflow.reject_artifact_mutation();
drop trigger if exists ugai_workflow_artifacts_no_truncate on ugai_workflow.artifacts;
create trigger ugai_workflow_artifacts_no_truncate
    before truncate on ugai_workflow.artifacts
    for each statement execute function ugai_workflow.reject_artifact_mutation();

comment on schema ugai_workflow is
    'Private durable UGAI workflow state, leases, audit events and artifact references; not a RAG corpus.';
comment on table ugai_workflow.tasks is
    'Durable task state. Application code validates transitions; version and lease token fence stale workers.';
comment on table ugai_workflow.events is
    'Append-only task lifecycle and lease event log; no raw prompts, secrets or hidden model reasoning.';
comment on table ugai_workflow.artifacts is
    'Append-only reference registry; artifact bytes remain in a separately permissioned object store.';
