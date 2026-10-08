"""Embed the scheduler around a custom callback using safe mock connectors."""

import asyncio
import json

from agent_budget_scheduler import Estimates, JobSpec, Scheduler, SchedulerConfig
from agent_budget_scheduler.mock import MOCK_ADAPTERS


async def summarize_release(context):
    record = await context.call("lookup.record", {"record": "release-a"})
    generated = await context.call("model.generate", {"input_tokens": 30, "output_tokens": 10},
                                   token_upper_bound=60)
    # Values return to the caller. The decision log never stores tool payloads.
    return {"record": record.value, "answer": generated.value}


async def main():
    async with Scheduler(SchedulerConfig(1, 1, 4), adapters=MOCK_ADAPTERS,
                         execution_mode="offline_mock") as scheduler:
        receipt = scheduler.submit(JobSpec("embedded-release", "engineering", priority=5,
                                           max_tool_calls=2, max_tokens=60,
                                           estimates=Estimates(tokens=100)), summarize_release)
        if not receipt.accepted:
            raise RuntimeError(f"submission rejected: {receipt.reason}")
        outcome = await scheduler.wait(receipt.job_id)
        print(json.dumps({"execution_mode": "offline_mock", "state": outcome.state.value,
                          "value": outcome.value, "summary": scheduler.report()["summary"]}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
