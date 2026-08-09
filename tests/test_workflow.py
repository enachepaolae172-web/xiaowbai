import pytest

from src.models import ResearchReport, ResearchRequest, WorkflowStatus
from src.workflow import InvalidTransitionError, WorkflowController


PROGRESS_STATES = [
    WorkflowStatus.VALIDATING,
    WorkflowStatus.PLANNING,
    WorkflowStatus.SEARCHING,
    WorkflowStatus.BUILDING_EVIDENCE,
    WorkflowStatus.ANALYZING,
    WorkflowStatus.VERIFYING,
]


def test_workflow_advances_from_pending_to_completed(
    research_request: ResearchRequest,
    research_report: ResearchReport,
) -> None:
    controller = WorkflowController.create(research_request, run_id="test-run")

    for status in PROGRESS_STATES:
        controller.advance(status)
    completed = controller.complete(research_report)

    assert completed.status is WorkflowStatus.COMPLETED
    assert completed.result == research_report
    assert [event.status for event in completed.history] == [
        WorkflowStatus.PENDING,
        *PROGRESS_STATES,
        WorkflowStatus.COMPLETED,
    ]


def test_workflow_rejects_skipped_state(research_request: ResearchRequest) -> None:
    controller = WorkflowController.create(research_request)

    with pytest.raises(InvalidTransitionError, match="expected validating"):
        controller.advance(WorkflowStatus.SEARCHING)


def test_workflow_can_fail_from_non_terminal_state(
    research_request: ResearchRequest,
) -> None:
    controller = WorkflowController.create(research_request)
    controller.advance(WorkflowStatus.VALIDATING)
    failed = controller.fail("Input validation service unavailable")

    assert failed.status is WorkflowStatus.FAILED
    assert failed.error == "Input validation service unavailable"
    assert failed.result is None


def test_terminal_workflow_cannot_advance(
    research_request: ResearchRequest,
) -> None:
    controller = WorkflowController.create(research_request)
    controller.fail("Stopped")

    with pytest.raises(InvalidTransitionError, match="terminal"):
        controller.fail("Stopped again")


def test_workflow_snapshot_is_independent(research_request: ResearchRequest) -> None:
    controller = WorkflowController.create(research_request)
    snapshot = controller.snapshot()
    snapshot.history.clear()

    assert len(controller.run.history) == 1


def test_workflow_round_trip(research_request: ResearchRequest) -> None:
    controller = WorkflowController.create(research_request, run_id="round-trip")
    controller.advance(WorkflowStatus.VALIDATING, note="Validated")

    restored = controller.run.model_validate_json(controller.run.model_dump_json())

    assert restored == controller.run
