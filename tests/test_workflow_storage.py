import asyncio
import os
from pathlib import Path

import pytest

from app.services.postgres_gpu_queue import PostgresExternalGPUQueue
from app.workflows.planner import build_workflow_plan
from app.workflows.schemas import WorkflowPlanRequest


def test_workflow_plan_persists_across_queue_restart_and_enforces_tenant_scope():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL not configured; PostgreSQL integration test not run")

    async def scenario():
        import asyncpg

        migration_dir = Path(__file__).parents[1] / "migrations"
        connection = await asyncpg.connect(database_url)
        try:
            for migration_path in sorted(migration_dir.glob("*.sql")):
                await connection.execute(migration_path.read_text(encoding="utf-8"))
        finally:
            await connection.close()

        plan = build_workflow_plan(WorkflowPlanRequest(
            project_id="workflow-storage-project",
            domain="coding",
            title="Persistent workflow test",
            objective="Verify durable and tenant-scoped plan storage",
            steps=[
                {"step_id": "build", "title": "Build", "action": "build_project"},
                {"step_id": "release", "title": "Release", "action": "deploy", "depends_on": ["build"]},
            ],
        ))

        first = PostgresExternalGPUQueue(database_url)
        await first.open()
        try:
            await first.create_workflow_plan(
                plan,
                tenant_id="workflow-test-tenant",
                owner_subject="workflow-test-owner",
            )
        finally:
            await first.close()

        restarted = PostgresExternalGPUQueue(database_url)
        await restarted.open()
        try:
            recovered = await restarted.get_workflow_plan(
                plan.plan_id,
                tenant_id="workflow-test-tenant",
                owner_subject="workflow-test-owner",
                project_ids=[],
                tenant_admin=False,
            )
            assert recovered is not None
            assert recovered.plan_id == plan.plan_id
            assert recovered.approval_required_steps == ["release"]

            cross_tenant = await restarted.get_workflow_plan(
                plan.plan_id,
                tenant_id="another-tenant",
                owner_subject="workflow-test-owner",
                project_ids=["workflow-storage-project"],
                tenant_admin=True,
            )
            assert cross_tenant is None
        finally:
            await restarted.close()

    asyncio.run(scenario())
