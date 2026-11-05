-- Canonical tenant/project/workspace binding registry for UGAI task intake.
-- Bindings are provisioned by an approved workspace integration; client-submitted UUIDs
-- are not accepted as proof of workspace ownership or project association.

create table if not exists ugai_workflow.workspace_bindings (
    tenant_id text not null,
    workspace_id uuid not null,
    project_id text not null,
    status text not null default 'active' check (status in ('active', 'revoked')),
    created_at timestamptz not null default clock_timestamp(),
    updated_at timestamptz not null default clock_timestamp(),
    constraint pk_ugai_workflow_workspace_bindings primary key (tenant_id, workspace_id)
);

create index if not exists ugai_workflow_workspace_project_idx
    on ugai_workflow.workspace_bindings (tenant_id, project_id, status);

alter table ugai_workflow.workspace_bindings enable row level security;
alter table ugai_workflow.workspace_bindings force row level security;

drop policy if exists ugai_workflow_workspace_bindings_runtime on ugai_workflow.workspace_bindings;
create policy ugai_workflow_workspace_bindings_runtime on ugai_workflow.workspace_bindings
    for select to ugai_workflow_runtime
    using (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

revoke all on ugai_workflow.workspace_bindings from public;
grant select on ugai_workflow.workspace_bindings to ugai_workflow_runtime;

comment on table ugai_workflow.workspace_bindings is
    'Read-only authoritative tenant/workspace/project binding used to validate client workspace references before task intake.';
