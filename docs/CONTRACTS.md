# Contracts (schema 1.0)

## Python API

The reference runtime is CPython 3.11.9; there are no runtime/test package dependencies. Construct `Scheduler(config, adapters=..., execution_mode=..., clock=...)` and enter it once with `async with`. The default execution label is `local_cooperative`; the CLI explicitly uses `offline_mock`. Labels do not certify adapter behavior.

| Type or method | Contract |
| --- | --- |
| `SchedulerConfig` | Positive integer `max_running=2`, `max_running_per_tenant=1`, `max_pending=64`, `aging_interval_ms=1000`. |
| `JobSpec` | Required unique `job_id` and `tenant`; `priority=0` in 0–9; nonnegative integer `max_tool_calls=10`, `max_tokens=1000`; optional `estimates`; optional `deadline_after_ms` integer 1–86,400,000. |
| `Estimates` | Optional nonnegative integer tokens and duration_ms, plus optional `ReportedCost`. Descriptive only; never used to reserve, bill, or rank work. |
| `submit(spec, async_callback)` | Synchronous `Admission(job_id, accepted, reason)`. Full pending queue rejects with `overload`; no callback starts. Duplicate IDs raise ValueError, including reuse of a rejected ID. |
| `context.call(tool, arguments=None, token_upper_bound=0)` | Await a registered async adapter. Each invocation reserves one call and the stated bound before scheduling the adapter. The callback must await all guarded calls. |
| Adapter | Async callable accepting `ToolRequest(arguments, token_upper_bound)` and returning `ToolResult(value, usage, cost)`. Honest total-token bounds and usage telemetry are the adapter's responsibility. |
| `TokenUsage` | Nonnegative integer input/output tokens; total is their sum. No tokenizer or provider billing inference. |
| `ReportedCost` | Finite nonnegative decimal string, length ≤64, ≤24 digits, absolute decimal exponent ≤12; three uppercase ASCII currency letters; source label. Decimal subtotals retain reported precision. |
| `wait(job_id)` | Shielded wait returning `JobOutcome(job_id, state, reason, value)`. Rejected/unknown IDs raise ValueError. Cancelling or timing out a waiter leaves its job running. Value is present only on success. |
| `wait_all()` | Wait for the current snapshot of accepted IDs; it is not a subscription to future submissions. |
| `cancel(job_id)` | Check a due deadline first, then request CANCELLED; returns whether that request latched a new reason. Terminal/repeated requests return false. Unknown/rejected IDs raise ValueError. |
| `poll()` | Reevaluate deadlines and schedule dispatch, particularly after an injected monotonic test clock advances. |
| `wait_event(type, job_id)` | Return a detached copy of the first historical matching event or wait for it; a terminal job without that event raises ValueError. This is an observer, not an execution barrier. |
| `report()` / `events()` | Detached decision data. Call report on the owning loop. Events contain no tool arguments, response value, or ordinary raw exception message. |

Counts reject booleans and non-integer values. IDs, tenants, tool names, execution labels, and cost sources use 1–128 ASCII alphanumeric characters or `.`, `_`, `:`, `-`. Syntactic label validation is not secret redaction. Trusted custom `JobFault.reason` is diagnostic text supplied by the embedding application and must not contain sensitive content. JobOutcome fields are frozen; an arbitrary callback value is not deeply frozen.

Normal context exit closes admission and drains accepted jobs. A body exception requests cancellation and drains cleanup before propagating. Blocking code or a callback/adapter that suppresses cancellation can delay exit indefinitely. Process termination and fatal BaseExceptions are outside the ordinary outcome guarantee.

## State, stop, and fairness rules

Accepted jobs enter QUEUED, then RUNNING. A running stop enters STOPPING until owned work drains. Queued cancellation/expiry becomes terminal immediately; it never calls the callback. Terminal states are SUCCEEDED, FAILED, BUDGET_EXHAUSTED, CANCELLED, DEADLINE_EXCEEDED. Terminal state/reason is published once and is not revised.

The first latched stop wins. A due deadline checked during `cancel()` therefore wins over a new cancellation; an earlier guarded fault remains the reason even if a later cancellation interrupts its callback. Budget denial and adapter faults latch a stop without forcibly cancelling other already-in-flight guarded calls. Catching those exceptions does not permit further guarded operations or success. A context becomes closed when its callback exits.

`max_pending` counts QUEUED jobs only. RUNNING and STOPPING occupy running slots, including cleanup. Tenant round robin chooses the next eligible tenant; priority aging and FIFO ties select within it. Aging uses time since submission, caps at 9, and does not override tenant caps. A fixed set of eligible tenants receives rotating dispatch opportunities when capacity becomes available. This is not a guarantee of equal runtime, throughput, tokens, completion latency, or deadlines.

## Reservations and usage

