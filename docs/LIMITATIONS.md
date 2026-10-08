# Contribution and limitations

## What this repository contributes

The original contribution is a small, inspectable implementation combining bounded admission, tenant round robin, priority aging, guarded call/token reservations, cooperative stop/cleanup, and reports that retain uncertainty and overruns. The Python embedding and seven fictional workloads demonstrate the same scheduler. Controlled tests expose races that a console-only happy path would miss, and the verification script checks actual report/event data.

Round robin, aging, asyncio cancellation, and resource reservation are established techniques. This repository does not claim a new scheduling algorithm, a better-performing replacement for established tools, or empirical superiority. [RESEARCH.md](RESEARCH.md) records overlapping capabilities in APScheduler, Celery, and LiteLLM and the narrower purpose of this prototype.

## Execution and accounting boundaries

- Trusted cooperative callbacks share one event loop. Blocking code delays timers and every other job. Cancellation-suppressing callbacks/adapters can retain slots and delay shutdown indefinitely. Deadlines request a stop; they are not hard execution deadlines.
- Capacity limits bound dispatched jobs, including cleanup. They do not bound callback-created threads, arbitrary tasks, CPU, memory, sockets, or provider-side concurrency. There is no sandbox or multi-process isolation.
- Reservations prevent new guarded dispatch beyond the conservative allowance when adapters honor their total-token bounds. They cannot constrain a dishonest adapter or undisclosed provider usage. Full observed overruns remain visible. Unknown usage keeps a bound, which is uncertainty rather than an actual measurement.
- All accountable tool/model operations must go through JobContext. Calls made directly by a callback, provider-internal retries, hidden tool calls, and background side effects are outside accounting unless the adapter includes them in its declared bound and returned telemetry.
- Cost is adapter-reported information, separate from estimates. There is no monetary reservation, provider-price feed, invoice verification, hard spending cap, or currency conversion. Mock cost/token values are supplied synthetic telemetry.
- Cancellation cannot undo external effects or establish whether an interrupted remote request succeeded. There is no automatic retry, idempotency protocol, transaction, exactly-once guarantee, rollback, or provider integration in this MVP.
- The API retains completed jobs, tenant queues, ledgers, IDs, and events in memory. Pending admission is bounded, but cumulative history is not an unbounded-service memory guarantee. There is no persistence, restart recovery, distributed coordination, or durable audit log.
- Labels and decision outputs reduce payload exposure; they are not general PII/secret redaction. Trusted labels, cost sources, and custom JobFault reasons can contain application information. The API outcome may contain arbitrary returned content and mutable nested values.
- Final files can be replaced or partially written. They are evidence snapshots, not signed receipts, replay inputs, billing records, or transactionally committed logs.

## Evidence limits

The local reference is Windows with CPython 3.11.9. Hosted ubuntu-24.04/windows-2022 execution is prepared but unexecuted. Immutable action pins and available Python artifacts were checked from primary metadata; their actual hosted execution was not tested. Other runtimes/platforms, real providers, security isolation, resource stress, benchmarks, long-lived operation, and production rollout remain unexecuted.

The bounded seeded sweep is reproducible coverage, not exhaustive model checking. Controlled event/fake-clock tests establish the documented races; short real-delay demonstrations do not establish latency bounds. Saved example timings are machine-specific observations. CPython 3.11.9 is a pinned reproducibility baseline, not a claim to the newest security patch. No deployment, publication, service purchase, or paid provider call was performed.
