-- Forward-only expansion of the durable UGAI workflow state vocabulary.
-- Existing unknown remote outcomes must never be re-claimed as executable work.
DO $$
DECLARE constraint_row record;
BEGIN
    FOR constraint_row IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'ugai_workflow.tasks'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) ILIKE '%state = ANY%'
    LOOP
        EXECUTE format(
            'ALTER TABLE ugai_workflow.tasks DROP CONSTRAINT %I',
            constraint_row.conname
        );
    END LOOP;
END
$$;

ALTER TABLE ugai_workflow.tasks
    ADD CONSTRAINT ck_ugai_workflow_task_state
    CHECK (state IN (
        'received', 'observing', 'planning', 'executing', 'verifying',
        'awaiting_approval', 'awaiting_clarification', 'blocked',
        'outcome_unknown', 'failed', 'succeeded', 'cancelled'
    ));

COMMENT ON COLUMN ugai_workflow.tasks.state IS
    'Durable state machine. outcome_unknown is quarantined and cannot be claimed or retried without evidence-backed reconciliation.';
