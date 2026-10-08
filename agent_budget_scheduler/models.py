"""Validated local contracts. No network protocol or provider SDK is involved."""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping

SCHEMA_VERSION = "1.0"


def integer(value: Any, name: str, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} must be an integer from {minimum}"
                         + (f" through {maximum}" if maximum is not None else " upward"))
    return value


def label(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError(f"{name} must be a nonempty string of at most 128 characters")
    if any(not (c.isascii() and (c.isalnum() or c in "._:-")) for c in value):
        raise ValueError(f"{name} may contain only ASCII letters, digits, . _ : -")
    return value


def fields(value: Any, allowed: set[str], required: set[str], name: str) -> dict:
    if type(value) is not dict:
        raise ValueError(f"{name} must be an object")
    unknown = value.keys() - allowed
    missing = required - value.keys()
    if unknown or missing:
        # Unknown keys are untrusted text and may themselves contain sensitive values.
        raise ValueError(f"{name}: {len(unknown)} unsupported fields; missing fields {sorted(missing)}")
    return value


@dataclass(frozen=True)
class ReportedCost:
    amount: str
    currency: str = "USD"
    source: str = "adapter_reported"

    def __post_init__(self) -> None:
        if not isinstance(self.amount, str) or len(self.amount) > 64:
            raise ValueError("cost amount must be a decimal string of at most 64 characters")
        try:
            number = Decimal(self.amount)
        except InvalidOperation as exc:
            raise ValueError("cost amount must be a decimal string") from exc
        if not number.is_finite() or number < 0:
            raise ValueError("cost amount must be finite and nonnegative")
        # Bound exponent/precision so reporting cannot allocate unbounded decimal output.
        if abs(number.as_tuple().exponent) > 12 or len(number.as_tuple().digits) > 24:
            raise ValueError("cost amount exceeds supported decimal precision")
        if not isinstance(self.currency, str) or len(self.currency) != 3 or not (
            self.currency.isascii() and self.currency.isalpha() and self.currency.isupper()
        ):
            raise ValueError("cost currency must be three uppercase ASCII letters")
        label(self.source, "cost source")

    def to_dict(self) -> dict:
        return {"amount": self.amount, "currency": self.currency, "source": self.source}


@dataclass(frozen=True)
class Estimates:
    tokens: int | None = None
    duration_ms: int | None = None
    cost: ReportedCost | None = None

    def __post_init__(self) -> None:
        if self.tokens is not None:
            integer(self.tokens, "estimated tokens")
        if self.duration_ms is not None:
            integer(self.duration_ms, "estimated duration_ms")
        if self.cost is not None and not isinstance(self.cost, ReportedCost):
            raise ValueError("estimated cost must be ReportedCost")

    def to_dict(self) -> dict:
        return {"tokens": self.tokens, "duration_ms": self.duration_ms,
                "cost": self.cost.to_dict() if self.cost is not None else None}


@dataclass(frozen=True)
class SchedulerConfig:
    max_running: int = 2
    max_running_per_tenant: int = 1
    max_pending: int = 64
    aging_interval_ms: int = 1000

    def __post_init__(self) -> None:
        for name in ("max_running", "max_running_per_tenant", "max_pending", "aging_interval_ms"):
            integer(getattr(self, name), name, minimum=1)

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in
                ("max_running", "max_running_per_tenant", "max_pending", "aging_interval_ms")}


@dataclass(frozen=True)
class JobSpec:
    job_id: str
    tenant: str
    priority: int = 0
    max_tool_calls: int = 10
    max_tokens: int = 1000
    estimates: Estimates = field(default_factory=Estimates)
    deadline_after_ms: int | None = None

    def __post_init__(self) -> None:
        label(self.job_id, "job_id")
        label(self.tenant, "tenant")
        integer(self.priority, "priority", maximum=9)
        integer(self.max_tool_calls, "max_tool_calls")
        integer(self.max_tokens, "max_tokens")
        if not isinstance(self.estimates, Estimates):
            raise ValueError("estimates must be Estimates")
        if self.deadline_after_ms is not None:
            integer(self.deadline_after_ms, "deadline_after_ms", minimum=1, maximum=86400000)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        integer(self.input_tokens, "input_tokens")
        integer(self.output_tokens, "output_tokens")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class ToolRequest:
    arguments: Mapping[str, Any]
    token_upper_bound: int


@dataclass(frozen=True)
class ToolResult:
    value: Any = None
    usage: TokenUsage | None = None
    cost: ReportedCost | None = None

    def __post_init__(self) -> None:
        if self.usage is not None and not isinstance(self.usage, TokenUsage):
            raise ValueError("tool usage must be TokenUsage or None")
        if self.cost is not None and not isinstance(self.cost, ReportedCost):
            raise ValueError("tool cost must be ReportedCost or None")


class State(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    SUCCEEDED = "SUCCEEDED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"


@dataclass(frozen=True)
class Admission:
    job_id: str
    accepted: bool
    reason: str | None = None


@dataclass(frozen=True)
class JobOutcome:
    job_id: str
    state: State
    reason: str | None
    value: Any = None


class JobFault(Exception):
    """A stable diagnostic reason. Arbitrary exception text is never logged."""

    def __init__(self, reason: str, state: State = State.FAILED):
        super().__init__(reason)
        self.reason = reason
        self.state = state


class BudgetExceeded(JobFault):
    def __init__(self, reason: str):
        super().__init__(reason, State.BUDGET_EXHAUSTED)
