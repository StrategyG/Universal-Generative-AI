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
    constraint decision_events_field_lengths check (
        length(event_id) <= 128
        and length(workflow_id) <= 128
        and length(decision_id) <= 128
        and length(actor_id) <= 255
        and length(stage) <= 100
        and length(outcome) <= 100
    ),
    constraint decision_events_details_object check (jsonb_typeof(details) = 'object')
);

create index if not exists decision_events_decision_id_idx
    on ugai_audit.decision_events (decision_id, occurred_at);
create index if not exists decision_events_workflow_id_idx
    on ugai_audit.decision_events (workflow_id, occurred_at);

alter table ugai_audit.decision_events enable row level security;

-- Supabase projects may grant broad default table privileges to service_role.
-- Revoke everything first, then grant only what the append RPC needs.
revoke all on table ugai_audit.decision_events from public, anon, authenticated, service_role;
grant insert on table ugai_audit.decision_events to service_role;

drop policy if exists decision_events_service_insert on ugai_audit.decision_events;
create policy decision_events_service_insert
    on ugai_audit.decision_events
    for insert
    to service_role
    with check (true);

-- The table schema stays out of the exposed Data API schemas. This narrow RPC
-- is the only Data API surface and is executable only by service_role.
create or replace function public.append_ugai_decision_event(
    p_event_id text,
    p_workflow_id text,
    p_decision_id text,
    p_actor_id text,
    p_stage text,
    p_outcome text,
    p_occurred_at timestamptz,
    p_details jsonb
)
returns void
language sql
security invoker
set search_path = pg_catalog
as $$
    insert into ugai_audit.decision_events (
        event_id, workflow_id, decision_id, actor_id,
        stage, outcome, occurred_at, details
    )
    values (
        p_event_id, p_workflow_id, p_decision_id, p_actor_id,
        p_stage, p_outcome, p_occurred_at, coalesce(p_details, '{}'::jsonb)
    );
$$;

revoke all on function public.append_ugai_decision_event(
    text, text, text, text, text, text, timestamptz, jsonb
) from public, anon, authenticated;
grant execute on function public.append_ugai_decision_event(
    text, text, text, text, text, text, timestamptz, jsonb
) to service_role;

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
comment on function public.append_ugai_decision_event(
    text, text, text, text, text, text, timestamptz, jsonb
) is
    'Narrow SECURITY INVOKER API to append one redacted UGAI decision audit event.';
