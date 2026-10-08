# Local execution evidence

## Current M3 final local MVP: 2026-10-07

Main independently accepted M2 in `coordination/reviews/agent-budget-scheduler-M3.md` and assigned final documentation, bounded seeded core invariants, example evidence, and prepared CI. M3 changes add no scheduler runtime feature. The local MVP is ready for **independent whole-repository acceptance**, not yet accepted by main. All execution below used this clone root:

```text
C:\Users\shash\Documents\CodexPortfolios\agentic-ai-2026-10-07\agent-budget-scheduler
```

| Actual command/check | Observed result |
| --- | --- |
| `py -3.11 --version` | Python 3.11.9, exit 0. |
| `py -3.11 -m unittest tests.test_invariants -v` | One new seeded test passed, exit 0; 0.573 seconds observed. Eight seeds, 160 transitions per seed plus drain; independent counts/reservation bookkeeping, terminal stability, and rejection/dispatch/stop/finish/reserve/denial/observe/unknown coverage all checked. |
| `py -3.11 -m unittest discover -s tests -v` | **33 tests**, `OK`, exit 0; reported 7.835 seconds. All existing 32 tests retained and passing. Test duration is an observation, not a benchmark. |
| `py -3.11 scripts/check_examples.py --out work/m3-demo` | Exit 0; seven PASS lines and an actual summary receipt. Every child CLI exited 0, literal outcomes/ledgers/capacity/events checked, every fixture's bytes preserved. |
| `py -3.11 scripts/check_examples.py --out examples/sample-output` | Exit 0; seven PASS lines. Saved seven report.json/events.jsonl pairs and summary.json in the repository. Receipt UTC time `2026-10-07T16:18:05.624057+00:00`, Python 3.11.9, Windows platform reported by Python. |
| `py -3.11 -m examples.embedded_agent` | Exit 0; SUCCEEDED, two started calls, 40 observed mock tokens, zero unknown/active/unresolved usage. Returned answer explicitly labeled `[MOCK]`. |
| Official GitHub tag-ref reads via Invoke-RestMethod; pinned manifests, READMEs, license texts, Python versions manifest and official hardening guidance read | checkout v4.3.0 resolved to commit `08eba0b27e820071cde6df949e0beb9ba4906955`; setup-python v6.0.0 to commit `e797f83bcb11b83ae66e0230d6156d7c80228e7c`. Node 20/24 manifests and MIT licenses verified; Python 3.11.9 linux-24.04/win32 x64 artifacts listed. Metadata verification only; no action/interpreter artifact downloaded or hosted job run. Exact links/retrieval date in docs/RESEARCH.md. |
| `py -3.11 work/verify_delivery.py` | Exit 0; 52 text files inspected without trailing whitespace, Python AST syntax parsed, all relative Markdown links resolved, seven saved reports/events rechecked, fixture hashes matched receipts, CI required fields/action pins checked as text. This scratch inspection is not a YAML linter or hosted action execution. |
| `git status --short`; `git diff --check` | Exit 0; source remains local/uncommitted and untracked in the initially empty repository, including the preserved AGENTS.md. No tracked diff exists, so Git's whitespace check alone does not inspect new files; the separate 52-file inspection supplies that check. |

The M2 scenario table below still describes the final seven-fixture results. [Saved evidence](examples/sample-output/README.md) now makes every report/event stream reviewable. The checker also establishes contiguous event sequence numbers, exactly one terminal per accepted job, no subsequent job decision after terminal, zero final active reservations per job, and no started operation for a rejected job. It checks literal budget/fault reasons, basic estimates versus observations, retained synthetic cost subtotals, fairness rotation, aging priority, and the queued-stop no-call results. Expected values are not derived from the scheduler policy under test.

Documentation covers exact lifecycle/stop precedence, capacity through cleanup, reservation/unknown/cost semantics, timing fields, CLI exits/replacement behavior, original contribution, primary-source comparisons, and cooperative limitations. Windows and POSIX clone-root instructions are present; only Windows execution has been performed.

`.github/workflows/ci.yml` is prepared for ubuntu-24.04/windows-2022, Python 3.11.9, read-only `contents` permissions, full action commit pins, `persist-credentials: false`, and stdlib test/CLI/embedding steps. It contains no secrets, provider/service calls, install command, deployment, push, or artifact publication. Source/actions/interpreter fetches may use GitHub network access. **Hosted CI is unexecuted**; no hosted success or free account-minute entitlement is claimed. No scheduler expansion, heavy lease, dependency installation, paid call, external account mutation, publication, or deployment occurred.

