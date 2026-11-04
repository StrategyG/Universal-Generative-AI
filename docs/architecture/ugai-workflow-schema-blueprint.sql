-- DESIGN BLUEPRINT ONLY — NOT A SUPABASE MIGRATION.
-- Generate a real migration with:
--   supabase migration new create_ugai_workflow_runtime
-- Copy this reviewed blueprint into that generated migration.
-- Apply first to an isolated Supabase development branch.

create schema if not exists ugai_workflow;

do $role$
begin
    if not exists (select 1 from pg_roles where rolname = 'ugai_workflow_runtime') then
        execute 'create role ugai_workflow_runtime nologin nobypassrls';
    end if;
end
$role$;

revoke all on schema ugai_workflow from public, anon, authenticated, service_role;
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
            'failed','succeeded','cancelled'
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
    constraint uq_ugai_workflow_task_tenant_id unique (tenant_id, task_id),
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

-- User intent is encrypted before it reaches this table. Ciphertext is bound
-- to tenant_id + task_id + key_version using AES-256-GCM associated data.
do $task_tenant_key$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'uq_ugai_workflow_task_tenant_id'
          and conrelid = 'ugai_workflow.tasks'::regclass
    ) then
        alter table ugai_workflow.tasks
            add constraint uq_ugai_workflow_task_tenant_id unique (tenant_id, task_id);
    end if;
end
$task_tenant_key$;

create table if not exists ugai_workflow.task_payloads (
    task_id uuid primary key,
    tenant_id text not null,
    ciphertext bytea not null check (octet_length(ciphertext) between 16 and 65552),
    nonce bytea not null check (octet_length(nonce) = 12),
    key_version text not null check (
        length(key_version) between 1 and 32
        and key_version ~ '^[A-Za-z0-9._-]+$'
    ),
    created_at timestamptz not null default now(),
    constraint fk_ugai_workflow_task_payloads_tenant_task
        foreign key (tenant_id, task_id)
        references ugai_workflow.tasks(tenant_id, task_id) on delete restrict
);

create index if not exists ugai_workflow_task_payloads_tenant_idx
    on ugai_workflow.task_payloads (tenant_id, created_at desc);

