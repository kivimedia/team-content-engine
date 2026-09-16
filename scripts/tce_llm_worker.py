"""Run the TCE subscription LLM worker.

    python scripts/tce_llm_worker.py --api-base https://tce.example.com --once

The TCE private access key is read from TCE_PRIVATE_ACCESS_KEY and sent as a
Bearer token. The worker refuses to start if metered or third-party provider
variables are present, and verifies `claude auth status` before leasing.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tce.llm.worker import (  # noqa: E402
    EXIT_PREFLIGHT_FAILED,
    ApiClient,
    Worker,
    default_worker_id,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TCE subscription LLM worker")
    parser.add_argument("--api-base", default=os.environ.get("TCE_API_BASE", "http://localhost:8000"))
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--once", action="store_true", help="drain available jobs once, then exit")
    parser.add_argument("--max-jobs", type=int, default=None)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--lease-seconds", type=int, default=600)
    parser.add_argument("--job-timeout-seconds", type=float, default=540.0)
    args = parser.parse_args(argv)

    key = os.environ.get("TCE_PRIVATE_ACCESS_KEY", "")
    if not key:
        print("TCE_PRIVATE_ACCESS_KEY is not set; the llm-jobs routes require it.", file=sys.stderr)
        return EXIT_PREFLIGHT_FAILED

    worker = Worker(
        ApiClient(args.api_base, key),
        args.worker_id or default_worker_id(),
        lease_seconds=args.lease_seconds,
        job_timeout_s=args.job_timeout_seconds,
    )
    return worker.run(once=args.once, max_jobs=args.max_jobs, poll_seconds=args.poll_seconds)


if __name__ == "__main__":
    sys.exit(main())
