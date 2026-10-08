# Primary-source research and pins

Sources below were opened/read on **2026-10-07** during planning/final delivery. Versioned artifacts are distinct from rolling documentation snapshots. Comparisons are scoped observations from those sources, not compatibility tests. No referenced implementation, provider SDK, external dataset, or model is installed or vendored. The fuller planning record is in [PLAN.md](../PLAN.md).

| Source | Version/snapshot and relevance |
| --- | --- |
| [CPython release/artifacts](https://www.python.org/downloads/release/python-3119/) and [tagged license](https://raw.githubusercontent.com/python/cpython/v3.11.9/LICENSE) | CPython 3.11.9, verified installed locally. PSF License Version 2 plus historical/incorporated notices. Chosen reproducibility baseline. |
| [asyncio task documentation](https://docs.python.org/3.11/library/asyncio-task.html) and [tagged tasks.py](https://raw.githubusercontent.com/python/cpython/v3.11.9/Lib/asyncio/tasks.py) | The 3.11 docs are rolling patch documentation; tagged source fixes the implementation reference. Cancellation and shield behavior inform cooperative cleanup/wait ownership, not forced process termination. |
| [APScheduler user guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html), [3.11.3 artifact](https://pypi.org/project/APScheduler/3.11.3/) | 3.x guide snapshot, displayed 3.11.3.post3; compared against versioned MIT package metadata. Existing job scheduling, executor/job-store, and concurrency controls overlap with general scheduling; this MVP focuses on per-agent guarded usage and local decision inspection. Not installed. |
| [Celery worker guide](https://docs.celeryq.dev/en/v5.6.2/userguide/workers.html), [5.6.2 artifact](https://pypi.org/project/celery/5.6.2/) | Versioned 5.6.2 documentation/artifact, BSD-3-Clause. Existing worker concurrency, revocation, and time-limit capabilities overlap; this repository omits broker/distributed execution. This is not a latest-version claim. Not installed. |
| [LiteLLM budgets/users](https://docs.litellm.ai/docs/proxy/users) | Unversioned retrieval snapshot: existing user/team/session budgets and proxy controls overlap with budget management. This prototype's reservation/unknown ledger is local; it does not claim provider proxy compatibility or replace a production budget service. Not installed. |
| [OpenAI Responses Python create reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create) | Unversioned retrieval snapshot: output/tool bounds and response usage are relevant adapter concerns. A provider output limit alone does not define this scheduler's total input/output upper bound. Research only; no SDK, key, model pin, API call, or compatibility claim. |
| [GitHub Actions hardening guidance](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions) | Retrieval snapshot supports full commit pins and minimal token permissions. The prepared workflow uses contents: read and disables persisted checkout credentials. |

## Prepared CI dependencies

Both tag refs were resolved to **commit** objects in the original action repositories, and the pinned action manifests/license texts were read. These actions are CI dependencies, not Python runtime dependencies.

| Action | Verified immutable commit | Source and license |
| --- | --- | --- |
| actions/checkout v4.3.0 (Node 20) | `08eba0b27e820071cde6df949e0beb9ba4906955` | [Tag ref](https://api.github.com/repos/actions/checkout/git/ref/tags/v4.3.0), [pinned manifest](https://raw.githubusercontent.com/actions/checkout/08eba0b27e820071cde6df949e0beb9ba4906955/action.yml), [MIT license](https://raw.githubusercontent.com/actions/checkout/v4.3.0/LICENSE). |
| actions/setup-python v6.0.0 (Node 24) | `e797f83bcb11b83ae66e0230d6156d7c80228e7c` | [Tag ref](https://api.github.com/repos/actions/setup-python/git/ref/tags/v6.0.0), [pinned manifest](https://raw.githubusercontent.com/actions/setup-python/e797f83bcb11b83ae66e0230d6156d7c80228e7c/action.yml), [MIT license](https://raw.githubusercontent.com/actions/setup-python/v6.0.0/LICENSE), [pinned README](https://raw.githubusercontent.com/actions/setup-python/e797f83bcb11b83ae66e0230d6156d7c80228e7c/README.md). |

The [official Python versions manifest](https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json), read on the same date, lists stable Python 3.11.9 x64 artifacts for linux-24.04 and win32: `python-3.11.9-linux-24.04-x64.tar.gz` and `python-3.11.9-win32-x64.zip` in release `3.11.9-9947079978`. This verifies listed availability, not a downloaded hash or hosted installation. Runner images evolve; action/runtime pins do not freeze the whole operating system image.

The workflow runs unittest, seven offline CLI assertions, and the embedding demo, using no secrets, provider calls, deployment, publication, or package installation. Fetching source/actions or a missing interpreter may require CI network access. Hosted execution remains **unexecuted**; local evidence is in [EVIDENCE.md](../EVIDENCE.md).
