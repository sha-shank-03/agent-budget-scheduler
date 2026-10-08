"""Synthetic connectors: no provider calls, tokenization or external data."""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from .models import (
    SCHEMA_VERSION, Estimates, JobSpec, ReportedCost, SchedulerConfig,
    TokenUsage, ToolRequest, ToolResult, fields, integer,
)

RECORDS = MappingProxyType({
    "release-a": "Synthetic release A passed its offline checks.",
    "release-b": "Synthetic release B needs a fictional follow-up review.",
})


def validate_mock_arguments(tool: str, arguments: dict, upper_bound: int) -> None:
    integer(upper_bound, "token_upper_bound")
    if tool == "lookup.record":
        fields(arguments, {"record", "delay_ms", "cleanup_delay_ms"}, {"record"}, "lookup arguments")
        if not isinstance(arguments["record"], str) or arguments["record"] not in RECORDS:
            raise ValueError("lookup record must be a known synthetic record")
    elif tool in ("model.generate", "fault.overrun"):
        fields(arguments, {"input_tokens", "output_tokens", "delay_ms", "cleanup_delay_ms"},
               {"input_tokens", "output_tokens"}, "mock model arguments")
        usage = TokenUsage(arguments["input_tokens"], arguments["output_tokens"])
        if tool == "model.generate" and usage.total_tokens > upper_bound:
            raise ValueError("mock token usage exceeds the declared reservation")
        if tool == "fault.overrun" and usage.total_tokens <= upper_bound:
            raise ValueError("fault.overrun must intentionally exceed its declared reservation")
    elif tool in ("fault.raise", "fault.missing_usage"):
        fields(arguments, {"delay_ms", "cleanup_delay_ms"}, set(), "mock fault arguments")
    else:
        raise ValueError("unknown mock tool")
    integer(arguments.get("delay_ms", 0), "delay_ms", maximum=1000)
    integer(arguments.get("cleanup_delay_ms", 0), "cleanup_delay_ms", maximum=1000)


async def _mock_delay(arguments):
    try:
        await asyncio.sleep(arguments.get("delay_ms", 0) / 1000)
    except asyncio.CancelledError:
        await asyncio.sleep(arguments.get("cleanup_delay_ms", 0) / 1000)
        raise


async def lookup_record(request: ToolRequest) -> ToolResult:
    arguments = dict(request.arguments)
    validate_mock_arguments("lookup.record", arguments, request.token_upper_bound)
    await _mock_delay(arguments)
    return ToolResult(RECORDS[arguments["record"]], TokenUsage(),
                      ReportedCost("0", source="synthetic_mock"))


async def mock_model(request: ToolRequest) -> ToolResult:
    arguments = dict(request.arguments)
    validate_mock_arguments("model.generate", arguments, request.token_upper_bound)
    await _mock_delay(arguments)
    usage = TokenUsage(arguments["input_tokens"], arguments["output_tokens"])
    # This fictional rate is not an OpenAI or other provider price.
    cost = ReportedCost(format(Decimal(usage.total_tokens) * Decimal("0.000001"), "f"),
                        source="synthetic_mock")
    return ToolResult("[MOCK] deterministic synthetic summary", usage, cost)


async def _mock_fault(request: ToolRequest, tool: str) -> ToolResult:
    arguments = dict(request.arguments)
    validate_mock_arguments(tool, arguments, request.token_upper_bound)
    await _mock_delay(arguments)
    if tool == "fault.raise":
        raise RuntimeError("deliberate synthetic adapter failure")
    if tool == "fault.missing_usage":
        return ToolResult("[MOCK FAULT] missing telemetry")
    usage = TokenUsage(arguments["input_tokens"], arguments["output_tokens"])
    return ToolResult("[MOCK FAULT] dishonest bound", usage,
                      ReportedCost(format(Decimal(usage.total_tokens) * Decimal("0.000001"), "f"),
                                   source="synthetic_mock"))


async def fault_raise(request):
    return await _mock_fault(request, "fault.raise")


