# Runtime and reference attribution

The implementation has **no third-party runtime or test package dependencies**. It does not vendor an interpreter, SDK, model, third-party source implementation, or external dataset. The code and fictional fixtures were authored for this repository under its MIT license.

The reference runtime is CPython **3.11.9**, using its standard library (asyncio, dataclasses, JSON, Decimal, argparse, pathlib, typing, time, collections, unittest and their dependencies). Python software/documentation is covered by the PSF License Version 2 and its historical/incorporated notices. See the [tagged runtime license](https://raw.githubusercontent.com/python/cpython/v3.11.9/LICENSE) and [official release/artifact page](https://www.python.org/downloads/release/python-3119/), read on 2026-10-07. The runtime is already installed locally and is not distributed here. If it is bundled later, its complete license notices must accompany it.

Conceptual references read during planning include official Python asyncio documentation/source, APScheduler documentation/PyPI metadata (MIT), Celery documentation/PyPI metadata (BSD-3-Clause), LiteLLM budget documentation, and official OpenAI Responses usage/bound documentation. They are comparison/research sources, not dependencies. Exact URLs and version/retrieval caveats are recorded in [docs/RESEARCH.md](docs/RESEARCH.md) and [PLAN.md](PLAN.md). No source implementation or API SDK from those projects is copied or installed.

The prepared [CI workflow](.github/workflows/ci.yml) references these MIT-licensed actions. Their tag refs, pinned manifests, and full license texts were read on 2026-10-07. Action source is fetched by CI, not vendored here. Hosted execution is unexecuted.

| CI dependency | Immutable commit | License |
| --- | --- | --- |
| actions/checkout v4.3.0 | `08eba0b27e820071cde6df949e0beb9ba4906955` | [MIT, GitHub and contributors](https://raw.githubusercontent.com/actions/checkout/v4.3.0/LICENSE) |
| actions/setup-python v6.0.0 | `e797f83bcb11b83ae66e0230d6156d7c80228e7c` | [MIT, GitHub and contributors](https://raw.githubusercontent.com/actions/setup-python/v6.0.0/LICENSE) |

The CPython distribution selected by setup-python has its own runtime notices above. No model weights, provider SDK, external corpus, or third-party Python package is part of this project. This notice is attribution for actual runtime/CI use and research, not a license claim for unrelated upstream software.
