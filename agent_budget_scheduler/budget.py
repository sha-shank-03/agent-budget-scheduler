"""Reservations, observations and unknown usage are distinct quantities."""

from decimal import Decimal, localcontext

from .models import BudgetExceeded, JobFault, ReportedCost, TokenUsage, integer


class BudgetLedger:
    def __init__(self, max_calls: int, max_tokens: int):
        self.max_calls = integer(max_calls, "max_calls")
        self.max_tokens = integer(max_tokens, "max_tokens")
        self.started_tool_calls = 0
        self.observed_input_tokens = 0
        self.observed_output_tokens = 0
        self.unresolved_reserved_tokens = 0
        self.unknown_usage_calls = 0
        self.reservation_breaches = 0
        self._active: dict[int, int] = {}
        self._costs: list[ReportedCost] = []

    @property
    def observed_known_tokens(self) -> int:
        return self.observed_input_tokens + self.observed_output_tokens

    @property
    def active_reserved_tokens(self) -> int:
        return sum(self._active.values())

    @property
    def remaining_tokens(self) -> int:
        return self.max_tokens - self.observed_known_tokens - self.active_reserved_tokens - self.unresolved_reserved_tokens

    def reserve(self, upper_bound: int) -> int:
        integer(upper_bound, "token_upper_bound")
        # These checks plus counter/reservation mutation contain no await.
        if self.started_tool_calls >= self.max_calls:
            raise BudgetExceeded("tool_calls")
        if upper_bound > self.remaining_tokens:
            raise BudgetExceeded("tokens")
        self.started_tool_calls += 1
        operation_id = self.started_tool_calls
        self._active[operation_id] = upper_bound
        return operation_id

    def observe(self, operation_id: int, usage: TokenUsage, cost: ReportedCost | None) -> None:
        if not isinstance(usage, TokenUsage):
            raise ValueError("usage must be TokenUsage")
        bound = self._active.pop(operation_id)
        self.observed_input_tokens += usage.input_tokens
        self.observed_output_tokens += usage.output_tokens
        if cost is not None:
            self._costs.append(cost)
        if usage.total_tokens > bound:
            self.reservation_breaches += 1
            raise JobFault("usage_exceeds_reservation")

    def unknown(self, operation_id: int, cost: ReportedCost | None = None) -> None:
        self.unresolved_reserved_tokens += self._active.pop(operation_id)
        self.unknown_usage_calls += 1
        if cost is not None:
            self._costs.append(cost)

    def has_active(self, operation_id: int) -> bool:
        return operation_id in self._active

    def to_dict(self) -> dict:
        subtotals: dict[str, Decimal] = {}
        sources: dict[str, set[str]] = {}
        # Input contracts bound decimal precision; retain exact additions even across runs.
        with localcontext() as ctx:
            ctx.prec = 80
            for cost in self._costs:
                subtotals[cost.currency] = subtotals.get(cost.currency, Decimal(0)) + Decimal(cost.amount)
                sources.setdefault(cost.currency, set()).add(cost.source)
        complete_cost = len(self._costs) == self.started_tool_calls and not self._active
        reported_cost = None
        if complete_cost and len(subtotals) == 1:
            currency, amount = next(iter(subtotals.items()))
            reported_cost = {"amount": format(amount, "f"), "currency": currency,
                             "sources": sorted(sources[currency])}
        return {
            "started_tool_calls": self.started_tool_calls,
            "observed_input_tokens": self.observed_input_tokens,
            "observed_output_tokens": self.observed_output_tokens,
            "observed_known_tokens": self.observed_known_tokens,
            "active_reserved_tokens": self.active_reserved_tokens,
            "unresolved_reserved_tokens": self.unresolved_reserved_tokens,
            "unknown_usage_calls": self.unknown_usage_calls,
            "usage_complete": self.unknown_usage_calls == 0 and not self._active,
            "remaining_conservative_tokens": self.remaining_tokens,
            "reservation_breaches": self.reservation_breaches,
            "observed_token_overrun": max(0, self.observed_known_tokens - self.max_tokens),
            "reported_cost": reported_cost,
            "reported_cost_subtotals": [
                {"amount": format(subtotals[currency], "f"), "currency": currency,
                 "sources": sorted(sources[currency])} for currency in sorted(subtotals)
            ],
            "reported_cost_complete": complete_cost and len(subtotals) <= 1,
        }