Remaining checks: final independent main acceptance and hosted Linux/Windows execution. POSIX quickstart/runtime execution, actual hosted action/interpreter installation, performance/stress/security testing, live providers, production spending limits, distributed scheduling, durability, and rollback remain unexecuted or outside this MVP. The preserved M2 harness failure and correction below are historical evidence, not an unresolved final test failure.

## Historical M2 slice: 2026-10-07

Main independently accepted M1 and explicitly assigned M2. M2 now implements within-tenant aging, submission-relative queued/running deadlines, queued/running cooperative cancellation, failure fixtures, and owned-operation cleanup. **M3 CI/full design docs remain deferred.** Execution stays local, standard-library-only, on CPython 3.11.9 selected by `py -3.11`; no heavy lease, installation, live model/provider call, service, paid call, publication, or deployment was used.

Actually executed in the repository workdir recorded below:

| Command/check | Observed result |
| --- | --- |
| `py -3.11 --version` | Python 3.11.9. |
| `py -3.11 -m unittest discover -s tests -v` | Final **32 tests**, `OK`, exit 0; 2.753 seconds reported. Duration is an observed test-run result, not a benchmark. Preserved M1 tests also pass. |
| `py -3.11 -m agent_budget_scheduler run examples/<scenario>.json --out work/m2/<scenario>` for basic, fairness, aging, overload, budgets, lifecycle, faults | All seven CLI commands exited 0 and wrote parseable schema-1.0 JSON/JSONL. They were executed sequentially in a PowerShell foreach with every exit checked. |
| `py -3.11 -m examples.embedded_agent` | Exit 0; preserved one success, two started calls, 40 observed mock tokens, visibly labeled mock answer, and no unknown usage. |
| `py -3.11 -c ...` independent reads/assertions against actual `work/m2/*` output files | All expected terminal-state maps passed, as did fairness/aging dispatch order, basic 65 tokens, zero remaining active reservations, lifecycle 120 unresolved tokens, and fault 25 observed/15 overrun/50 unresolved tokens. |
| `py -3.11 -c ...` source whitespace scan; `git status --short`; `git diff --check` | Scanned 29 text files with no trailing spaces/tabs, exit 0. Source remains local/untracked; AGENTS.md was preserved. Git's check returned 0 with no tracked diff, so the separate scan supplied the untracked-file check. |

Observed scenario results (fresh **offline_mock** execution):

| Fixture | Terminal states | Rejected | Calls | Known tokens | Unknown calls | Unresolved tokens | Observed overrun |
| --- | --- | --- | --- | --- | --- | --- | --- |
| basic | SUCCEEDED 2 | 0 | 4 | 65 | 0 | 0 | 0 |
| fairness | SUCCEEDED 5 | 0 | 5 | 0 | 0 | 0 | 0 |
| aging | SUCCEEDED 3 | 0 | 3 | 0 | 0 | 0 | 0 |
| overload | SUCCEEDED 2 | 1 | 2 | 0 | 0 | 0 | 0 |
| budgets | BUDGET_EXHAUSTED 2, SUCCEEDED 1 | 0 | 3 | 40 | 0 | 0 | 0 |
| lifecycle | CANCELLED 2, DEADLINE_EXCEEDED 2, SUCCEEDED 1 | 0 | 3 | 0 | 2 | 120 | 0 |
| faults | FAILED 3, SUCCEEDED 1 | 0 | 4 | 25 | 2 | 50 | 15 |

All seven reports end with zero **active** reservations. Unresolved reservations in interrupted/missing-usage cases remain visible and are not counted as observed consumption or silently erased. The fault fixture retains all 25 reported tokens against its 10-token reservation/job budget, reports one breach and a negative remaining allowance of -15. Complete reported cost is null where cost telemetry is missing; known synthetic cost subtotals are retained. No monetary cap or arbitrary-provider token-consumption guarantee is claimed.

Fairness dispatch was `alpha, beta, gamma, alpha, alpha`. The aging fixture dispatched `blocker, old-low, later-high`; the old low-priority job's recorded effective priority was 9. Its deterministic core test separately proves the boundary: with a 10-ms interval, a priority-0 job loses to a later priority-9 job at 89 ms and wins the enqueue-order tie at 90 ms.

