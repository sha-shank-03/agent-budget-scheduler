import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_public_m2_scenarios_have_reproducible_outcomes_and_truthful_ledgers(self):
        expected_states = {
            "fairness": {"SUCCEEDED": 5}, "aging": {"SUCCEEDED": 3},
            "overload": {"SUCCEEDED": 2},
            "budgets": {"BUDGET_EXHAUSTED": 2, "SUCCEEDED": 1},
            "lifecycle": {"CANCELLED": 2, "DEADLINE_EXCEEDED": 2, "SUCCEEDED": 1},
            "faults": {"FAILED": 3, "SUCCEEDED": 1},
        }
        for scenario, states in expected_states.items():
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory(dir=ROOT / "work") as temporary:
                process = subprocess.run(
                    [sys.executable, "-m", "agent_budget_scheduler", "run", f"examples/{scenario}.json",
                     "--out", temporary], cwd=ROOT, capture_output=True, text=True, timeout=5,
                )
                self.assertEqual(process.returncode, 0, process.stderr)
                report = json.loads((Path(temporary) / "report.json").read_text(encoding="utf-8"))
                events = [json.loads(line) for line in (Path(temporary) / "events.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(report["execution_mode"], "offline_mock")
                self.assertEqual(report["summary"]["states"], states)
                self.assertEqual(report["summary"]["usage"]["active_reserved_tokens"], 0)
                self.assertLessEqual(report["summary"]["peak_running"], report["config"]["max_running"])
                self.assertTrue(all(v <= report["config"]["max_running_per_tenant"]
                                    for v in report["summary"]["peak_running_by_tenant"].values()))
                dispatch = [e for e in events if e["event_type"] == "dispatched"]
                usage = report["summary"]["usage"]
                jobs = {job["job_id"]: job for job in report["jobs"]}
                if scenario == "fairness":
                    self.assertEqual([e["tenant"] for e in dispatch], ["alpha", "beta", "gamma", "alpha", "alpha"])
                elif scenario == "aging":
                    self.assertEqual([e["job_id"] for e in dispatch], ["blocker", "old-low", "later-high"])
                    self.assertEqual(dispatch[1]["effective_priority"], 9)
                elif scenario == "overload":
                    self.assertEqual(report["rejections"], [{"job_id": "rejected", "reason": "overload"}])
                    self.assertFalse(any(e.get("job_id") == "rejected" and e["event_type"] == "operation_started" for e in events))
                elif scenario == "budgets":
                    self.assertEqual(jobs["calls-exhausted"]["reason"], "tool_calls")
                    self.assertEqual(jobs["tokens-exhausted"]["reason"], "tokens")
                    self.assertEqual((usage["started_tool_calls"], usage["observed_known_tokens"]), (3, 40))
                elif scenario == "lifecycle":
                    self.assertEqual(usage["unresolved_reserved_tokens"], 120)
                    self.assertEqual(usage["unknown_usage_calls"], 2)
                    for job_id in ("queued-cancel", "queued-deadline"):
                        self.assertEqual(jobs[job_id]["usage"]["started_tool_calls"], 0)
                        self.assertIsNone(jobs[job_id]["runtime_ms"])
                    self.assertFalse(usage["usage_complete"])
                    self.assertIsNone(usage["reported_cost"])
                elif scenario == "faults":
                    self.assertEqual(usage["observed_known_tokens"], 25)
                    self.assertEqual(usage["observed_token_overrun"], 15)
                    self.assertEqual(usage["reservation_breaches"], 1)
                    self.assertEqual(usage["unknown_usage_calls"], 2)
                    self.assertEqual(usage["unresolved_reserved_tokens"], 50)
                    self.assertEqual(jobs["overrun"]["usage"]["remaining_conservative_tokens"], -15)
                    self.assertIsNone(usage["reported_cost"])

    def test_public_cli_writes_literal_basic_results_and_safe_events(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "work") as temporary:
            process = subprocess.run(
                [sys.executable, "-m", "agent_budget_scheduler", "run", "examples/basic.json", "--out", temporary],
                cwd=ROOT, capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn("mode=offline_mock accepted=2 rejected=0 succeeded=2", process.stdout)
            report = json.loads((Path(temporary) / "report.json").read_text(encoding="utf-8"))
            events_text = (Path(temporary) / "events.jsonl").read_text(encoding="utf-8")
            events = [json.loads(line) for line in events_text.splitlines()]
            self.assertEqual(report["schema_version"], "1.0")
            self.assertEqual(report["execution_mode"], "offline_mock")
            self.assertEqual(report["summary"]["states"], {"SUCCEEDED": 2})
            self.assertEqual(report["summary"]["usage"]["observed_known_tokens"], 65)
            self.assertEqual(report["summary"]["usage"]["started_tool_calls"], 4)
            self.assertEqual(report["summary"]["usage"]["unknown_usage_calls"], 0)
            self.assertEqual(sum(e["event_type"] == "operation_started" for e in events), 4)
            self.assertEqual(sum(e["event_type"] == "terminal" for e in events), 2)
            self.assertEqual([e["sequence"] for e in events], list(range(1, len(events) + 1)))
            self.assertNotIn("Synthetic release A", events_text)
            self.assertNotIn("deterministic synthetic summary", events_text)

    def test_invalid_workload_starts_no_output_or_tools(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "work") as temporary:
            path = Path(temporary)
            (path / "invalid.json").write_text('{"schema_version": "2.0"}', encoding="utf-8")
            process = subprocess.run(
                [sys.executable, "-m", "agent_budget_scheduler", "run", str(path / "invalid.json"),
                 "--out", str(path / "output")], cwd=ROOT, capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(process.returncode, 2)
            self.assertIn("Invalid workload", process.stderr)
            self.assertFalse((path / "output").exists())

    @classmethod
    def setUpClass(cls):
        (ROOT / "work").mkdir(exist_ok=True)
