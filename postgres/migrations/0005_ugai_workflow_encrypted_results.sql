-- Encrypted, tenant/actor-scoped Notebook task results.
-- Apply after 0004_ugai_workflow_encrypted_inputs.sql.
-- Result bytes are AES-256-GCM ciphertext only; keys remain in the deployment secret manager.

create table if not exists ugai_workflow.results (
    tenant_id text not null,
    task_id uuid not null,
    actor_id text not null,
    project_id text not null,
    key_id text not null check (key_id ~ '^[A-Za-z0-9._-]{1,64}$'),
    nonce bytea not null check (octet_length(nonce) = 12),
    ciphertext bytea not null check (octet_length(ciphertext) between 17 and 262160),
    result_digest text not null check (result_digest ~ '^[0-9a-f]{64}$'),
    created_at timestamptz not null default clock_timestamp(),
    constraint pk_ugai_workflow_results primary key (tenant_id, task_id),
    constraint fk_ugai_workflow_results_task
        foreign key (tenant_id, task_id)
        references ugai_workflow.tasks (tenant_id, task_id)
        on delete restrict
);

create index if not exists ugai_workflow_results_actor_idx
    on ugai_workflow.results (tenant_id, actor_id, project_id, created_at desc);

alter table ugai_workflow.results enable row level security;
alter table ugai_workflow.results force row level security;

drop policy if exists ugai_workflow_results_runtime on ugai_workflow.results;
create policy ugai_workflow_results_runtime on ugai_workflow.results
    for all to ugai_workflow_runtime
    using (
        tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
        and actor_id = nullif(current_setting('app.ugai_actor_id', true), '')
    )
    with check (
        tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
        and actor_id = nullif(current_setting('app.ugai_actor_id', true), '')
    );

revoke all on ugai_workflow.results from public;
grant select, insert on ugai_workflow.results to ugai_workflow_runtime;

comment on table ugai_workflow.results is
    'Immutable AES-256-GCM Notebook task results, bound to tenant, actor, project and task; only ciphertext is stored.';
comment on column ugai_workflow.results.result_digest is
    'SHA-256 of canonical plaintext result, checked after authenticated decryption.';