Controlled-event/fake-clock assertions establish:

- Queued cancellation/deadline expiry invokes neither callback nor adapter; queued deadline timing starts at submission.
- Running cancellation and deadline stops hold one running slot during a deliberately blocked cleanup gate, keep the follower queued, and release it only when actual cleanup finishes. Later cancellation/deadline requests preserve the first reason and do not interrupt cleanup again.
- Cancelled waiters leave the underlying job running; its subsequent result is still available.
- Cancellation between dispatch and callback entry resolves the future without running the callback. Cancellation before adapter entry leaves no active reservation leak and records conservative unresolved usage.
- A suppressed cancellation cannot start another guarded operation or turn the job into success; already reported usage is retained.
- A callback returning with owned operation work pending fails; cleanup is shielded from a later parent cancellation, and its follower cannot start early.
- Deadline checks before guarded invocation and at completion prevent late work/success even before timer delivery. A cancellation requested after a due deadline first records deadline expiry.
- Unknown usage retains the declared bound; a known adapter-reported cost can still be retained separately. Adapter exception text is absent from reports/events. An overrun and caught budget denial cannot become success, and unrelated jobs still run.
- The public CLI tests independently parse the six new scenario reports and check exact states, rejected-work non-invocation, capacity limits, fair/aged order, and truthful ledger totals.

An initial expanded run executed 27 tests and exited 1 with one **test-harness scheduling failure**: the test used `wait_for(wait_event(...))`, which created another task and allowed an immediate callback to complete before cancellation. The expected between-dispatch-and-entry cancellation was not controlled. The test was corrected to enqueue an explicit event-loop cancellation callback after the dispatch pump and before the new job task's first turn; it still requires CANCELLED, zero callback invocations, and one dispatched slot. The corrected 27-test run passed, and later 29/30/final 32-test runs passed after additional CLI/boundary cases. No assertion was weakened or result invented.

Remaining checks: main's independent M2 review; M3 full architecture/contracts/limitations/research docs and hosted CI; bounded randomized core suite. Linux/other Python runtime execution, live providers, security isolation, hard spending enforcement, benchmarks, durability, distributed scheduling, and external-side-effect rollback remain unexecuted or outside the agreed MVP. README states the cooperative boundary: blocking or cancellation-suppressing trusted code may delay timers, cleanup, and slot release. Decision history is memory-held for bounded runs, not a durable audit log.

## Historical M1 evidence

Date: **2026-10-07**. Scope: main's explicitly accepted **M1 slice**, not completion of the full PLAN.md MVP. Evidence was gathered on this Windows/PowerShell workspace with **CPython 3.11.9 selected by `py -3.11`**. No dependency installation, heavy build, service, model download, network/model execution, paid call, publication, or deployment was used for these checks. No heavy resource lease was needed for the bounded standard-library suite.

Repository workdir for every command below:

```text
C:\Users\shash\Documents\CodexPortfolios\agentic-ai-2026-10-07\agent-budget-scheduler
```

## Commands actually executed

| Command | Observed result |
| --- | --- |
| `py -3.11 --version` | `Python 3.11.9`. |
| `py -3.11 -m unittest discover -s tests -v` | First run: 13 tests passed. After an additional started-call assertion and cleanup hardening, the final run passed **14 tests**, `OK`, exit 0; reported duration 0.949 seconds. This is a test-run observation, not a performance benchmark. |
| `py -3.11 -m agent_budget_scheduler run examples/basic.json --out work/basic` | Exit 0. Wrote parseable `work/basic/report.json` and `work/basic/events.jsonl`; console output reproduced below. |
| `py -3.11 -m examples.embedded_agent` | Exit 0. Printed `execution_mode: offline_mock`, `state: SUCCEEDED`, the fictional lookup text and `[MOCK] deterministic synthetic summary`, two started calls and 40 observed tokens. |
| `py -3.11 -m agent_budget_scheduler --help` | Exit 0; exposed the `run` command and offline-tool description. |
| `py -3.11 -c ...` independent generated-report assertions | Parsed the actual basic output files; asserted literal success/call/token totals, zero unknown/active/unresolved usage and breaches/overruns, capacity peaks within config, and unchanged submitted token estimates. All assertions passed; 14 ordered events were parsed. |
| `git status --short` / `rg --files ...` | Confirmed source/examples/tests/docs exist; new files remain untracked in the initially empty repository. AGENTS.md was preserved. Scratch output/cache directories are ignored. |
| `git diff --check` | Exit 0 with no tracked diff; this does **not** inspect the untracked implementation. A separate text-whitespace scan is recorded below. |
| `py -3.11 -c ...` source text-whitespace scan | Read 22 source/document/fixture text files outside work/cache/Git directories; found no trailing spaces/tabs. Exit 0. |