-- Results are separately encrypted and immutable; only opaque references
-- and digests may appear in the task row or event log.
create table if not exists ugai_workflow.task_results (
    task_id uuid primary key,
    tenant_id text not null,
    actor_id text not null,
    result_digest text not null check (result_digest ~ '^[0-9a-f]{64}create table if not exists ugai_workflow.events (
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
alter table ugai_workflow.task_payloads enable row level security;
alter table ugai_workflow.task_results enable row level security;
alter table ugai_workflow.events enable row level security;
alter table ugai_workflow.artifacts enable row level security;
alter table ugai_workflow.tasks force row level security;
alter table ugai_workflow.task_payloads force row level security;
alter table ugai_workflow.task_results force row level security;
alter table ugai_workflow.events force row level security;
alter table ugai_workflow.artifacts force row level security;

drop policy if exists ugai_workflow_tasks_runtime on ugai_workflow.tasks;
create policy ugai_workflow_tasks_runtime on ugai_workflow.tasks
    for all to ugai_workflow_runtime
    using (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''))
    with check (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

drop policy if exists ugai_workflow_task_payloads_select on ugai_workflow.task_payloads;
create policy ugai_workflow_task_payloads_select on ugai_workflow.task_payloads
    for select to ugai_workflow_runtime
    using (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

drop policy if exists ugai_workflow_task_payloads_insert on ugai_workflow.task_payloads;
create policy ugai_workflow_task_payloads_insert on ugai_workflow.task_payloads
    for insert to ugai_workflow_runtime
    with check (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

drop policy if exists ugai_workflow_task_results_select on ugai_workflow.task_results;
create policy ugai_workflow_task_results_select on ugai_workflow.task_results
    for select to ugai_workflow_runtime
    using (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

drop policy if exists ugai_workflow_task_results_insert on ugai_workflow.task_results;
create policy ugai_workflow_task_results_insert on ugai_workflow.task_results
    for insert to ugai_workflow_runtime
    with check (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

drop policy if exists ugai_workflow_events_runtime on ugai_workflow.events;
create policy ugai_workflow_events_runtime on ugai_workflow.events
    for select to ugai_workflow_runtime
    using (exists (
        select 1 from ugai_workflow.tasks task
        where task.task_id = events.task_id
          and task.tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
    ));
drop policy if exists ugai_workflow_events_insert on ugai_workflow.events;
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
drop policy if exists ugai_workflow_artifacts_insert on ugai_workflow.artifacts;
create policy ugai_workflow_artifacts_insert on ugai_workflow.artifacts
    for insert to ugai_workflow_runtime
    with check (exists (
        select 1 from ugai_workflow.tasks task
        where task.task_id = artifacts.task_id
          and task.tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
    ));

revoke all on all tables in schema ugai_workflow from public, anon, authenticated, service_role;
grant select, insert on ugai_workflow.tasks to ugai_workflow_runtime;
grant update (
    state, version, retry_count, retryable, available_at,
    lease_owner, lease_token, lease_expires_at, approval_reference,
    decision_digest, plan_digest, error_code, updated_at
) on ugai_workflow.tasks to ugai_workflow_runtime;
grant select, insert on ugai_workflow.task_payloads to ugai_workflow_runtime;
grant select, insert on ugai_workflow.task_results to ugai_workflow_runtime;
grant select, insert on ugai_workflow.events to ugai_workflow_runtime;
grant select, insert on ugai_workflow.artifacts to ugai_workflow_runtime;
grant usage, select on all sequences in schema ugai_workflow to ugai_workflow_runtime;

create or replace function ugai_workflow.reject_task_payload_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $payload$
begin
    raise exception 'UGAI workflow task payloads are append-only';
end;
$payload$;

revoke all on function ugai_workflow.reject_task_payload_mutation()
    from public, anon, authenticated, service_role;
drop trigger if exists ugai_workflow_task_payloads_immutable on ugai_workflow.task_payloads;
create trigger ugai_workflow_task_payloads_immutable
    before update or delete on ugai_workflow.task_payloads
    for each row execute function ugai_workflow.reject_task_payload_mutation();
drop trigger if exists ugai_workflow_task_payloads_no_truncate on ugai_workflow.task_payloads;
create trigger ugai_workflow_task_payloads_no_truncate
    before truncate on ugai_workflow.task_payloads
    for each statement execute function ugai_workflow.reject_task_payload_mutation();

create or replace function ugai_workflow.reject_task_result_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $result$
begin
    raise exception 'UGAI workflow task results are append-only';
end;
$result$;

revoke all on function ugai_workflow.reject_task_result_mutation()
    from public, anon, authenticated, service_role;
drop trigger if exists ugai_workflow_task_results_immutable on ugai_workflow.task_results;
create trigger ugai_workflow_task_results_immutable
    before update or delete on ugai_workflow.task_results
    for each row execute function ugai_workflow.reject_task_result_mutation();
drop trigger if exists ugai_workflow_task_results_no_truncate on ugai_workflow.task_results;
create trigger ugai_workflow_task_results_no_truncate
    before truncate on ugai_workflow.task_results
    for each statement execute function ugai_workflow.reject_task_result_mutation();

create or replace function ugai_workflow.reject_event_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $event$
begin
    raise exception 'UGAI workflow events are append-only';
end;
$event$;

revoke all on function ugai_workflow.reject_event_mutation()
    from public, anon, authenticated, service_role;
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
as $artifact$
begin
    raise exception 'UGAI workflow artifact registry is append-only';
end;
$artifact$;

revoke all on function ugai_workflow.reject_artifact_mutation()
    from public, anon, authenticated, service_role;
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
comment on table ugai_workflow.task_payloads is
    'Append-only encrypted task input envelopes. Plaintext is never stored in workflow metadata or event rows.';
comment on table ugai_workflow.task_results is
    'Append-only encrypted task results. Result bytes are never stored in the task row or event details.';
comment on table ugai_workflow.events is
    'Append-only task lifecycle and lease event log; no raw prompts, secrets or hidden model reasoning.';
comment on table ugai_workflow.artifacts is
    'Append-only reference registry; artifact bytes remain in a separately permissioned object store.';
),
    ciphertext bytea not null check (octet_length(ciphertext) between 16 and 65552),
    nonce bytea not null check (octet_length(nonce) = 12),
    key_version text not null check (
        length(key_version) between 1 and 32
        and key_version ~ '^[A-Za-z0-9._-]+create table if not exists ugai_workflow.events (
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
alter table ugai_workflow.task_payloads enable row level security;
alter table ugai_workflow.events enable row level security;
alter table ugai_workflow.artifacts enable row level security;
alter table ugai_workflow.tasks force row level security;
alter table ugai_workflow.task_payloads force row level security;
alter table ugai_workflow.events force row level security;
alter table ugai_workflow.artifacts force row level security;

drop policy if exists ugai_workflow_tasks_runtime on ugai_workflow.tasks;
create policy ugai_workflow_tasks_runtime on ugai_workflow.tasks
    for all to ugai_workflow_runtime
    using (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''))
    with check (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

drop policy if exists ugai_workflow_task_payloads_select on ugai_workflow.task_payloads;
create policy ugai_workflow_task_payloads_select on ugai_workflow.task_payloads
    for select to ugai_workflow_runtime
    using (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

drop policy if exists ugai_workflow_task_payloads_insert on ugai_workflow.task_payloads;
create policy ugai_workflow_task_payloads_insert on ugai_workflow.task_payloads
    for insert to ugai_workflow_runtime
    with check (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

drop policy if exists ugai_workflow_events_runtime on ugai_workflow.events;
create policy ugai_workflow_events_runtime on ugai_workflow.events
    for select to ugai_workflow_runtime
    using (exists (
        select 1 from ugai_workflow.tasks task
        where task.task_id = events.task_id
          and task.tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
    ));
drop policy if exists ugai_workflow_events_insert on ugai_workflow.events;
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
drop policy if exists ugai_workflow_artifacts_insert on ugai_workflow.artifacts;
create policy ugai_workflow_artifacts_insert on ugai_workflow.artifacts
    for insert to ugai_workflow_runtime
    with check (exists (
        select 1 from ugai_workflow.tasks task
        where task.task_id = artifacts.task_id
          and task.tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
    ));

revoke all on all tables in schema ugai_workflow from public, anon, authenticated, service_role;
grant select, insert on ugai_workflow.tasks to ugai_workflow_runtime;
grant update (
    state, version, retry_count, retryable, available_at,
    lease_owner, lease_token, lease_expires_at, approval_reference,
    decision_digest, plan_digest, error_code, updated_at
) on ugai_workflow.tasks to ugai_workflow_runtime;
grant select, insert on ugai_workflow.task_payloads to ugai_workflow_runtime;
grant select, insert on ugai_workflow.events to ugai_workflow_runtime;
grant select, insert on ugai_workflow.artifacts to ugai_workflow_runtime;
grant usage, select on all sequences in schema ugai_workflow to ugai_workflow_runtime;

create or replace function ugai_workflow.reject_task_payload_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $payload$
begin
    raise exception 'UGAI workflow task payloads are append-only';
end;
$payload$;

revoke all on function ugai_workflow.reject_task_payload_mutation()
    from public, anon, authenticated, service_role;
drop trigger if exists ugai_workflow_task_payloads_immutable on ugai_workflow.task_payloads;
create trigger ugai_workflow_task_payloads_immutable
    before update or delete on ugai_workflow.task_payloads
    for each row execute function ugai_workflow.reject_task_payload_mutation();
drop trigger if exists ugai_workflow_task_payloads_no_truncate on ugai_workflow.task_payloads;
create trigger ugai_workflow_task_payloads_no_truncate
    before truncate on ugai_workflow.task_payloads
    for each statement execute function ugai_workflow.reject_task_payload_mutation();

create or replace function ugai_workflow.reject_event_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $event$
begin
    raise exception 'UGAI workflow events are append-only';
end;
$event$;

revoke all on function ugai_workflow.reject_event_mutation()
    from public, anon, authenticated, service_role;
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
as $artifact$
begin
    raise exception 'UGAI workflow artifact registry is append-only';
end;
$artifact$;

revoke all on function ugai_workflow.reject_artifact_mutation()
    from public, anon, authenticated, service_role;
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
comment on table ugai_workflow.task_payloads is
    'Append-only encrypted task input envelopes. Plaintext is never stored in workflow metadata or event rows.';
comment on table ugai_workflow.events is
    'Append-only task lifecycle and lease event log; no raw prompts, secrets or hidden model reasoning.';
comment on table ugai_workflow.artifacts is
    'Append-only reference registry; artifact bytes remain in a separately permissioned object store.';

    ),
    created_at timestamptz not null default now(),
    constraint fk_ugai_workflow_task_results_tenant_task
        foreign key (tenant_id, task_id)
        references ugai_workflow.tasks(tenant_id, task_id) on delete restrict
);

create index if not exists ugai_workflow_task_results_tenant_idx
    on ugai_workflow.task_results (tenant_id, created_at desc);

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
alter table ugai_workflow.task_payloads enable row level security;
alter table ugai_workflow.events enable row level security;
alter table ugai_workflow.artifacts enable row level security;
alter table ugai_workflow.tasks force row level security;
alter table ugai_workflow.task_payloads force row level security;
alter table ugai_workflow.events force row level security;
alter table ugai_workflow.artifacts force row level security;

drop policy if exists ugai_workflow_tasks_runtime on ugai_workflow.tasks;
create policy ugai_workflow_tasks_runtime on ugai_workflow.tasks
    for all to ugai_workflow_runtime
    using (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''))
    with check (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

drop policy if exists ugai_workflow_task_payloads_select on ugai_workflow.task_payloads;
create policy ugai_workflow_task_payloads_select on ugai_workflow.task_payloads
    for select to ugai_workflow_runtime
    using (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

drop policy if exists ugai_workflow_task_payloads_insert on ugai_workflow.task_payloads;
create policy ugai_workflow_task_payloads_insert on ugai_workflow.task_payloads
    for insert to ugai_workflow_runtime
    with check (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

drop policy if exists ugai_workflow_events_runtime on ugai_workflow.events;
create policy ugai_workflow_events_runtime on ugai_workflow.events
    for select to ugai_workflow_runtime
    using (exists (
        select 1 from ugai_workflow.tasks task
        where task.task_id = events.task_id
          and task.tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
    ));
drop policy if exists ugai_workflow_events_insert on ugai_workflow.events;
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
drop policy if exists ugai_workflow_artifacts_insert on ugai_workflow.artifacts;
create policy ugai_workflow_artifacts_insert on ugai_workflow.artifacts
    for insert to ugai_workflow_runtime
    with check (exists (
        select 1 from ugai_workflow.tasks task
        where task.task_id = artifacts.task_id
          and task.tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
    ));

revoke all on all tables in schema ugai_workflow from public, anon, authenticated, service_role;
grant select, insert on ugai_workflow.tasks to ugai_workflow_runtime;
grant update (
    state, version, retry_count, retryable, available_at,
    lease_owner, lease_token, lease_expires_at, approval_reference,
    decision_digest, plan_digest, error_code, updated_at
) on ugai_workflow.tasks to ugai_workflow_runtime;
grant select, insert on ugai_workflow.task_payloads to ugai_workflow_runtime;
grant select, insert on ugai_workflow.events to ugai_workflow_runtime;
grant select, insert on ugai_workflow.artifacts to ugai_workflow_runtime;
grant usage, select on all sequences in schema ugai_workflow to ugai_workflow_runtime;

create or replace function ugai_workflow.reject_task_payload_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $payload$
begin
    raise exception 'UGAI workflow task payloads are append-only';
end;
$payload$;

revoke all on function ugai_workflow.reject_task_payload_mutation()
    from public, anon, authenticated, service_role;
drop trigger if exists ugai_workflow_task_payloads_immutable on ugai_workflow.task_payloads;
create trigger ugai_workflow_task_payloads_immutable
    before update or delete on ugai_workflow.task_payloads
    for each row execute function ugai_workflow.reject_task_payload_mutation();
drop trigger if exists ugai_workflow_task_payloads_no_truncate on ugai_workflow.task_payloads;
create trigger ugai_workflow_task_payloads_no_truncate
    before truncate on ugai_workflow.task_payloads
    for each statement execute function ugai_workflow.reject_task_payload_mutation();

create or replace function ugai_workflow.reject_event_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $event$
begin
    raise exception 'UGAI workflow events are append-only';
end;
$event$;

revoke all on function ugai_workflow.reject_event_mutation()
    from public, anon, authenticated, service_role;
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
as $artifact$
begin
    raise exception 'UGAI workflow artifact registry is append-only';
end;
$artifact$;

revoke all on function ugai_workflow.reject_artifact_mutation()
    from public, anon, authenticated, service_role;
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
comment on table ugai_workflow.task_payloads is
    'Append-only encrypted task input envelopes. Plaintext is never stored in workflow metadata or event rows.';
comment on table ugai_workflow.events is
    'Append-only task lifecycle and lease event log; no raw prompts, secrets or hidden model reasoning.';
comment on table ugai_workflow.artifacts is
    'Append-only reference registry; artifact bytes remain in a separately permissioned object store.';
