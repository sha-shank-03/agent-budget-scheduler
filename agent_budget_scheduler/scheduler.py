"""One event loop owns all job state and all dispatched operation tasks."""

import asyncio
import time
from collections import Counter
from decimal import Decimal, localcontext
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping

from .budget import BudgetLedger
from .models import (
    SCHEMA_VERSION, Admission, JobFault, JobOutcome, JobSpec, SchedulerConfig,
    State, ToolRequest, ToolResult, integer, label,
)
from .policy import DispatchPolicy, JobRecord

Adapter = Callable[[ToolRequest], Awaitable[ToolResult]]
Agent = Callable[["JobContext"], Awaitable[Any]]


class JobContext:
    """Call only registered tools; all started operations consume a call slot."""

    def __init__(self, scheduler: "Scheduler", record: JobRecord, ledger: BudgetLedger):
        self._scheduler = scheduler
        self._record = record
        self._ledger = ledger
        self._operations: dict[asyncio.Task, int] = {}
        self._closed = False
        self._fault: JobFault | None = None

    def _latch(self, fault: JobFault) -> None:
        if self._fault is None:
            self._fault = fault
        self._scheduler._request_stop(self._record, fault.state, fault.reason, cancel_task=False)

    async def call(self, tool: str, arguments: Mapping[str, Any] | None = None,
                   *, token_upper_bound: int = 0) -> ToolResult:
        self._scheduler._check_loop()
        if self._closed:
            raise JobFault("context_closed")
        self._scheduler._check_deadline(self._record, cancel_task=False)
        if self._record.stop_state is not None:
            raise JobFault(self._record.stop_reason, self._record.stop_state)
        if self._fault is not None:
            raise self._fault
        label(tool, "tool")
        integer(token_upper_bound, "token_upper_bound")
        if arguments is not None and not isinstance(arguments, Mapping):
            raise ValueError("arguments must be a mapping")
        adapter = self._scheduler._adapters.get(tool)
        if adapter is None:
            fault = JobFault("unknown_tool")
            self._latch(fault)
            raise fault
        try:
            operation_id = self._ledger.reserve(token_upper_bound)
        except JobFault as fault:
            self._latch(fault)
            self._scheduler._event("operation_denied", self._record, reason=fault.reason,
                                   token_upper_bound=token_upper_bound, usage=self._ledger.to_dict())
            raise
        self._scheduler._event("operation_started", self._record, operation_id=operation_id,
                               tool=tool, token_upper_bound=token_upper_bound,
                               active_reserved_tokens=self._ledger.active_reserved_tokens)
        request = ToolRequest(MappingProxyType(dict(arguments or {})), token_upper_bound)
        # The owned task includes reconciliation, not just the adapter callback.
        operation = asyncio.create_task(self._invoke(operation_id, tool, adapter, request))
        self._operations[operation] = operation_id
        try:
            return await operation
        finally:
            self._operations.pop(operation, None)
            if self._ledger.has_active(operation_id):
                # Covers cancellation before the owned task executes its first instruction.
                self._ledger.unknown(operation_id)
                self._latch(JobFault("operation_cancelled"))
                self._scheduler._event("operation_usage_unknown", self._record,
                                       operation_id=operation_id, tool=tool, usage=self._ledger.to_dict())

    async def _invoke(self, operation_id: int, tool: str, adapter: Adapter,
                      request: ToolRequest) -> ToolResult:
        known_cost = None
        try:
            result = await adapter(request)
            if not isinstance(result, ToolResult):
                raise JobFault("invalid_tool_result")
            known_cost = result.cost
            if result.usage is None:
                raise JobFault("usage_unknown")
            try:
                self._ledger.observe(operation_id, result.usage, result.cost)
            finally:
                # A breach is recorded at full observed usage, never clamped.
                self._scheduler._event("operation_observed", self._record,
                                       operation_id=operation_id, tool=tool,
                                       input_tokens=result.usage.input_tokens,
                                       output_tokens=result.usage.output_tokens,
                                       usage=self._ledger.to_dict())
            return result
        except BaseException as exc:
            if self._ledger.has_active(operation_id):
                self._ledger.unknown(operation_id, known_cost)
                self._scheduler._event("operation_usage_unknown", self._record,
                                       operation_id=operation_id, tool=tool,
                                       usage=self._ledger.to_dict())
            fault = exc if isinstance(exc, JobFault) else JobFault(
                "operation_cancelled" if isinstance(exc, asyncio.CancelledError) else "adapter_error"
            )
            self._latch(fault)
            if isinstance(exc, (JobFault, asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            raise fault from None

    async def _close(self) -> None:
        self._closed = True
        if self._operations:
            self._latch(JobFault("unawaited_operations"))
            operations = tuple(self._operations.items())
            for operation, _ in operations:
                operation.cancel()
            # A cooperative adapter may take time to clean up. Its job retains its slot.
            cleanup = asyncio.gather(*(operation for operation, _ in operations), return_exceptions=True)
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    # Parent cancellation is a stop request, not permission to release live capacity.
                    continue
            for _, operation_id in operations:
                # A task cancelled before its first coroutine instruction cannot reconcile itself.
                if self._ledger.has_active(operation_id):
                    self._ledger.unknown(operation_id)
                    self._scheduler._event("operation_usage_unknown", self._record,
                                           operation_id=operation_id, usage=self._ledger.to_dict())
            self._operations.clear()


class Scheduler:
    """Embeddable bounded-run scheduler. Exiting its context drains accepted jobs."""

    def __init__(self, config: SchedulerConfig | None = None, *,
                 adapters: Mapping[str, Adapter], execution_mode: str = "local_cooperative",
                 clock: Callable[[], float] = time.monotonic):
        if config is not None and not isinstance(config, SchedulerConfig):
            raise ValueError("config must be SchedulerConfig")
        self.config = config or SchedulerConfig()
        copied = dict(adapters)
        for name, adapter in copied.items():
            label(name, "adapter name")
            if not callable(adapter):
                raise ValueError("adapters must be callable")
        self._adapters = MappingProxyType(copied)
        self.execution_mode = label(execution_mode, "execution_mode")
        self._clock = clock
        self._policy = DispatchPolicy(self.config, clock)
        self._epoch = clock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._accepting = False
        self._agents: dict[str, Agent] = {}
        self._ledgers: dict[str, BudgetLedger] = {}
        self._futures: dict[str, asyncio.Future] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._pump_scheduled = False
        self._events: list[dict] = []
        self._entered_jobs: set[str] = set()
        self._cancel_sent: set[str] = set()
        self._deadline_notified: set[str] = set()
        self._deadline_handle: asyncio.TimerHandle | None = None
        self._published_terminal: set[str] = set()
        self._event_changed = asyncio.Event()

    async def __aenter__(self) -> "Scheduler":
        if self._loop is not None:
            raise RuntimeError("scheduler can only be entered once")
        self._loop = asyncio.get_running_loop()
        self._accepting = True
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self._accepting = False
        if exc_type is not None:
            for record in self._policy.records.values():
                if not record.terminal:
                    self.cancel(record.spec.job_id)
        await self.wait_all()
        if self._deadline_handle is not None:
            self._deadline_handle.cancel()

    def _check_loop(self) -> None:
        if self._loop is None or asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("use scheduler inside its async context on the owning event loop")

    def submit(self, spec: JobSpec, agent: Agent) -> Admission:
        self._check_loop()
        if not self._accepting:
            raise RuntimeError("scheduler is closed to submissions")
        if not isinstance(spec, JobSpec) or not callable(agent):
            raise ValueError("submit requires JobSpec and callable async agent")
        self._process_deadlines()
        receipt = self._policy.submit(spec)
        if not receipt.accepted:
            self._event("admission_rejected", job_id=spec.job_id, tenant=spec.tenant,
                        reason=receipt.reason, pending=self._policy.pending)
            return receipt
        self._agents[spec.job_id] = agent
        self._ledgers[spec.job_id] = BudgetLedger(spec.max_tool_calls, spec.max_tokens)
        self._futures[spec.job_id] = self._loop.create_future()
        self._event("admitted", self._policy.records[spec.job_id], pending=self._policy.pending)
        self._schedule_pump()
        self._arm_deadline()
        return receipt

    def _schedule_pump(self) -> None:
        if not self._pump_scheduled:
            self._pump_scheduled = True
            self._loop.call_soon(self._pump)

    def _pump(self) -> None:
        self._pump_scheduled = False
        self._process_deadlines()
        while (record := self._policy.dispatch()) is not None:
            self._event("dispatched", record, base_priority=record.spec.priority,
                        effective_priority=record.dispatched_priority,
                        running=self._policy.running,
                        tenant_running=self._policy.running_by_tenant[record.spec.tenant])
            self._tasks[record.spec.job_id] = asyncio.create_task(self._run_job(record))
        self._arm_deadline()

    async def _run_job(self, record: JobRecord) -> None:
        job_id = record.spec.job_id
        context = JobContext(self, record, self._ledgers[job_id])
        value = None
        fault = None
        self._entered_jobs.add(job_id)
        try:
            self._check_deadline(record, cancel_task=False)
            if record.stop_state is None:
                value = await self._agents[job_id](context)
        except JobFault as exc:
            fault = exc
        except asyncio.CancelledError:
            fault = JobFault("job_task_cancelled")
        except Exception:
            fault = JobFault("agent_error")
        finally:
            await context._close()
            self._check_deadline(record, cancel_task=False)
            # A caught denial/adapter fault cannot be turned into success by the agent.
            fault = context._fault or fault
            state = record.stop_state or (fault.state if fault is not None else State.SUCCEEDED)
            reason = record.stop_reason if record.stop_state is not None else (fault.reason if fault else None)
            self._policy.finish(record, state, reason)
            self._publish_terminal(record, value if state is State.SUCCEEDED else None)
            self._tasks.pop(job_id)
            self._schedule_pump()
            self._arm_deadline()

    def _publish_terminal(self, record: JobRecord, value=None) -> None:
        job_id = record.spec.job_id
        if job_id in self._published_terminal:
            return
        self._published_terminal.add(job_id)
        self._event("terminal", record, reason=record.reason, usage=self._ledgers[job_id].to_dict())
        self._futures[job_id].set_result(JobOutcome(job_id, record.state, record.reason, value))

    def _request_stop(self, record: JobRecord, state: State, reason: str, *, cancel_task=True) -> bool:
        changed = self._policy.request_stop(record, state, reason)
        if changed:
            self._event("stop_requested", record, reason=reason, target_state=state.value)
            if record.terminal:
                self._publish_terminal(record)
                self._schedule_pump()
        if cancel_task and record.state is State.STOPPING and record.spec.job_id not in self._cancel_sent:
            # Cancel a running coroutine once. A not-yet-entered task will check stop state itself.
            if record.spec.job_id in self._entered_jobs:
                self._cancel_sent.add(record.spec.job_id)
                self._tasks[record.spec.job_id].cancel()
        return changed

    def cancel(self, job_id: str) -> bool:
        """Return whether a new stop reason was latched; repeated requests are harmless."""
        self._check_loop()
        record = self._policy.records.get(job_id)
        if record is None:
            raise ValueError("job_id was not admitted")
        self._check_deadline(record)
        changed = self._request_stop(record, State.CANCELLED, "cancelled")
        self._arm_deadline()
        return changed

    def _check_deadline(self, record: JobRecord, *, cancel_task=True) -> None:
        if not record.terminal and record.deadline_at is not None and self._clock() >= record.deadline_at:
            self._deadline_notified.add(record.spec.job_id)
            self._request_stop(record, State.DEADLINE_EXCEEDED, "deadline", cancel_task=cancel_task)

    def _process_deadlines(self) -> None:
        for record in self._policy.records.values():
            self._check_deadline(record)

    def poll(self) -> None:
        """Reevaluate deadlines/dispatch after advancing an injected test clock."""
        self._check_loop()
        self._process_deadlines()
        self._schedule_pump()
        self._arm_deadline()

    def _arm_deadline(self) -> None:
        if self._deadline_handle is not None:
            self._deadline_handle.cancel()
            self._deadline_handle = None
        deadlines = [record.deadline_at for record in self._policy.records.values()
                     if not record.terminal and record.deadline_at is not None
                     and record.spec.job_id not in self._deadline_notified]
        if deadlines:
            self._deadline_handle = self._loop.call_later(max(0, min(deadlines) - self._clock()), self.poll)

    async def wait(self, job_id: str) -> JobOutcome:
        self._check_loop()
        if job_id not in self._futures:
            raise ValueError("job_id was not admitted")
        # Cancelling a waiter must not invalidate the job's completion receipt.
        return await asyncio.shield(self._futures[job_id])

    async def wait_all(self) -> list[JobOutcome]:
        self._check_loop()
        return await asyncio.gather(*(self.wait(job_id) for job_id in self._futures))

    def _event(self, event_type: str, record: JobRecord | None = None, **details) -> None:
        event = {"schema_version": SCHEMA_VERSION, "sequence": len(self._events) + 1,
                 "elapsed_ms": round((self._clock() - self._epoch) * 1000, 3),
                 "event_type": event_type}
        if record is not None:
            event.update(job_id=record.spec.job_id, tenant=record.spec.tenant, state=record.state.value)
        event.update(details)
        self._events.append(event)
        self._event_changed.set()

    async def wait_event(self, event_type: str, job_id: str) -> dict:
        """Observe the first matching event without polling or altering job execution."""
        self._check_loop()
        if job_id not in self._futures:
            raise ValueError("job_id was not admitted")
        while True:
            for event in self._events:
                if event["event_type"] == event_type and event.get("job_id") == job_id:
                    import copy
                    return copy.deepcopy(event)
            if self._policy.records[job_id].terminal:
                raise ValueError("job finished before the requested event")
            self._event_changed.clear()
            await self._event_changed.wait()

    def events(self) -> list[dict]:
        # Reports are detached JSON data, not writable views into scheduler state.
        import copy
        return copy.deepcopy(self._events)

    def report(self) -> dict:
        self._check_loop()
        jobs = []
        for job_id, record in self._policy.records.items():
            spec = record.spec
            jobs.append({
                "job_id": job_id, "tenant": spec.tenant, "priority": spec.priority,
                "state": record.state.value, "reason": record.reason,
                "limits": {"max_tool_calls": spec.max_tool_calls, "max_tokens": spec.max_tokens},
                "deadline_after_ms": spec.deadline_after_ms,
                "estimates": spec.estimates.to_dict(), "usage": self._ledgers[job_id].to_dict(),
                "queue_wait_ms": self._duration(record.submitted_at, record.started_at),
                "runtime_ms": self._duration(record.started_at, record.finished_at),
            })
        counts = Counter(job["state"] for job in jobs)
        usage = {
            key: sum(job["usage"][key] for job in jobs) for key in (
                "started_tool_calls", "observed_known_tokens", "active_reserved_tokens",
                "unresolved_reserved_tokens", "unknown_usage_calls", "reservation_breaches",
                "observed_token_overrun",
            )
        }
        usage["usage_complete"] = all(job["usage"]["usage_complete"] for job in jobs)
        # Preserve partial costs by currency; never infer a missing value from tokens.
        subtotals: dict[str, Decimal] = {}
        sources: dict[str, set[str]] = {}
        with localcontext() as ctx:
            ctx.prec = 80
            for job in jobs:
                for cost in job["usage"]["reported_cost_subtotals"]:
                    currency = cost["currency"]
                    subtotals[currency] = subtotals.get(currency, Decimal(0)) + Decimal(cost["amount"])
                    sources.setdefault(currency, set()).update(cost["sources"])
        complete_cost = all(job["usage"]["reported_cost_complete"] for job in jobs) and len(subtotals) <= 1
        usage["reported_cost_complete"] = complete_cost
        usage["reported_cost_subtotals"] = [
            {"amount": format(subtotals[currency], "f"), "currency": currency,
             "sources": sorted(sources[currency])} for currency in sorted(subtotals)
        ]
        usage["reported_cost"] = usage["reported_cost_subtotals"][0] if complete_cost and subtotals else None
        return {
            "schema_version": SCHEMA_VERSION, "execution_mode": self.execution_mode,
            "policy": "tenant_round_robin_aging_priority", "config": self.config.to_dict(),
            "summary": {"accepted": len(jobs), "rejected": len(self._policy.rejections),
                        "states": dict(sorted(counts.items())), "usage": usage,
                        "peak_running": self._policy.peak_running,
                        "peak_running_by_tenant": dict(self._policy.peak_running_by_tenant)},
            "jobs": jobs,
            "rejections": [{"job_id": item.job_id, "reason": item.reason}
                           for item in self._policy.rejections],
        }

    @staticmethod
    def _duration(start: float | None, end: float | None) -> float | None:
        return round((end - start) * 1000, 3) if start is not None and end is not None else None
