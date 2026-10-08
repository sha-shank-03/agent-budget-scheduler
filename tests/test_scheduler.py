import asyncio
from collections import Counter
import json
from pathlib import Path
import unittest

from agent_budget_scheduler import Estimates, JobSpec, Scheduler, SchedulerConfig, TokenUsage, ToolResult
from agent_budget_scheduler.models import BudgetExceeded, State
from agent_budget_scheduler.mock import MOCK_ADAPTERS, parse_workload, scripted_agent

ROOT = Path(__file__).resolve().parents[1]


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_literal_basic_totals_and_estimates_remain_distinct(self):
        config, jobs = parse_workload(json.loads((ROOT / "examples/basic.json").read_text(encoding="utf-8")))
        async with Scheduler(config, adapters=MOCK_ADAPTERS, execution_mode="offline_mock") as scheduler:
            for job in jobs:
                self.assertTrue(scheduler.submit(job.spec, scripted_agent(job)).accepted)
            outcomes = await asyncio.wait_for(scheduler.wait_all(), 2)
            report = scheduler.report()
            self.assertEqual([outcome.state for outcome in outcomes], [State.SUCCEEDED, State.SUCCEEDED])
            self.assertTrue(all("[MOCK]" in outcome.value for outcome in outcomes))
            summary = report["summary"]
            self.assertEqual(summary["states"], {"SUCCEEDED": 2})
            self.assertEqual(summary["usage"]["started_tool_calls"], 4)
            self.assertEqual(summary["usage"]["observed_known_tokens"], 65)
            self.assertEqual(summary["usage"]["unknown_usage_calls"], 0)
            self.assertEqual(summary["usage"]["active_reserved_tokens"], 0)
            self.assertEqual(summary["usage"]["unresolved_reserved_tokens"], 0)
            self.assertEqual(summary["usage"]["reservation_breaches"], 0)
            self.assertEqual(summary["usage"]["observed_token_overrun"], 0)
            self.assertEqual(summary["usage"]["reported_cost"],
                             {"amount": "0.000065", "currency": "USD", "sources": ["synthetic_mock"]})
            self.assertEqual([job["estimates"]["tokens"] for job in report["jobs"]], [100, 200])
            self.assertEqual([job["usage"]["observed_known_tokens"] for job in report["jobs"]], [40, 25])
            self.assertEqual([job["estimates"]["cost"]["amount"] for job in report["jobs"]], ["0.50", "0.75"])
            self.assertEqual([job["usage"]["remaining_conservative_tokens"] for job in report["jobs"]], [20, 15])

    async def test_actual_callback_capacity_is_globally_and_per_tenant_bounded(self):
        release = asyncio.Event()
        two_active = asyncio.Event()
        active = Counter()
        peaks = Counter()
        global_active = 0
        global_peak = 0
        order = []

        def callback(job_id, tenant):
            async def run(context):
                nonlocal global_active, global_peak
                global_active += 1
                active[tenant] += 1
                global_peak = max(global_peak, global_active)
                peaks[tenant] = max(peaks[tenant], active[tenant])
                order.append(job_id)
                if global_active == 2:
                    two_active.set()
                try:
                    await release.wait()
                finally:
                    active[tenant] -= 1
                    global_active -= 1
            return run

        async with Scheduler(SchedulerConfig(2, 1, 8), adapters={}) as scheduler:
            try:
                for job_id, tenant in (("a1", "a"), ("a2", "a"), ("b1", "b"), ("b2", "b"), ("c1", "c")):
                    scheduler.submit(JobSpec(job_id, tenant), callback(job_id, tenant))
                await asyncio.wait_for(two_active.wait(), 2)
                self.assertEqual(order, ["a1", "b1"])
                self.assertEqual(global_active, 2)
                self.assertEqual(dict(active), {"a": 1, "b": 1})
                self.assertEqual(scheduler.report()["summary"]["states"], {"QUEUED": 3, "RUNNING": 2})
            finally:
                release.set()
                outcomes = await asyncio.wait_for(scheduler.wait_all(), 2)
            self.assertEqual(global_peak, 2)
            self.assertTrue(all(peak == 1 for peak in peaks.values()))
            self.assertEqual(global_active, 0)
            self.assertEqual(len(outcomes), 5)
            self.assertTrue(all(outcome.state is State.SUCCEEDED for outcome in outcomes))

    async def test_competing_reservations_cannot_both_start(self):
        started = asyncio.Event()
        release = asyncio.Event()
        entered = 0

        async def controlled_adapter(request):
            nonlocal entered
            entered += 1
            started.set()
            await release.wait()
            return ToolResult("done", TokenUsage(40, 20))

        async def agent(context):
            first = asyncio.create_task(context.call("controlled", token_upper_bound=60))
            try:
                await asyncio.wait_for(started.wait(), 2)
                with self.assertRaises(BudgetExceeded) as denied:
                    await context.call("controlled", token_upper_bound=60)
                self.assertEqual(denied.exception.reason, "tokens")
                live = scheduler.report()["jobs"][0]["usage"]
                self.assertEqual(live["active_reserved_tokens"], 60)
                self.assertEqual(live["started_tool_calls"], 1)
                self.assertEqual(live["observed_known_tokens"], 0)
            finally:
                release.set()
                await first
            return "agent caught the denial"

        async with Scheduler(adapters={"controlled": controlled_adapter}) as scheduler:
            scheduler.submit(JobSpec("race", "tenant", max_tokens=100, max_tool_calls=2), agent)
            try:
                result = await asyncio.wait_for(scheduler.wait("race"), 2)
            finally:
                release.set()  # A regression must fail with a timeout rather than hang teardown.
            self.assertEqual(result.state, State.BUDGET_EXHAUSTED)
            self.assertEqual(result.reason, "tokens")
            self.assertIsNone(result.value)  # Catching a denial does not turn the job into success.
            usage = scheduler.report()["jobs"][0]["usage"]
            self.assertEqual(entered, 1)
            self.assertEqual(usage["observed_known_tokens"], 60)
            self.assertEqual(usage["remaining_conservative_tokens"], 40)
            self.assertEqual(usage["active_reserved_tokens"], 0)
            self.assertEqual(usage["unknown_usage_calls"], 0)

    async def test_unused_reservation_is_released_for_next_operation(self):
        calls = 0

        async def adapter(request):
            nonlocal calls
            calls += 1
            return ToolResult(usage=TokenUsage(20, 20))

        async def agent(context):
            await context.call("controlled", token_upper_bound=60)
            await context.call("controlled", token_upper_bound=60)

        async with Scheduler(adapters={"controlled": adapter}) as scheduler:
            scheduler.submit(JobSpec("reuse", "t", max_tokens=100, max_tool_calls=2,
                                      estimates=Estimates(tokens=1)), agent)
            result = await asyncio.wait_for(scheduler.wait("reuse"), 2)
            self.assertEqual(result.state, State.SUCCEEDED)
            self.assertEqual(calls, 2)
            report = scheduler.report()["jobs"][0]
            self.assertEqual(report["usage"]["observed_known_tokens"], 80)
            self.assertEqual(report["usage"]["remaining_conservative_tokens"], 20)
            self.assertEqual(report["estimates"]["tokens"], 1)
            self.assertIsNone(report["usage"]["reported_cost"])
            self.assertFalse(report["usage"]["reported_cost_complete"])

    async def test_call_denial_does_not_invoke_adapter_or_increment_started_count(self):
        invoked = 0

        async def adapter(request):
            nonlocal invoked
            invoked += 1
            return ToolResult(usage=TokenUsage())

        async def agent(context):
            await context.call("lookup")
            try:
                await context.call("lookup")
            except BudgetExceeded:
                pass

        async with Scheduler(adapters={"lookup": adapter}) as scheduler:
            scheduler.submit(JobSpec("one-call", "t", max_tool_calls=1, max_tokens=0), agent)
            outcome = await asyncio.wait_for(scheduler.wait("one-call"), 2)
            self.assertEqual(outcome.state, State.BUDGET_EXHAUSTED)
            self.assertEqual(outcome.reason, "tool_calls")
            self.assertEqual(invoked, 1)
            self.assertEqual(scheduler.report()["summary"]["usage"]["started_tool_calls"], 1)
