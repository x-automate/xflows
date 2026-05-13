from __future__ import annotations

import json
import time
from pathlib import Path
from statistics import quantiles

import requests

API_BASE_URL = "http://localhost:8000"
WORKFLOW_ID = "wf_support_assistant"
TESTCASE_FILE = Path(__file__).with_name("testcases.json")


def wait_for_run(run_id: str, timeout_seconds: int = 90) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        run = requests.get(f"{API_BASE_URL}/runs/{run_id}", timeout=10).json()
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            return run
        time.sleep(0.5)
    raise TimeoutError(f"Run {run_id} timed out")


def evaluate() -> int:
    testcases = json.loads(TESTCASE_FILE.read_text(encoding="utf-8"))
    latencies = []
    failures = []

    for testcase in testcases:
        started = time.time()
        response = requests.post(
            f"{API_BASE_URL}/workflows/{WORKFLOW_ID}/runs",
            json={"input": testcase["input"]},
            timeout=10,
        )
        response.raise_for_status()
        run_id = response.json()["id"]
        run = wait_for_run(run_id)
        elapsed = time.time() - started
        latencies.append(elapsed)

        output = (run.get("output") or "").lower()
        expectations = [value.lower() for value in testcase.get("expect_contains_any", [])]
        if run["status"] != "succeeded" or (expectations and not any(value in output for value in expectations)):
            failures.append(
                {
                    "test": testcase["name"],
                    "status": run["status"],
                    "output": run.get("output"),
                }
            )

    p95 = quantiles(latencies, n=100, method="inclusive")[94] if latencies else 0
    print(json.dumps({"total": len(testcases), "failures": len(failures), "p95_latency_seconds": p95}, indent=2))
    if failures:
        print(json.dumps({"failed_cases": failures}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(evaluate())