Before adapter dispatch, reserve one nonrefundable call slot and a nonnegative total-token upper bound. Refused calls do not increment started calls. The conservative remaining allowance is:

```text
max_tokens - observed_known_tokens - active_reserved_tokens - unresolved_reserved_tokens
```

On valid telemetry, release the active bound and add the full reported input/output tokens; unused reservation becomes available again. On absent/invalid telemetry, cancellation, or adapter error, move the full active bound to unresolved and increment unknown_usage_calls. Started calls count gateway dispatch, even if cancellation prevents the adapter's first instruction. Unknown tokens are not zero consumption and are not counted as observed tokens.

If reported usage exceeds its bound, retain all reported tokens, increment reservation_breaches, and fail with `usage_exceeds_reservation`. Do not clamp to the configured limit. Remaining allowance may become negative. `observed_token_overrun` is `max(0, known_tokens - max_tokens)` for each job; report summary sums those per-job overruns, not a pooled allowance calculation.

`usage_complete` means no active reservation and no unknown-usage call. Cost completeness is separate: every started call must supply cost, no active work may remain, and currencies must permit a single total. Known costs always remain in `reported_cost_subtotals` by currency/source. An incomplete or mixed-currency `reported_cost` is null. A zero-call ledger has complete cost coverage but no numeric total (`reported_cost: null`); absence of a subtotal is not an inferred invoice of zero. Estimates never fill missing telemetry. The mock's `synthetic_mock` cost is fictional.

## CLI manifest and exit behavior

Run `python -m agent_budget_scheduler run <manifest.json> --out <directory>` from the clone root. The entire UTF-8 JSON manifest is validated before scheduling. Unknown fields, duplicate object keys/IDs, unsupported schema/mode/tools, or invalid mock arguments reject the whole input. Input is limited to 1 MiB, 1–1,000 jobs, 1–100 operations per job, and 10,000 operations total.

| Object | Fields |
| --- | --- |
| Root (all required) | `schema_version: "1.0"`, `execution_mode: "offline_mock"`, `config`, `jobs`. |
| Config | All SchedulerConfig fields optional, defaults above. |
| Job | Required `job_id`, `tenant`, `max_tool_calls`, `max_tokens`, `operations`; optional `priority`, `estimates`, `deadline_after_ms`, `cancel_after_ms`. |
| Estimates | Optional `tokens`, `duration_ms`, `cost`; present cost requires amount, currency, source. |
| Operation (all required) | `tool`, `token_upper_bound`, `arguments`. |

`lookup.record` requires fictional record `release-a` or `release-b`. `model.generate` requires input_tokens/output_tokens whose sum does not exceed its bound. `fault.raise` and `fault.missing_usage` deliberately fail; `fault.overrun` requires a sum greater than its bound. All tools optionally accept delay_ms/cleanup_delay_ms from 0–1,000. Model token counts are supplied synthetic integers, not tokenization of text.

The demo-only `cancel_after_ms` is 0–10,000: zero requests cancellation after the submission batch and before dispatch; positive values arm cancellation timers after that batch. It is not a JobSpec deadline. Scripts invoke operations sequentially, returning the last value.

Exit **0** means valid workload processing completed, including failures/rejections. Exit **2** means invalid/unreadable input (also argparse usage errors). Exit **1** means runner/output failure. The console's succeeded count is not a whole-workload success claim. Files replace existing report.json/events.jsonl; writes are not transactional and a write failure may leave partial/stale output. Use a new directory for a distinct run.

## Output semantics

`report.json` contains schema_version, execution_mode, policy (`tenant_round_robin_aging_priority`), config, summary, jobs in admission order, and rejection receipts. Job rows contain IDs, base priority, state/reason, limits, deadline, unchanged estimates, usage, queue_wait_ms, runtime_ms. Queue wait spans submission to dispatch; runtime spans dispatch to terminal including cleanup. Both are null without dispatch, and runtime is null until completion. Durations use the monotonic clock rounded to three decimals, not wall-clock timestamps. During STOPPING, the job row's reason remains null until terminal; use stop_requested for the latched reason.

Summary states reflect the snapshot, with accepted/rejected counts, aggregate usage, and observed running/tenant peaks. Rejected jobs have only job_id/reason receipts and no usage row. Payload values never appear in these outputs.

`events.jsonl` contains sequence numbers starting at 1, elapsed_ms since scheduler construction, schema_version, event_type, and decision-specific fields. Job events include job_id, tenant, state; admission_rejected contains its ID, tenant, reason, pending count. Event types are admitted, admission_rejected, dispatched, stop_requested, operation_started, operation_denied, operation_observed, operation_usage_unknown, terminal. Operations identify their per-job operation_id where one was allocated; a denial has no allocated ID. Cleanup before adapter entry may emit unknown usage without a tool field. Event ordering reflects serialized local decisions; elapsed time can tie and is not a cross-process ordering key.
