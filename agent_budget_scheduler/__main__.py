"""Fresh local mock execution. Exit 0 means processed, not every job succeeded."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

from .mock import MOCK_ADAPTERS, parse_workload, scripted_agent
from .scheduler import Scheduler

MAX_MANIFEST_BYTES = 1024 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def read_workload(path: Path):
    # Read one extra byte to enforce the bound even if the file grows after a stat.
    with path.open("rb") as file:
        data = file.read(MAX_MANIFEST_BYTES + 1)
    if len(data) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest exceeds 1 MiB")
    document = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
    return parse_workload(document)


async def execute(config, jobs):
    async with Scheduler(config, adapters=MOCK_ADAPTERS, execution_mode="offline_mock") as scheduler:
        accepted = set()
        for job in jobs:
            if scheduler.submit(job.spec, scripted_agent(job)).accepted:
                accepted.add(job.spec.job_id)
        controls = []
        for job in jobs:
            if job.spec.job_id in accepted and job.cancel_after_ms is not None:
                if job.cancel_after_ms == 0:
                    scheduler.cancel(job.spec.job_id)
                else:
                    controls.append(asyncio.get_running_loop().call_later(
                        job.cancel_after_ms / 1000, scheduler.cancel, job.spec.job_id
                    ))
        try:
            await scheduler.wait_all()
        finally:
            for control in controls:
                control.cancel()
        return scheduler.report(), scheduler.events()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run constrained agent jobs with synthetic offline tools.")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="execute a schema-1.0 offline mock workload")
    run.add_argument("workload", type=Path)
    run.add_argument("--out", type=Path, required=True, help="directory for report.json and events.jsonl")
    args = parser.parse_args(argv)
    try:
        config, jobs = read_workload(args.workload)
    except (OSError, UnicodeError, RecursionError):
        print("Invalid workload: input must be readable UTF-8 JSON within the size/depth limits.", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Invalid workload: {exc}", file=sys.stderr)
        return 2
    try:
        report, events = asyncio.run(execute(config, jobs))
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        (args.out / "events.jsonl").write_text(
            "".join(json.dumps(event, allow_nan=False) + "\n" for event in events), encoding="utf-8"
        )
    except (Exception, KeyboardInterrupt):
        print("Runner/output failure; no complete report is guaranteed.", file=sys.stderr)
        return 1
    summary = report["summary"]
    usage = summary["usage"]
    print(f"mode={report['execution_mode']} accepted={summary['accepted']} rejected={summary['rejected']} "
          f"succeeded={summary['states'].get('SUCCEEDED', 0)} "
          f"started_tool_calls={usage['started_tool_calls']} observed_known_tokens={usage['observed_known_tokens']} "
          f"unknown_usage_calls={usage['unknown_usage_calls']}")
    print(f"Report: {args.out / 'report.json'}")
    print(f"Events: {args.out / 'events.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
