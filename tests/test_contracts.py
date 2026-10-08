import copy
import json
from pathlib import Path
import unittest

from agent_budget_scheduler import Estimates, JobSpec, ReportedCost, SchedulerConfig, TokenUsage
from agent_budget_scheduler.mock import parse_workload

ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_deadline_and_aging_contracts_have_explicit_integer_bounds(self):
        for deadline in (0, -1, True, 1.5, 86400001):
            with self.subTest(deadline=deadline), self.assertRaises(ValueError):
                JobSpec("test", "tenant", deadline_after_ms=deadline)
        for aging in (0, True, -1):
            with self.subTest(aging=aging), self.assertRaises(ValueError):
                SchedulerConfig(aging_interval_ms=aging)
        self.assertEqual(JobSpec("test", "tenant", deadline_after_ms=100).deadline_after_ms, 100)

    def test_invalid_counts_and_priority_are_rejected(self):
        for values in ({"max_tokens": True}, {"max_tool_calls": -1}, {"priority": 10}, {"priority": 1.5}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                JobSpec("test", "tenant", **values)
        with self.assertRaises(ValueError):
            SchedulerConfig(max_running=0)
        with self.assertRaises(ValueError):
            TokenUsage(output_tokens=-1)
        with self.assertRaises(ValueError):
            Estimates(duration_ms=float("inf"))

    def test_cost_contract_is_decimal_and_explicit(self):
        for amount in ("NaN", "Infinity", "-0.1", "1e-999", 0.1):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                ReportedCost(amount)
        self.assertEqual(ReportedCost("0.50", source="submitted_estimate").to_dict(),
                         {"amount": "0.50", "currency": "USD", "source": "submitted_estimate"})

    def test_manifest_rejects_unsupported_and_duplicate_jobs(self):
        document = json.loads((ROOT / "examples/basic.json").read_text(encoding="utf-8"))
        invalid = copy.deepcopy(document)
        invalid["schema_version"] = "2.0"
        with self.assertRaisesRegex(ValueError, "schema_version"):
            parse_workload(invalid)
        invalid = copy.deepcopy(document)
        invalid["jobs"][1]["job_id"] = invalid["jobs"][0]["job_id"]
        with self.assertRaisesRegex(ValueError, "duplicate job_id"):
            parse_workload(invalid)
        invalid = copy.deepcopy(document)
        invalid["jobs"][0]["unsupported_flag"] = 100
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            parse_workload(invalid)

    def test_mock_usage_must_fit_declared_bound_before_execution(self):
        document = json.loads((ROOT / "examples/basic.json").read_text(encoding="utf-8"))
        document["jobs"][0]["operations"][1]["token_upper_bound"] = 39
        with self.assertRaisesRegex(ValueError, "declared reservation"):
            parse_workload(document)
