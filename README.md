# agent-budget-scheduler

[![CI](https://github.com/sha-shank-03/agent-budget-scheduler/actions/workflows/ci.yml/badge.svg)](https://github.com/sha-shank-03/agent-budget-scheduler/actions/workflows/ci.yml)

Open-source MIT project. [Project context](docs/PROJECT_CONTEXT.md) · [Independent local verification](docs/INDEPENDENT_VERIFICATION.md) · [Contributing](CONTRIBUTING.md)

Run cooperative async agent jobs with bounded concurrency, tenant dispatch fairness, and per-job tool/token reservations. Inspect why work was admitted, dispatched, or refused, and compare submitted estimates with observed usage.

This local MVP implements [PLAN.md](PLAN.md): a Python API and offline mock CLI, tenant round robin with priority aging, bounded pending admission, running-job limits, submission-relative deadlines, cooperative cancellation, and guarded usage accounting with failure demonstrations. Design documentation, saved seven-fixture evidence, and a pinned offline CI workflow are included. Hosted CI remains unexecuted. Unknown fields are rejected rather than silently ignored.

## Quickstart

Use CPython **3.11.9**, the reference runtime used for local evidence. On this Windows workspace `py -3.11` selects that interpreter; verify the version on your machine. No pip install, credentials, server, model download, or network access is needed to execute the examples/tests after obtaining the source and interpreter. From the clone root on Windows PowerShell:

```powershell
py -3.11 --version
py -3.11 -m agent_budget_scheduler run examples/basic.json --out work/basic
py -3.11 -m examples.embedded_agent
py -3.11 -m unittest discover -s tests -v
py -3.11 scripts/check_examples.py --out work/demo
```

From the clone root on POSIX with Python 3.11.9 installed:

```sh
python3.11 --version
python3.11 -m agent_budget_scheduler run examples/basic.json --out work/basic
python3.11 -m examples.embedded_agent
python3.11 -m unittest discover -s tests -v
python3.11 scripts/check_examples.py --out work/demo
```

Other platforms/runtimes have not yet been executed locally. Packaging is deferred; run directly from the clone. The seven-scenario checker invokes the CLI, verifies exact outcomes/ledgers and fixture preservation, and saves `work/demo/summary.json`. Checked-in [sample reports and decision events](examples/sample-output/README.md) show a completed fresh local mock run.

The basic CLI prints:

```text
mode=offline_mock accepted=2 rejected=0 succeeded=2 started_tool_calls=4 observed_known_tokens=65 unknown_usage_calls=0
Report: work\basic\report.json
Events: work\basic\events.jsonl
```

Path separators depend on the platform. The two jobs use fictional records and synthetic token counts of 40 and 25. This is fresh local scheduler execution with mock tools, **not live model execution or recorded replay**. Durations vary; the states and totals are reproducible. The model response explicitly begins with `[MOCK]`.

`report.json` includes the execution mode, configured limits, job outcomes, per-job estimates and usage, observed capacity peaks, and rejection receipts. `events.jsonl` contains ordered admission/dispatch/operation/terminal decisions. Events never include tool arguments, returned content, or arbitrary exception messages. The demo reports a fictional mock cost of `0.000065 USD` with `source: synthetic_mock`; this is not a provider price or invoice. Its submitted cost estimates (`0.50` and `0.75`) and token estimates (100 and 200) remain distinct from observations.

Run a scenario by replacing `basic.json` in the quickstart command and choosing its own output directory:

| Fixture | Reproducible outcome |
| --- | --- |
| `fairness.json` | Dispatch tenants `alpha, beta, gamma, alpha, alpha`. |
| `aging.json` | The priority-0 job ages to 9 and dispatches before a later priority-9 job after the blocker finishes. |
| `overload.json` | Two accepted jobs succeed; the third pending submission is rejected without a tool call. |
| `budgets.json` | One call-budget exhaustion, one token-reservation exhaustion, and a healthy job. |
| `lifecycle.json` | Two CANCELLED jobs, two DEADLINE_EXCEEDED jobs, one success; queued stops start no tools, interrupted calls retain 120 unresolved reserved tokens. |
| `faults.json` | Three failures and one success: adapter error, missing telemetry, and an intentional 25-token observation against a 10-token budget, retaining the 15-token overrun. |

For example:

```powershell
py -3.11 -m agent_budget_scheduler run examples/lifecycle.json --out work/lifecycle
py -3.11 -m agent_budget_scheduler run examples/faults.json --out work/faults
```

The `fault.*` connectors deliberately break contracts using local synthetic data. They are labeled mock faults, not live provider tests. The lifecycle demo uses short real mock delays; semantic tests use controlled events and an injected clock instead of asserting exact elapsed time.

## Embed an agent callback

```python
import asyncio
from agent_budget_scheduler import JobSpec, Scheduler, SchedulerConfig
from agent_budget_scheduler.mock import MOCK_ADAPTERS

async def agent(context):
    await context.call("lookup.record", {"record": "release-a"})
    response = await context.call(
        "model.generate", {"input_tokens": 30, "output_tokens": 10},
        token_upper_bound=60,
    )
    return response.value

async def main():
    async with Scheduler(SchedulerConfig(2, 1, 8), adapters=MOCK_ADAPTERS,
                         execution_mode="offline_mock") as scheduler:
        receipt = scheduler.submit(
            JobSpec("example", "engineering", priority=5,
                    max_tool_calls=2, max_tokens=60), agent,
        )
        if receipt.accepted:
            outcome = await scheduler.wait(receipt.job_id)
            print(outcome.state.value, outcome.value)
        else:
            print("rejected", receipt.reason)

asyncio.run(main())
```

The context manager closes submissions and drains accepted jobs on normal exit. If its body raises, it requests cancellation for unfinished jobs and waits for their cooperative cleanup. `wait()` returns an outcome rather than raising a job's adapter error. Cancelling or timing out a waiter does not cancel its job. Waiting on a rejected ID is an error. A caller may await all accepted jobs with `wait_all()`. The callback's returned value is available in the API outcome and is excluded from decision reports.

Pass `deadline_after_ms` to JobSpec to bound the allowed submission-to-completion interval (positive integer, at most one day). Call `scheduler.cancel(job_id)` to request cancellation; it returns whether a new stop reason was latched. A due deadline is checked first. Repeated requests do not send repeated cancellation into cleanup or change the first outcome. After an earlier fault, a cancellation request may still interrupt the callback while preserving that fault's first reason. `wait_event(event_type, job_id)` observes the first matching decision event; it does not alter job execution. Injected-clock tests explicitly call `poll()` after advancing time; normal execution arms a timer for the next deadline.

Register a custom async adapter as a mapping from tool name to callable. It receives `ToolRequest(arguments, token_upper_bound)` and returns `ToolResult(value, TokenUsage(input_tokens, output_tokens), optional ReportedCost)`. Every dispatched operation, including `model.generate`, consumes one `max_tool_calls` slot. The declared token bound covers total input plus output usage. Custom adapters must honor and explain their bounds; the scheduler cannot infer provider behavior from a number supplied by a caller.

## Scheduling and budget contracts

- `max_pending` counts queued jobs, excluding running jobs. Submission is synchronous on the owning event loop. A full pending queue returns `accepted=False, reason="overload"`; dispatch runs on a subsequent loop turn. No accepted job is evicted to make room for higher priority.
- Global and per-tenant limits count running callbacks and their owned operation cleanup. Work is nonpreemptive. Choose an eligible tenant by round robin, then its highest effective priority: `min(9, base_priority + floor(queued_wait_ms / aging_interval_ms))`. Break ties by enqueue order. The default aging interval is 1,000 ms; a priority-0 job reaches 9 after nine intervals and wins ties against later arrivals. The dispatch event records the priority used at that decision.
- Deadlines include queue wait and are checked before dispatch, before a guarded call, and at completion. At `now >= deadline`, queued jobs terminate without invoking their callback. Running cancellation/deadline stops enter STOPPING, reject subsequent calls, and retain their slot until callback/adapter cleanup actually finishes. A late result cannot become success. The first processed stop reason is immutable; later usage observations, including breaches, remain recorded independently.
- Reservations and call-count updates happen before any `await`. An operation starts only if its declared token bound fits the remaining allowance after known observations, active reservations, and unresolved reservations. Two concurrent calls cannot both reserve the same remaining allowance.
- Successful usage reconciles the reservation and releases unused capacity. Denied calls never invoke an adapter or increment started usage. A budget denial remains a job failure even if the agent catches the exception. Reported usage above a declared bound is retained in full and flags a breach; it fails an otherwise running job and cannot overwrite an earlier stop reason. The remaining allowance can be negative when a dishonest adapter reports an overrun; measurements are never clamped to fit limits.
- A started operation without trustworthy usage leaves an unknown measurement and a conservative unresolved reservation. Missing usage/cost is not zero. Known reported costs are subtotaled by currency; an incomplete cost total is null. Cost accounting never substitutes a token-price calculation for adapter-reported data.
- All relevant operations must go through the context and be awaited. If a callback exits with owned adapter work still pending, the scheduler fails that job and drains its operation cleanup before releasing its running slot.

The CLI validates the entire manifest before submitting any job. See [examples/basic.json](examples/basic.json) for schema `1.0`: root fields are `schema_version`, `execution_mode`, `config`, and `jobs`. Config supports the three capacity limits and optional positive `aging_interval_ms`. Jobs support IDs, tenant, priority, call/token limits, estimates, operations, and optional `deadline_after_ms`. The mock harness additionally supports `cancel_after_ms` (0–10,000): zero cancels before dispatch, while a positive value schedules a cancellation request after the submission batch. This is a demo control, not a scheduler deadline. An operation names a safe mock or an explicit `fault.*` tool, its total-token upper bound, and validated arguments. Counts are nonnegative integers (booleans are rejected), capacities are positive integers, and priorities are 0–9. Unknown fields/schema versions and duplicate IDs/JSON keys are rejected. Inputs are bounded to 1 MiB, 1,000 jobs, 100 operations per job, and 10,000 operations overall. Mock `delay_ms` and `cleanup_delay_ms` are each at most 1,000 ms per operation.

CLI exit codes: **0** means a valid workload was fully processed, including any job failures/rejections; inspect the report outcomes. **2** means invalid/unreadable input. **1** means runner/output failure. Output files use schema `1.0` and an existing destination's `report.json`/`events.jsonl` are replaced; choose a distinct `--out` directory to preserve a prior run.

## Architecture and limits

`DispatchPolicy` is a synchronous capacity/queue core with an injected monotonic clock. `Scheduler` owns async callbacks and decision events on one event loop. `JobContext` owns adapter tasks through ledger reconciliation. `BudgetLedger` separately tracks observations, active reservations, unknown reservations, and explicitly sourced costs. The CLI prevalidates and runs scripted callbacks against the same API used by the embedding example. All code and tests use only Python's standard library.

This is cooperative execution of trusted callbacks, not an execution sandbox. Blocking or cancellation-suppressing code can hold a slot and delay shutdown. Fairness means dispatch opportunities across a fixed set of eligible tenants, not equal CPU time, latency, token consumption, or deadline satisfaction. Calls outside the gateway and provider-internal side effects are outside its accounting. There is no hard monetary cap, unconditional arbitrary-provider token cap, external-side-effect rollback, persistence/restart recovery, automatic retry, exactly-once guarantee, or live provider integration. Reports/event history are held in memory for bounded runs; the API is not yet an unbounded daemon.

The contribution is an inspectable combination of admission, dispatch, guarded budgets, and demonstrations. Round robin, priorities, and reservations are established techniques; no novel algorithm or comparative performance benefit is claimed. Existing APScheduler, Celery, and LiteLLM functionality overlaps. Read the [architecture](docs/ARCHITECTURE.md), [exact contracts](docs/CONTRACTS.md), [contribution and limitations](docs/LIMITATIONS.md), and [primary-source research/pins](docs/RESEARCH.md).

## Verification and license

[EVIDENCE.md](EVIDENCE.md) records commands actually run, their observed results, an initial test-harness failure and its correction, and checks that remain unexecuted. Tests measure callback capacity and cleanup with controlled events, contend for held reservations, test aging/deadlines with a fake clock, assert public CLI outcomes and literal totals, and run eight bounded seeded core sweeps.

[Prepared GitHub Actions CI](.github/workflows/ci.yml) selects Python 3.11.9 on ubuntu-24.04/windows-2022 and runs stdlib tests, the seven-scenario checker, and embedding. Both actions use verified immutable commits, token permissions are read-only, checkout does not persist credentials, and no secrets or paid/provider calls are used. Hosted execution is unexecuted; there is no CI-passed badge or claim.

Original code and synthetic fixtures are [MIT licensed](LICENSE). [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) identifies the runtime and source references. No third-party runtime/test package is installed or vendored.

## Get the source

```sh
git clone https://github.com/sha-shank-03/agent-budget-scheduler.git
cd agent-budget-scheduler
```

Follow the quickstart above for runtime/dependency setup. Demos use fictional/mock data; initial dependency setup, where required, is separate from offline execution.
