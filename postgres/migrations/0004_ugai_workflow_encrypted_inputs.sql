-- Encrypted, actor-scoped input vault for durable UGAI tasks.
-- Apply after 0003_ugai_workflow_runtime.sql through the reviewed migration process.
-- AES-GCM encryption is performed by the service; plaintext is never stored in this table.

create table if not exists ugai_workflow.inputs (
    input_ref uuid primary key default gen_random_uuid(),
    tenant_id text not null,
    actor_id text not null,
    project_id text not null,
    workspace_id uuid not null,
    notebook_id uuid,
    key_id text not null check (key_id ~ '^[A-Za-z0-9._-]{1,64}$'),
    nonce bytea not null check (octet_length(nonce) = 12),
    ciphertext bytea not null check (octet_length(ciphertext) between 17 and 32784),
    payload_digest text not null check (payload_digest ~ '^[0-9a-f]{64}$'),
    idempotency_key text not null
        check (idempotency_key ~ '^[A-Za-z0-9._:-]{8,128}$'),
    created_at timestamptz not null default clock_timestamp(),
    expires_at timestamptz not null default (clock_timestamp() + interval '30 days'),
    constraint uq_ugai_workflow_input_idempotency
        unique (tenant_id, actor_id, idempotency_key),
    constraint ck_ugai_workflow_input_expiry
        check (expires_at > created_at)
);

create index if not exists ugai_workflow_inputs_expiry_idx
    on ugai_workflow.inputs (expires_at);

create index if not exists ugai_workflow_inputs_actor_idx
    on ugai_workflow.inputs (tenant_id, actor_id, project_id, created_at desc);

alter table ugai_workflow.inputs enable row level security;
alter table ugai_workflow.inputs force row level security;

drop policy if exists ugai_workflow_inputs_runtime on ugai_workflow.inputs;
create policy ugai_workflow_inputs_runtime on ugai_workflow.inputs
    for all to ugai_workflow_runtime
    using (
        tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
        and actor_id = nullif(current_setting('app.ugai_actor_id', true), '')
    )
    with check (
        tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
        and actor_id = nullif(current_setting('app.ugai_actor_id', true), '')
    );

revoke all on ugai_workflow.inputs from public;
grant select, insert on ugai_workflow.inputs to ugai_workflow_runtime;

comment on table ugai_workflow.inputs is
    'Tenant-, actor- and project-scoped task input vault. Payload is AES-256-GCM ciphertext only; key material remains in deployment secret manager.';
comment on column ugai_workflow.inputs.nonce is
    'Unique 96-bit AES-GCM nonce generated per encrypted input.';
comment on column ugai_workflow.inputs.key_id is
    'Opaque keyring version identifier; no encryption key material is stored in PostgreSQL.';
comment on column ugai_workflow.inputs.payload_digest is
    'SHA-256 of canonical plaintext payload, used for idempotency and post-decryption integrity verification.';