async def fault_missing_usage(request):
    return await _mock_fault(request, "fault.missing_usage")


async def fault_overrun(request):
    return await _mock_fault(request, "fault.overrun")


MOCK_ADAPTERS = MappingProxyType({
    "lookup.record": lookup_record, "model.generate": mock_model,
    "fault.raise": fault_raise, "fault.missing_usage": fault_missing_usage, "fault.overrun": fault_overrun,
})


@dataclass(frozen=True)
class ScriptedOperation:
    tool: str
    token_upper_bound: int
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ScriptedJob:
    spec: JobSpec
    operations: tuple[ScriptedOperation, ...]
    cancel_after_ms: int | None = None


def parse_workload(document: Any) -> tuple[SchedulerConfig, tuple[ScriptedJob, ...]]:
    fields(document, {"schema_version", "execution_mode", "config", "jobs"},
           {"schema_version", "execution_mode", "config", "jobs"}, "workload")
    if document["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported schema_version; expected 1.0")
    if document["execution_mode"] != "offline_mock":
        raise ValueError("CLI supports execution_mode offline_mock only")
    config_fields = {"max_running", "max_running_per_tenant", "max_pending", "aging_interval_ms"}
    config = SchedulerConfig(**fields(document["config"], config_fields, set(), "config"))
    if type(document["jobs"]) is not list or not 1 <= len(document["jobs"]) <= 1000:
        raise ValueError("jobs must be a list containing 1 through 1000 jobs")
    jobs = []
    seen = set()
    operation_count = 0
    for item in document["jobs"]:
        fields(item, {"job_id", "tenant", "priority", "max_tool_calls", "max_tokens", "estimates", "operations",
                      "deadline_after_ms", "cancel_after_ms"},
               {"job_id", "tenant", "max_tool_calls", "max_tokens", "operations"}, "job")
        estimates = fields(item.get("estimates", {}), {"tokens", "duration_ms", "cost"}, set(), "estimates")
        cost = estimates.get("cost")
        if cost is not None:
            cost = ReportedCost(**fields(cost, {"amount", "currency", "source"},
                                          {"amount", "currency", "source"}, "estimated cost"))
        spec = JobSpec(item["job_id"], item["tenant"], item.get("priority", 0),
                       item["max_tool_calls"], item["max_tokens"],
                       Estimates(estimates.get("tokens"), estimates.get("duration_ms"), cost),
                       item.get("deadline_after_ms"))
        cancel_after_ms = item.get("cancel_after_ms")
        if cancel_after_ms is not None:
            integer(cancel_after_ms, "cancel_after_ms", maximum=10000)
        if spec.job_id in seen:
            raise ValueError("duplicate job_id")
        seen.add(spec.job_id)
        operations = item["operations"]
        if type(operations) is not list or not 1 <= len(operations) <= 100:
            raise ValueError("operations must contain 1 through 100 entries")
        operation_count += len(operations)
        if operation_count > 10000:
            raise ValueError("workload exceeds 10000 operations")
        parsed = []
        for operation in operations:
            fields(operation, {"tool", "token_upper_bound", "arguments"},
                   {"tool", "token_upper_bound", "arguments"}, "operation")
            if not isinstance(operation["tool"], str):
                raise ValueError("tool must be a string")
            if type(operation["arguments"]) is not dict:
                raise ValueError("operation arguments must be an object")
            validate_mock_arguments(operation["tool"], operation["arguments"], operation["token_upper_bound"])
            parsed.append(ScriptedOperation(operation["tool"], operation["token_upper_bound"],
                                            dict(operation["arguments"])))
        jobs.append(ScriptedJob(spec, tuple(parsed), cancel_after_ms))
    return config, tuple(jobs)


def scripted_agent(job: ScriptedJob):
    async def run(context):
        result = None
        for operation in job.operations:
            result = await context.call(operation.tool, operation.arguments,
                                        token_upper_bound=operation.token_upper_bound)
        return result.value if result is not None else None
    return run
