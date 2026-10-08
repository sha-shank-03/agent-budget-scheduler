"""Run and verify all public offline CLI fixtures, then save a receipt (stdlib only)."""

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    # states, rejected, calls, known tokens, unknown calls, unresolved, breaches, overrun
    "basic": ({"SUCCEEDED": 2}, 0, 4, 65, 0, 0, 0, 0),
    "fairness": ({"SUCCEEDED": 5}, 0, 5, 0, 0, 0, 0, 0),
    "aging": ({"SUCCEEDED": 3}, 0, 3, 0, 0, 0, 0, 0),
    "overload": ({"SUCCEEDED": 2}, 1, 2, 0, 0, 0, 0, 0),
    "budgets": ({"BUDGET_EXHAUSTED": 2, "SUCCEEDED": 1}, 0, 3, 40, 0, 0, 0, 0),
    "lifecycle": ({"CANCELLED": 2, "DEADLINE_EXCEEDED": 2, "SUCCEEDED": 1}, 0, 3, 0, 2, 120, 0, 0),
    "faults": ({"FAILED": 3, "SUCCEEDED": 1}, 0, 4, 25, 2, 50, 1, 15),
}
USAGE_KEYS = ("started_tool_calls", "observed_known_tokens", "unknown_usage_calls",
              "unresolved_reserved_tokens", "reservation_breaches", "observed_token_overrun")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def verify(name, report, events):
    states, rejected, *totals = EXPECTED[name]
    summary, config = report["summary"], report["config"]
    usage = summary["usage"]
    require(report["schema_version"] == "1.0" and report["execution_mode"] == "offline_mock", f"{name}: output contract")
    require(summary["states"] == states and summary["rejected"] == rejected, f"{name}: outcomes")
    require(summary["accepted"] == sum(states.values()) == len(report["jobs"]), f"{name}: accepted count")
    require([usage[key] for key in USAGE_KEYS] == totals, f"{name}: usage totals")
    require(usage["active_reserved_tokens"] == 0, f"{name}: outstanding reservations")
    require(summary["peak_running"] <= config["max_running"], f"{name}: global capacity")
    require(all(v <= config["max_running_per_tenant"] for v in summary["peak_running_by_tenant"].values()), f"{name}: tenant capacity")
    require([e["sequence"] for e in events] == list(range(1, len(events) + 1)), f"{name}: event sequence")
    jobs = {job["job_id"]: job for job in report["jobs"]}
    terminals = Counter()
    for event in events:
        require(event["schema_version"] == "1.0", f"{name}: event schema")
        job_id = event.get("job_id")
        require(not terminals[job_id], f"{name}: decision after terminal")
        if event["event_type"] == "terminal":
            terminals[job_id] += 1
        require(not ({"arguments", "value", "exception", "prompt"} & event.keys()), f"{name}: payload in decisions")
    require({job_id: count for job_id, count in terminals.items() if count} ==
            {job_id: 1 for job_id in jobs}, f"{name}: terminal publication")
    require(sum(e["event_type"] == "operation_started" for e in events) == totals[0], f"{name}: started events")
    for job in jobs.values():
        require(job["usage"]["active_reserved_tokens"] == 0, f"{name}: job reservation leak")
        require(job["state"] in states, f"{name}: nonterminal report")
    for receipt in report["rejections"]:
        require(not any(e.get("job_id") == receipt["job_id"] and e["event_type"] == "operation_started" for e in events), f"{name}: rejected tool invocation")
    dispatch = [e for e in events if e["event_type"] == "dispatched"]
    if name == "basic":
        require([j["estimates"]["tokens"] for j in report["jobs"]] == [100, 200], "basic: token estimates")
        require([j["usage"]["observed_known_tokens"] for j in report["jobs"]] == [40, 25], "basic: observed tokens")
        require([j["estimates"]["cost"]["amount"] for j in report["jobs"]] == ["0.50", "0.75"], "basic: cost estimates")
        require(Decimal(usage["reported_cost"]["amount"]) == Decimal("0.000065") and
                usage["reported_cost"]["sources"] == ["synthetic_mock"], "basic: synthetic cost")
    elif name == "fairness":
        require([e["tenant"] for e in dispatch] == ["alpha", "beta", "gamma", "alpha", "alpha"], "fairness: dispatch order")
    elif name == "aging":
        require([e["job_id"] for e in dispatch] == ["blocker", "old-low", "later-high"] and
                dispatch[1]["effective_priority"] == 9, "aging: priority promotion")
    elif name == "overload":
        require(report["rejections"] == [{"job_id": "rejected", "reason": "overload"}], "overload: rejection receipt")
    elif name == "budgets":
        require(jobs["calls-exhausted"]["reason"] == "tool_calls" and jobs["tokens-exhausted"]["reason"] == "tokens", "budgets: denial reasons")
    elif name == "lifecycle":
        for job_id in ("queued-cancel", "queued-deadline"):
            require(jobs[job_id]["usage"]["started_tool_calls"] == 0 and jobs[job_id]["runtime_ms"] is None,
                    "lifecycle: queued stop execution")
        require(not usage["usage_complete"] and usage["reported_cost"] is None, "lifecycle: incomplete usage")
    elif name == "faults":
        require({j: jobs[j]["reason"] for j in ("adapter-error", "missing-usage", "overrun")} ==
                {"adapter-error": "adapter_error", "missing-usage": "usage_unknown", "overrun": "usage_exceeds_reservation"}, "faults: stable reasons")
        require(jobs["overrun"]["usage"]["remaining_conservative_tokens"] == -15, "faults: retained overrun")
        require(usage["reported_cost"] is None and Decimal(usage["reported_cost_subtotals"][0]["amount"]) == Decimal("0.000025"), "faults: known subtotal")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "work" / "demo")
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    receipts = []
    for name in EXPECTED:
        fixture = ROOT / "examples" / f"{name}.json"
        before = fixture.read_bytes()
        directory = output / name
        command = [sys.executable, "-m", "agent_budget_scheduler", "run", str(fixture), "--out", str(directory)]
        process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10)
        require(process.returncode == 0, f"{name}: exit {process.returncode}: {process.stderr}")
        require(fixture.read_bytes() == before, f"{name}: fixture changed")
        report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        events = [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        verify(name, report, events)
        receipts.append({"scenario": name, "fixture_sha256": hashlib.sha256(before).hexdigest(), "exit_code": process.returncode,
                         "states": report["summary"]["states"], "rejected": report["summary"]["rejected"],
                         "usage": {key: report["summary"]["usage"][key] for key in USAGE_KEYS},
                         "events": len(events), "report": f"{name}/report.json", "decisions": f"{name}/events.jsonl"})
        print(f"PASS {name}: states={report['summary']['states']} calls={report['summary']['usage']['started_tool_calls']}")
    summary = {"schema_version": "1.0", "execution_mode": "offline_mock", "evidence_kind": "fresh_local_mock_execution",
               "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "python_version": platform.python_version(),
               "platform": platform.platform(), "checks": "literal outcomes, ledgers, capacity, event/terminal counts, scenario decisions, unchanged fixtures",
               "scenarios": receipts}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(receipts)} scenarios. Receipt: {output / 'summary.json'}")


if __name__ == "__main__":
    main()
