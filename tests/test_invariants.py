"""Bounded seeded core sweeps; async cleanup races have separate controlled tests."""

from collections import Counter
import random
import unittest

from agent_budget_scheduler import JobSpec, SchedulerConfig
from agent_budget_scheduler.budget import BudgetLedger
from agent_budget_scheduler.models import BudgetExceeded, State, TokenUsage
from agent_budget_scheduler.policy import DispatchPolicy


class CoreInvariantTests(unittest.TestCase):
    def test_seeded_transitions_preserve_capacity_reservations_and_terminals(self):
        coverage = Counter()
        for seed in range(8):
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                clock = [0.0]
                config = SchedulerConfig(3, 2, 5, 10)
                policy = DispatchPolicy(config, lambda: clock[0])
                queued, running, terminals = set(), set(), {}
                stops, ledgers, accounts = {}, {}, {}

                def snapshot(record):
                    return (record.state, record.reason, record.started_at,
                            record.finished_at, record.stop_state, record.stop_reason,
                            record.dispatched_priority)

                def check():
                    self.assertEqual(policy.pending, len(queued))
                    self.assertEqual(policy.running, len(running))
                    self.assertEqual({k for k, r in policy.records.items() if r.state is State.QUEUED}, queued)
                    self.assertEqual({k for k, r in policy.records.items()
                                      if r.state in (State.RUNNING, State.STOPPING)}, running)
                    counts = Counter(policy.records[k].spec.tenant for k in running)
                    self.assertEqual({k: v for k, v in policy.running_by_tenant.items() if v}, dict(counts))
                    self.assertLessEqual(len(queued), config.max_pending)
                    self.assertLessEqual(len(running), config.max_running)
                    self.assertTrue(all(v <= config.max_running_per_tenant for v in counts.values()))
                    for job_id, saved in terminals.items():
                        self.assertEqual(snapshot(policy.records[job_id]), saved)
                        self.assertFalse(policy.request_stop(policy.records[job_id], State.CANCELLED, "late"))
                        self.assertEqual(snapshot(policy.records[job_id]), saved)
                    for job_id, ledger in ledgers.items():
                        account = accounts[job_id]
                        self.assertEqual(ledger.started_tool_calls, account["calls"])
                        self.assertEqual(ledger.active_reserved_tokens, sum(account["active"].values()))
                        self.assertEqual(ledger.observed_known_tokens, account["known"])
                        self.assertEqual(ledger.unresolved_reserved_tokens, account["unresolved"])
                        self.assertEqual(ledger.unknown_usage_calls, account["unknown"])
                        self.assertEqual(ledger.remaining_tokens,
                                         40 - account["known"] - account["unresolved"] - sum(account["active"].values()))
                        self.assertGreaterEqual(ledger.remaining_tokens, 0)
                        self.assertLessEqual(ledger.started_tool_calls, 4)
                        if job_id in terminals:
                            self.assertEqual(ledger.active_reserved_tokens, 0)

                def reconcile(job_id, operation_id, unknown):
                    ledger, account = ledgers[job_id], accounts[job_id]
                    bound = account["active"].pop(operation_id)
                    if unknown:
                        ledger.unknown(operation_id)
                        account["unresolved"] += bound
                        account["unknown"] += 1
                        coverage["unknown"] += 1
                    else:
                        used = rng.randint(0, bound)
                        incoming = rng.randint(0, used)
                        ledger.observe(operation_id, TokenUsage(incoming, used - incoming), None)
                        account["known"] += used
                        coverage["observe"] += 1

                def finish(job_id):
                    # Cleanup resolves every active reservation before releasing a slot.
                    for operation_id in list(accounts[job_id]["active"]):
                        reconcile(job_id, operation_id, True)
                    record = policy.records[job_id]
                    expected = stops.get(job_id, (State.SUCCEEDED, None))
                    policy.finish(record, State.SUCCEEDED, None)
                    self.assertEqual((record.state, record.reason), expected)
                    running.remove(job_id)
                    terminals[job_id] = snapshot(record)
                    with self.assertRaises(RuntimeError):
                        policy.finish(record, State.SUCCEEDED, None)
                    coverage["finish"] += 1

                for step in range(160):
                    clock[0] += rng.randint(0, 20) / 1000
                    action = rng.choice(("submit", "submit", "dispatch", "stop", "finish", "operation"))
                    if action == "submit":
                        job_id = f"s{seed}-{step}"
                        spec = JobSpec(job_id, f"tenant-{rng.randrange(3)}", rng.randrange(10), 4, 40)
                        expected = len(queued) < config.max_pending
                        receipt = policy.submit(spec)
                        self.assertEqual(receipt.accepted, expected)
                        if expected:
                            queued.add(job_id)
                            ledgers[job_id] = BudgetLedger(4, 40)
                            accounts[job_id] = {"calls": 0, "active": {}, "known": 0, "unresolved": 0, "unknown": 0}
                        else:
                            self.assertNotIn(job_id, policy.records)
                            coverage["rejection"] += 1
                    elif action == "dispatch":
                        eligible = [k for k in queued if sum(policy.records[r].spec.tenant == policy.records[k].spec.tenant
                                                            for r in running) < config.max_running_per_tenant]
                        expected = len(running) < config.max_running and bool(eligible)
                        record = policy.dispatch()
                        self.assertEqual(record is not None, expected)
                        if record is not None:
                            job_id = record.spec.job_id
                            self.assertIn(job_id, queued)
                            self.assertNotIn(job_id, terminals)
                            queued.remove(job_id)
                            running.add(job_id)
                            coverage["dispatch"] += 1
                    elif action == "stop" and queued | running:
                        job_id = rng.choice(sorted(queued | running))
                        state = rng.choice((State.CANCELLED, State.DEADLINE_EXCEEDED, State.FAILED))
                        expected = job_id not in stops
                        self.assertEqual(policy.request_stop(policy.records[job_id], state, "seeded_stop"), expected)
                        if expected:
                            stops[job_id] = (state, "seeded_stop")
                            if job_id in queued:
                                queued.remove(job_id)
                                terminals[job_id] = snapshot(policy.records[job_id])
                            coverage["stop"] += 1
                    elif action == "finish" and running:
                        finish(rng.choice(sorted(running)))
                    elif action == "operation" and running:
                        job_id = rng.choice(sorted(running))
                        account, ledger = accounts[job_id], ledgers[job_id]
                        if account["active"] and rng.choice((False, True)):
                            reconcile(job_id, rng.choice(sorted(account["active"])), rng.choice((False, True)))
                        elif job_id not in stops:
                            bound = rng.randint(0, 45)
                            expected_reason = ("tool_calls" if account["calls"] >= 4 else "tokens"
                                               if bound > 40 - account["known"] - account["unresolved"]
                                               - sum(account["active"].values()) else None)
                            if expected_reason:
                                with self.assertRaises(BudgetExceeded) as caught:
                                    ledger.reserve(bound)
                                self.assertEqual(caught.exception.reason, expected_reason)
                                policy.request_stop(policy.records[job_id], State.BUDGET_EXHAUSTED, expected_reason)
                                stops[job_id] = (State.BUDGET_EXHAUSTED, expected_reason)
                                coverage["denial"] += 1
                            else:
                                operation_id = ledger.reserve(bound)
                                account["calls"] += 1
                                self.assertEqual(operation_id, account["calls"])
                                account["active"][operation_id] = bound
                                coverage["reserve"] += 1
                    check()

                for job_id in sorted(queued):
                    policy.request_stop(policy.records[job_id], State.CANCELLED, "drain")
                    terminals[job_id] = snapshot(policy.records[job_id])
                queued.clear()
                for job_id in sorted(running):
                    finish(job_id)
                check()
                self.assertIsNone(policy.dispatch())
        self.assertTrue(all(coverage[key] > 0 for key in
                            ("rejection", "dispatch", "stop", "finish", "reserve", "denial", "observe", "unknown")), coverage)
