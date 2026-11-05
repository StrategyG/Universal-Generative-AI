from uuid import UUID

from ugai_workflow.input_vault import WorkflowInputVault
from ugai_workflow.result_vault import WorkflowResultVault


def test_input_vault_aad_has_unambiguous_scope_boundaries() -> None:
    common = {
        "workspace_id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        "input_ref": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        "key_id": "key-v1",
    }
    left = WorkflowInputVault._aad(
        tenant_id="tenant:one",
        actor_id="actor",
        project_id="project",
        **common,
    )
    right = WorkflowInputVault._aad(
        tenant_id="tenant",
        actor_id="one:actor",
        project_id="project",
        **common,
    )
    assert left != right


def test_result_vault_aad_has_unambiguous_scope_boundaries() -> None:
    task_id = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    left = WorkflowResultVault._aad(
        tenant_id="tenant:one",
        actor_id="actor",
        project_id="project",
        task_id=task_id,
        key_id="key-v1",
    )
    right = WorkflowResultVault._aad(
        tenant_id="tenant",
        actor_id="one:actor",
        project_id="project",
        task_id=task_id,
        key_id="key-v1",
    )
    assert left != right
