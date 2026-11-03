-- UGAI decision audit storage. Keep this schema private and separate from RAG audit_events.
create schema if not exists ugai_audit;

revoke all on schema ugai_audit from public, anon, authenticated;
grant usage on schema ugai_audit to service_role;

create table if not exists ugai_audit.decision_events (
    event_id text primary key,
    workflow_id text not null,
    decision_id text not null,
    actor_id text not null,
    stage text not null,
    outcome text not null,
    occurred_at timestamptz not null,
    details jsonb not null default '{}'::jsonb,
    inserted_at timestamptz not null default now(),
    constraint decision_events_event_id_nonempty check (length(trim(event_id)) > 0),
    constraint decision_events_workflow_id_nonempty check (length(trim(workflow_id)) > 0),
    constraint decision_events_decision_id_nonempty check (length(trim(decision_id)) > 0),
    constraint decision_events_actor_id_nonempty check (length(trim(actor_id)) > 0),
    constraint decision_events_stage_nonempty check (length(trim(stage)) > 0),
    constraint decision_events_outcome_nonempty check (length(trim(outcome)) > 0),
    constraint decision_events_details_object check (jsonb_typeof(details) = 'object')
);

create index if not exists decision_events_decision_id_idx
    on ugai_audit.decision_events (decision_id, occurred_at);
create index if not exists decision_events_workflow_id_idx
    on ugai_audit.decision_events (workflow_id, occurred_at);

alter table ugai_audit.decision_events enable row level security;

revoke all on table ugai_audit.decision_events from public, anon, authenticated;
grant insert on table ugai_audit.decision_events to service_role;

drop policy if exists decision_events_service_insert on ugai_audit.decision_events;
create policy decision_events_service_insert
    on ugai_audit.decision_events
    for insert
    to service_role
    with check (true);

create or replace function ugai_audit.reject_decision_event_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
    raise exception 'UGAI decision audit events are append-only';
end;
$$;

revoke all on function ugai_audit.reject_decision_event_mutation() from public, anon, authenticated, service_role;

drop trigger if exists decision_events_no_update_delete on ugai_audit.decision_events;
create trigger decision_events_no_update_delete
    before update or delete on ugai_audit.decision_events
    for each row execute function ugai_audit.reject_decision_event_mutation();

drop trigger if exists decision_events_no_truncate on ugai_audit.decision_events;
create trigger decision_events_no_truncate
    before truncate on ugai_audit.decision_events
    for each statement execute function ugai_audit.reject_decision_event_mutation();

comment on schema ugai_audit is
    'Private UGAI decision-workflow audit storage; not part of the RAG corpus or public Data API.';
comment on table ugai_audit.decision_events is
    'Append-only, redacted decision workflow events. Database owners remain privileged and must be separately governed.';
