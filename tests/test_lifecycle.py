import asyncio
import json
import unittest

from agent_budget_scheduler import JobSpec, ReportedCost, Scheduler, SchedulerConfig, TokenUsage, ToolResult
from agent_budget_scheduler.models import JobFault, State


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance_ms(self, milliseconds):
        self.now += milliseconds / 1000


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_queued_cancel_never_starts_a_callback_or_adapter(self):
        invoked = 0

        async def adapter(request):
            nonlocal invoked
            invoked += 1
            return ToolResult(usage=TokenUsage())

        async def agent(context):
            return await context.call("lookup")

        async with Scheduler(adapters={"lookup": adapter}) as scheduler:
            scheduler.submit(JobSpec("queued", "t"), agent)
            self.assertTrue(scheduler.cancel("queued"))
            self.assertFalse(scheduler.cancel("queued"))
            result = await asyncio.wait_for(scheduler.wait("queued"), 2)
            self.assertEqual(result.state, State.CANCELLED)
            self.assertEqual(invoked, 0)
            self.assertEqual(scheduler.report()["summary"]["peak_running"], 0)
            self.assertEqual(sum(e["event_type"] == "terminal" for e in scheduler.events()), 1)

    async def test_cancel_between_dispatch_and_callback_entry_resolves_job(self):
        invoked = 0

        async def agent(context):
            nonlocal invoked
            invoked += 1

        async with Scheduler(adapters={}) as scheduler:
            scheduler.submit(JobSpec("before-entry", "t"), agent)
            cancelled = asyncio.get_running_loop().create_future()
            # submit queued the pump first. This callback runs after pump dispatch and
            # before the newly-created job task gets its first event-loop turn.
            asyncio.get_running_loop().call_soon(
                lambda: cancelled.set_result(scheduler.cancel("before-entry"))
            )
            self.assertTrue(await asyncio.wait_for(cancelled, 2))
            result = await asyncio.wait_for(scheduler.wait("before-entry"), 2)
            self.assertEqual(result.state, State.CANCELLED)
            self.assertEqual(invoked, 0)
            self.assertEqual(scheduler.report()["summary"]["peak_running"], 1)

    async def test_cancelled_waiter_does_not_cancel_job(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def agent(context):
            entered.set()
            await release.wait()
            return "finished normally"

        async with Scheduler(adapters={}) as scheduler:
            scheduler.submit(JobSpec("waited", "t"), agent)
            waiter = asyncio.create_task(scheduler.wait("waited"))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                waiter.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await waiter
                self.assertEqual(scheduler.report()["jobs"][0]["state"], "RUNNING")
            finally:
                release.set()
            result = await asyncio.wait_for(scheduler.wait("waited"), 2)
            self.assertEqual(result.state, State.SUCCEEDED)
            self.assertEqual(result.value, "finished normally")
            self.assertFalse(scheduler.cancel("waited"))

    async def test_cancel_before_adapter_entry_releases_active_reservation_as_unknown(self):
        invoked = 0

        async def adapter(request):
            nonlocal invoked
            invoked += 1
            return ToolResult(usage=TokenUsage())

        async def agent(context):
            await context.call("not-entered", token_upper_bound=20)

        async with Scheduler(adapters={"not-entered": adapter}) as scheduler:
            scheduler.submit(JobSpec("scheduled", "t"), agent)
            # timeout() preserves this observer's task, unlike wait_for() creating another task.
            async with asyncio.timeout(2):
                await scheduler.wait_event("operation_started", "scheduled")
                scheduler.cancel("scheduled")
                outcome = await scheduler.wait("scheduled")
            self.assertEqual(outcome.state, State.CANCELLED)
            self.assertEqual(invoked, 0)
            usage = scheduler.report()["jobs"][0]["usage"]
            self.assertEqual(usage["active_reserved_tokens"], 0)
            self.assertEqual(usage["unknown_usage_calls"], 1)
            self.assertEqual(usage["unresolved_reserved_tokens"], 20)

    async def _running_stop_keeps_slot(self, by_deadline):
        clock = FakeClock()
        entered, cleanup_started, cleanup_release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        next_entered = asyncio.Event()
        calls = []

        async def adapter(request):
            calls.append("first")
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleanup_started.set()
                await cleanup_release.wait()
                raise

        async def first(context):
            await context.call("held", token_upper_bound=60)
            await context.call("held", token_upper_bound=20)

        async def follower(context):
            next_entered.set()

        async with Scheduler(SchedulerConfig(1, 1, 8), adapters={"held": adapter}, clock=clock) as scheduler:
            scheduler.submit(JobSpec("first", "a", max_tokens=100, deadline_after_ms=10), first)
            scheduler.submit(JobSpec("next", "b"), follower)
            try:
                await asyncio.wait_for(entered.wait(), 2)
                if by_deadline:
                    clock.advance_ms(10)
                    scheduler.poll()
                else:
                    self.assertTrue(scheduler.cancel("first"))
                await asyncio.wait_for(cleanup_started.wait(), 2)
                self.assertFalse(scheduler.cancel("first"))
                # A later deadline/cancel cannot interrupt cleanup or replace the first cause.
                clock.advance_ms(10)
                scheduler.poll()
                live = scheduler.report()
                self.assertEqual(live["jobs"][0]["state"], "STOPPING")
                self.assertEqual(live["jobs"][1]["state"], "QUEUED")
                self.assertFalse(next_entered.is_set())
                self.assertEqual(live["jobs"][0]["usage"]["active_reserved_tokens"], 60)
                self.assertEqual(calls, ["first"])
            finally:
                cleanup_release.set()
            outcomes = await asyncio.wait_for(scheduler.wait_all(), 2)
            expected = State.DEADLINE_EXCEEDED if by_deadline else State.CANCELLED
            self.assertEqual([item.state for item in outcomes], [expected, State.SUCCEEDED])
            self.assertEqual(outcomes[0].reason, "deadline" if by_deadline else "cancelled")
            self.assertTrue(next_entered.is_set())
            usage = scheduler.report()["jobs"][0]["usage"]
            self.assertEqual(usage["started_tool_calls"], 1)
            self.assertEqual(usage["active_reserved_tokens"], 0)
            self.assertEqual(usage["observed_known_tokens"], 0)
            self.assertEqual(usage["unknown_usage_calls"], 1)
            self.assertEqual(usage["unresolved_reserved_tokens"], 60)
            self.assertFalse(usage["usage_complete"])
            self.assertIsNone(usage["reported_cost"])
            self.assertEqual(sum(e["event_type"] == "terminal" and e.get("job_id") == "first"
                                 for e in scheduler.events()), 1)

    async def test_running_cancel_holds_slot_until_actual_cleanup_finishes(self):
        await self._running_stop_keeps_slot(False)

    async def test_running_deadline_holds_slot_until_actual_cleanup_finishes(self):
        await self._running_stop_keeps_slot(True)

    async def test_queued_deadline_counts_from_submission_and_invokes_nothing(self):
        clock = FakeClock()
        entered, release = asyncio.Event(), asyncio.Event()
        invoked = 0

        async def blocker(context):
            entered.set()
            await release.wait()

        async def queued(context):
            nonlocal invoked
            invoked += 1

        async with Scheduler(SchedulerConfig(1, 1, 8), adapters={}, clock=clock) as scheduler:
            scheduler.submit(JobSpec("blocker", "a"), blocker)
            scheduler.submit(JobSpec("queued", "b", deadline_after_ms=10), queued)
            try:
                await asyncio.wait_for(entered.wait(), 2)
                clock.advance_ms(10)
                scheduler.poll()
                outcome = await asyncio.wait_for(scheduler.wait("queued"), 2)
                self.assertEqual(outcome.state, State.DEADLINE_EXCEEDED)
                self.assertEqual(invoked, 0)
                self.assertIsNone(scheduler.report()["jobs"][1]["runtime_ms"])
            finally:
                release.set()
            await asyncio.wait_for(scheduler.wait_all(), 2)

    async def test_deadline_is_checked_at_completion_even_without_timer_delivery(self):
        clock = FakeClock()

        async def agent(context):
            clock.advance_ms(10)
            return "late"

        async with Scheduler(adapters={}, clock=clock) as scheduler:
            scheduler.submit(JobSpec("late", "t", deadline_after_ms=10), agent)
            outcome = await asyncio.wait_for(scheduler.wait("late"), 2)
            self.assertEqual(outcome.state, State.DEADLINE_EXCEEDED)
            self.assertIsNone(outcome.value)

    async def test_cancel_after_due_deadline_expires_queue_before_timer_delivery(self):
        clock = FakeClock()
        invoked = 0

        async def agent(context):
            nonlocal invoked
            invoked += 1

        async with Scheduler(adapters={}, clock=clock) as scheduler:
            scheduler.submit(JobSpec("due", "t", deadline_after_ms=10), agent)
            clock.advance_ms(10)
            self.assertFalse(scheduler.cancel("due"))
            outcome = await asyncio.wait_for(scheduler.wait("due"), 2)
            self.assertEqual(outcome.state, State.DEADLINE_EXCEEDED)
            self.assertEqual(invoked, 0)

    async def test_expired_running_job_cannot_start_tool_before_timer_delivery(self):
        clock = FakeClock()
        invoked = 0

        async def adapter(request):
            nonlocal invoked
            invoked += 1
            return ToolResult(usage=TokenUsage())

        async def agent(context):
            clock.advance_ms(10)
            try:
                await context.call("late")
            except JobFault:
                pass
            return "caught the deadline"

        async with Scheduler(adapters={"late": adapter}, clock=clock) as scheduler:
            scheduler.submit(JobSpec("late-call", "t", deadline_after_ms=10), agent)
            outcome = await asyncio.wait_for(scheduler.wait("late-call"), 2)
            self.assertEqual(outcome.state, State.DEADLINE_EXCEEDED)
            self.assertEqual(invoked, 0)
            self.assertEqual(scheduler.report()["jobs"][0]["usage"]["started_tool_calls"], 0)

    async def test_suppressed_cancellation_cannot_start_another_call_or_return_success(self):
        entered = asyncio.Event()
        calls = 0

        async def adapter(request):
            nonlocal calls
            calls += 1
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return ToolResult("already consumed", TokenUsage(20, 20))

        async def agent(context):
            await context.call("held", token_upper_bound=40)
            try:
                await context.call("held", token_upper_bound=40)
            except JobFault:
                pass
            return "caught the stop"

        async with Scheduler(adapters={"held": adapter}) as scheduler:
            scheduler.submit(JobSpec("suppressed", "t"), agent)
            await asyncio.wait_for(entered.wait(), 2)
            scheduler.cancel("suppressed")
            outcome = await asyncio.wait_for(scheduler.wait("suppressed"), 2)
            self.assertEqual(outcome.state, State.CANCELLED)
            self.assertIsNone(outcome.value)
            self.assertEqual(calls, 1)
            usage = scheduler.report()["jobs"][0]["usage"]
            self.assertEqual(usage["observed_known_tokens"], 40)
            self.assertEqual(usage["unknown_usage_calls"], 0)

    async def test_owned_unawaited_operation_cleanup_is_shielded_from_later_cancel(self):
        entered, cleanup_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        follower_entered = asyncio.Event()
        child = None

        async def adapter(request):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleanup_started.set()
                await release.wait()
                raise

        async def agent(context):
            nonlocal child
            child = asyncio.create_task(context.call("held", token_upper_bound=20))
            await entered.wait()

        async def follower(context):
            follower_entered.set()

        async with Scheduler(SchedulerConfig(1, 1, 8), adapters={"held": adapter}) as scheduler:
            scheduler.submit(JobSpec("unawaited", "a"), agent)
            scheduler.submit(JobSpec("follower", "b"), follower)
            try:
                await asyncio.wait_for(cleanup_started.wait(), 2)
                scheduler.cancel("unawaited")
                await asyncio.sleep(0)  # Deliver the parent stop while cleanup's gate remains closed.
                self.assertFalse(follower_entered.is_set())
                self.assertEqual(scheduler.report()["jobs"][0]["state"], "STOPPING")
            finally:
                release.set()
            outcomes = await asyncio.wait_for(scheduler.wait_all(), 2)
            self.assertEqual(outcomes[0].state, State.FAILED)
            self.assertEqual(outcomes[0].reason, "unawaited_operations")
            self.assertEqual(outcomes[1].state, State.SUCCEEDED)
            await asyncio.gather(child, return_exceptions=True)

    async def test_unknown_usage_retains_bound_and_known_reported_cost(self):
        calls = 0

        async def adapter(request):
            nonlocal calls
            calls += 1
            return ToolResult(cost=ReportedCost("0.125", source="synthetic_mock"))

        async def agent(context):
            for _ in range(2):
                try:
                    await context.call("missing", token_upper_bound=35)
                except JobFault:
                    pass

        async with Scheduler(adapters={"missing": adapter}) as scheduler:
            scheduler.submit(JobSpec("unknown", "t", max_tokens=100), agent)
            outcome = await asyncio.wait_for(scheduler.wait("unknown"), 2)
            self.assertEqual(outcome.state, State.FAILED)
            self.assertEqual(outcome.reason, "usage_unknown")
            self.assertEqual(calls, 1)
            usage = scheduler.report()["jobs"][0]["usage"]
            self.assertEqual(usage["observed_known_tokens"], 0)
            self.assertEqual(usage["unresolved_reserved_tokens"], 35)
            self.assertEqual(usage["remaining_conservative_tokens"], 65)
            self.assertFalse(usage["usage_complete"])
            self.assertEqual(usage["reported_cost"]["amount"], "0.125")

    async def test_observed_overrun_is_retained_and_failure_isolated(self):
        async def dishonest(request):
            return ToolResult(usage=TokenUsage(20, 5))

        async def bad(context):
            try:
                await context.call("dishonest", token_upper_bound=10)
            except JobFault:
                pass
            return "caught the breach"

        async def healthy(context):
            return "healthy"

        async with Scheduler(SchedulerConfig(1, 1, 8), adapters={"dishonest": dishonest}) as scheduler:
            scheduler.submit(JobSpec("breach", "a", max_tokens=10), bad)
            scheduler.submit(JobSpec("healthy", "b"), healthy)
            outcomes = await asyncio.wait_for(scheduler.wait_all(), 2)
            self.assertEqual([item.state for item in outcomes], [State.FAILED, State.SUCCEEDED])
            self.assertEqual(outcomes[0].reason, "usage_exceeds_reservation")
            usage = scheduler.report()["jobs"][0]["usage"]
            self.assertEqual(usage["observed_known_tokens"], 25)
            self.assertEqual(usage["observed_token_overrun"], 15)
            self.assertEqual(usage["remaining_conservative_tokens"], -15)
            self.assertEqual(usage["reservation_breaches"], 1)
            self.assertEqual(usage["unknown_usage_calls"], 0)

    async def test_adapter_exception_message_is_not_logged_and_no_success_is_fabricated(self):
        async def adapter(request):
            raise RuntimeError("fictional-private-payload-marker")

        async def agent(context):
            await context.call("throws", token_upper_bound=20)

        async with Scheduler(adapters={"throws": adapter}) as scheduler:
            scheduler.submit(JobSpec("error", "t"), agent)
            outcome = await asyncio.wait_for(scheduler.wait("error"), 2)
            self.assertEqual(outcome.reason, "adapter_error")
            usage = scheduler.report()["jobs"][0]["usage"]
            self.assertEqual(usage["unresolved_reserved_tokens"], 20)
            self.assertFalse(usage["reported_cost_complete"])
            self.assertNotIn("fictional-private-payload-marker", json.dumps(scheduler.events()))
