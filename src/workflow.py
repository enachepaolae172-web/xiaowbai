"""Deterministic workflow state controller with explicit transitions."""

from __future__ import annotations

from src.models import (
    ResearchReport,
    ResearchRequest,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStatus,
)


class InvalidTransitionError(ValueError):
    """Raised when workflow code attempts to skip or reverse a state."""


_NEXT_STATUS: dict[WorkflowStatus, WorkflowStatus] = {
    WorkflowStatus.PENDING: WorkflowStatus.VALIDATING,
    WorkflowStatus.VALIDATING: WorkflowStatus.PLANNING,
    WorkflowStatus.PLANNING: WorkflowStatus.SEARCHING,
    WorkflowStatus.SEARCHING: WorkflowStatus.BUILDING_EVIDENCE,
    WorkflowStatus.BUILDING_EVIDENCE: WorkflowStatus.ANALYZING,
    WorkflowStatus.ANALYZING: WorkflowStatus.VERIFYING,
    WorkflowStatus.VERIFYING: WorkflowStatus.COMPLETED,
}


class WorkflowController:
    """Own the state of one research run without invoking external services."""

    def __init__(self, run: WorkflowRun) -> None:
        self.run = run.model_copy(deep=True)
        if not self.run.history:
            self.run.history.append(WorkflowEvent(status=self.run.status))

    @classmethod
    def create(cls, request: ResearchRequest, *, run_id: str | None = None) -> WorkflowController:
        values: dict[str, object] = {"request": request}
        if run_id is not None:
            values["run_id"] = run_id
        return cls(WorkflowRun(**values))

    @property
    def expected_next_status(self) -> WorkflowStatus | None:
        return _NEXT_STATUS.get(self.run.status)

    def advance(self, status: WorkflowStatus, *, note: str | None = None) -> WorkflowRun:
        if status in {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED}:
            raise InvalidTransitionError("use complete() or fail() for terminal states")

        expected = self.expected_next_status
        if status is not expected:
            raise InvalidTransitionError(
                f"cannot transition from {self.run.status.value} to {status.value}; "
                f"expected {expected.value if expected else 'no next state'}"
            )
        self._record(status, note=note)
        return self.snapshot()

    def complete(self, report: ResearchReport, *, note: str | None = None) -> WorkflowRun:
        if self.run.status is not WorkflowStatus.VERIFYING:
            raise InvalidTransitionError("workflow can complete only after verification")
        if report.request != self.run.request:
            raise ValueError("report request does not match workflow request")

        self.run.result = report
        self.run.error = None
        self._record(WorkflowStatus.COMPLETED, note=note)
        return self.snapshot()

    def fail(self, error: str, *, note: str | None = None) -> WorkflowRun:
        if self.run.status in {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED}:
            raise InvalidTransitionError("terminal workflow cannot transition to failed")
        if not error.strip():
            raise ValueError("error must not be empty")

        self.run.error = error.strip()
        self.run.result = None
        self._record(WorkflowStatus.FAILED, note=note)
        return self.snapshot()

    def snapshot(self) -> WorkflowRun:
        return self.run.model_copy(deep=True)

    def _record(self, status: WorkflowStatus, *, note: str | None) -> None:
        self.run.status = status
        self.run.history.append(WorkflowEvent(status=status, note=note))
