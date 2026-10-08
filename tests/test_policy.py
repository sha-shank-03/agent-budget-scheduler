import unittest

from agent_budget_scheduler import JobSpec, SchedulerConfig
from agent_budget_scheduler.models import State
from agent_budget_scheduler.policy import DispatchPolicy


class PolicyTests(unittest.TestCase):
    def test_aging_threshold_defeats_a_later_priority_nine(self):
        for now, expected in ((0.089, "later-high"), (0.090, "old-low")):
            with self.subTest(now=now):
                clock = [0.0]
                policy = DispatchPolicy(SchedulerConfig(1, 1, 8, 10), lambda: clock[0])
                policy.submit(JobSpec("old-low", "same", 0))
                clock[0] = 0.080
                policy.submit(JobSpec("later-high", "same", 9))
                clock[0] = now
                self.assertEqual(policy.dispatch().spec.job_id, expected)

    def test_tenants_get_rotating_dispatch_opportunities(self):
        policy = DispatchPolicy(SchedulerConfig(1, 1, 8), lambda: 10.0)
        for job_id, tenant, priority in (
            ("a1", "alpha", 9), ("a2", "alpha", 9), ("a3", "alpha", 9),
            ("b1", "beta", 0), ("g1", "gamma", 0),
        ):
            self.assertTrue(policy.submit(JobSpec(job_id, tenant, priority)).accepted)
        tenants = []
        while (job := policy.dispatch()) is not None:
            tenants.append(job.spec.tenant)
            self.assertIsNone(policy.dispatch())  # A held slot cannot be dispatched again.
            policy.finish(job, State.SUCCEEDED, None)
        self.assertEqual(tenants, ["alpha", "beta", "gamma", "alpha", "alpha"])
        self.assertEqual((policy.running, policy.pending), (0, 0))

    def test_priority_then_fifo_within_tenant(self):
        policy = DispatchPolicy(SchedulerConfig(1, 1, 8), lambda: 20.0)
        for job_id, priority in (("low", 0), ("first-high", 9), ("second-high", 9)):
            policy.submit(JobSpec(job_id, "same", priority))
        order = []
        for _ in range(3):
            job = policy.dispatch()
            order.append(job.spec.job_id)
            policy.finish(job, State.SUCCEEDED, None)
        self.assertEqual(order, ["first-high", "second-high", "low"])

    def test_bounded_pending_admission_and_duplicate_ids(self):
        policy = DispatchPolicy(SchedulerConfig(1, 1, 2), lambda: 0.0)
        policy.submit(JobSpec("first", "a"))
        policy.submit(JobSpec("second", "b"))
        receipt = policy.submit(JobSpec("rejected", "c"))
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.reason, "overload")
        self.assertNotIn("rejected", policy.records)
        self.assertEqual(policy.pending, 2)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            policy.submit(JobSpec("first", "a"))