Basic CLI console output:

```text
mode=offline_mock accepted=2 rejected=0 succeeded=2 started_tool_calls=4 observed_known_tokens=65 unknown_usage_calls=0
Report: work\basic\report.json
Events: work\basic\events.jsonl
```

Independent inspection of the actual `work/basic/report.json` observed:

```json
{
  "accepted": 2,
  "rejected": 0,
  "states": {"SUCCEEDED": 2},
  "started_tool_calls": 4,
  "observed_known_tokens": 65,
  "unknown_usage_calls": 0,
  "active_reserved_tokens": 0,
  "unresolved_reserved_tokens": 0,
  "reservation_breaches": 0,
  "observed_token_overrun": 0,
  "usage_complete": true,
  "peak_running": 2,
  "peak_running_by_tenant": {"alpha": 1, "beta": 1}
}
```

Per-job observed token totals were **40** and **25**, while submitted token estimates remained **100** and **200**. Submitted cost estimates remained `0.50` and `0.75 USD`. The complete mock-reported cost was `0.000065 USD`, explicitly sourced as `synthetic_mock`. This rate/data is fictional and is not a provider price, actual bill, model quality result, or recorded replay.

## Meaningful checks in the 14-test suite

- The basic API and public CLI assert the literal 2-success/4-call/65-token totals, no unknown usage/budget breaches/overruns, unchanged estimates, and returned `[MOCK]` values.
- Actual callback counters are maintained independently of scheduler accounting. Events hold the first two callbacks open while the test checks that only `a1` and `b1` have started, three jobs remain queued, global active count is two, and per-tenant active counts are one. After releasing the gate, all five callbacks finish; measured peaks never exceed those limits.
- A controlled adapter holds a 60-token reservation against a 100-token budget. A competing 60-token request is denied before adapter invocation, leaving one started call and 60 active reserved tokens. After releasing the first call, observed usage is 60, reservations are zero, and allowance is 40. An agent catching the denial still receives a `BUDGET_EXHAUSTED` outcome.
- A separate sequential case reserves 60, observes 40, releases 20 unused tokens, and admits another 60-token reservation. It proves reconciliation permits useful remaining work rather than charging every reservation as observed usage.
- A one-call limit admits one zero-token operation and refuses the next without incrementing the started count or invoking the adapter.
- Policy tests assert tenant order `alpha, beta, gamma, alpha, alpha`, priority then FIFO within a tenant, bounded pending admission, and duplicate ID refusal.
- Contract/CLI tests refuse invalid counts, boolean counts, invalid priority/cost data, unsupported fields/version, duplicates, and mock usage above a declared bound during manifest preflight. Invalid CLI input creates no output directory. Events omit synthetic tool payloads/returned text.

Tests use controlled asyncio events and bounded timeouts rather than timing-sensitive capacity assertions. The demonstration's short mock sleeps are not latency tests.

## Historical M1 review boundary and unexecuted checks

At the M1 review boundary the CLI/API, two safe mocks, basic fixture, embedding example, validated contracts, capacity/admission/tenant selection, and guarded ledger were implemented. The current M2 record above supersedes the deferred M2 checklist below; PLAN.md contains the accepted wider plan.

**Unexecuted at the historical M1 boundary:** priority aging; queue/running deadlines; user cancellation and lifecycle race scenarios; expanded failure/unknown/overrun fixtures and tests; restart/durability or distributed execution; randomized policy suite; full architecture/contracts/limitations/research documents; hosted Linux/Windows CI. M2 was subsequently assigned and executed as recorded above; M3 remains deferred.

No live provider/API, security isolation, hard spending cap, external-side-effect rollback, model quality evaluation, benchmark, adoption claim, or exactly-once claim has been tested or asserted. Main's M1 acceptance was pending at that historical boundary and was subsequently granted; independent M2 acceptance remains pending.

All source and checks are standard-library-only. Original code/fixtures use MIT; the runtime/reference attribution is in THIRD_PARTY_NOTICES.md. Generated output is reproducible scratch evidence under ignored `work/`, not a required checked-in artifact.
