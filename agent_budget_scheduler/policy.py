"""Synchronous admission/dispatch state: all mutations precede any await."""

from collections import deque
from dataclasses import dataclass
from typing import Callable

from .models import Admission, JobSpec, SchedulerConfig, State


@dataclass
class JobRecord:
    spec: JobSpec
    sequence: int
    submitted_at: float
    state: State = State.QUEUED
    started_at: float | None = None
    finished_at: float | None = None
    reason: str | None = None
    deadline_at: float | None = None
    stop_state: State | None = None
    stop_reason: str | None = None
    dispatched_priority: int | None = None

    @property
    def terminal(self) -> bool:
        return self.state not in (State.QUEUED, State.RUNNING, State.STOPPING)


class DispatchPolicy:
    def __init__(self, config: SchedulerConfig, clock: Callable[[], float]):
        self.config = config
        self.clock = clock
        self.records: dict[str, JobRecord] = {}
        self.rejections: list[Admission] = []
        self._seen: set[str] = set()
        self._ring: deque[str] = deque()
        self._queues: dict[str, list[JobRecord]] = {}
        self.pending = 0
        self.running = 0
        self.running_by_tenant: dict[str, int] = {}
        self.peak_running = 0
        self.peak_running_by_tenant: dict[str, int] = {}

    def submit(self, spec: JobSpec) -> Admission:
        if spec.job_id in self._seen:
            raise ValueError("duplicate job_id")
        self._seen.add(spec.job_id)
        if self.pending >= self.config.max_pending:
            receipt = Admission(spec.job_id, False, "overload")
            self.rejections.append(receipt)
            return receipt
        record = JobRecord(spec, len(self.records), self.clock())
        if spec.deadline_after_ms is not None:
            record.deadline_at = record.submitted_at + spec.deadline_after_ms / 1000
        self.records[spec.job_id] = record
        if spec.tenant not in self._queues:
            self._queues[spec.tenant] = []
            self._ring.append(spec.tenant)
        self._queues[spec.tenant].append(record)
        self.pending += 1
        return Admission(spec.job_id, True)

    def dispatch(self) -> JobRecord | None:
        if self.running >= self.config.max_running:
            return None
        now = self.clock()
        for index, tenant in enumerate(self._ring):
            queue = self._queues[tenant]
            count = self.running_by_tenant.get(tenant, 0)
            if not queue or count >= self.config.max_running_per_tenant:
                continue
            eligible = [item for item in queue if item.deadline_at is None or now < item.deadline_at]
            if not eligible:
                continue
            record = min(eligible, key=lambda item: (-self.effective_priority(item, now), item.sequence))
            record.dispatched_priority = self.effective_priority(record, now)
            queue.remove(record)
            self._ring.rotate(-(index + 1))
            self.pending -= 1
            self.running += 1
            self.running_by_tenant[tenant] = count + 1
            self.peak_running = max(self.peak_running, self.running)
            self.peak_running_by_tenant[tenant] = max(
                self.peak_running_by_tenant.get(tenant, 0), count + 1
            )
            record.state = State.RUNNING
            record.started_at = now
            return record
        return None

    def finish(self, record: JobRecord, state: State, reason: str | None) -> None:
        if record.state not in (State.RUNNING, State.STOPPING) or state in (State.RUNNING, State.QUEUED, State.STOPPING):
            raise RuntimeError("invalid terminal transition")
        record.state = record.stop_state or state
        record.reason = record.stop_reason if record.stop_state is not None else reason
        record.finished_at = self.clock()
        self.running -= 1
        self.running_by_tenant[record.spec.tenant] -= 1

    def effective_priority(self, record: JobRecord, now: float | None = None) -> int:
        now = self.clock() if now is None else now
        elapsed_ms = max(0, (now - record.submitted_at) * 1000)
        return min(9, record.spec.priority + int(elapsed_ms // self.config.aging_interval_ms))

    def request_stop(self, record: JobRecord, state: State, reason: str) -> bool:
        if state not in (State.CANCELLED, State.DEADLINE_EXCEEDED, State.FAILED, State.BUDGET_EXHAUSTED):
            raise ValueError("invalid stop state")
        if record.terminal or record.stop_state is not None:
            return False
        record.stop_state, record.stop_reason = state, reason
        if record.state is State.QUEUED:
            self._queues[record.spec.tenant].remove(record)
            self.pending -= 1
            record.state, record.reason = state, reason
            record.finished_at = self.clock()
        else:
            record.state = State.STOPPING
        return True
