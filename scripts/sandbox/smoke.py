from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.sandbox.docker_runtime import SANDBOX_LABEL, DockerSandboxRuntime
from backend.sandbox.manager import SandboxManager


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    runtime = DockerSandboxRuntime()
    health = runtime.health()
    _require(health.available, f"Docker sandbox is not ready: {health.error_code}")
    print("[PASS] Docker daemon")
    print("[PASS] sandbox image")

    manager = SandboxManager(runtime)
    compute = manager.execute_python("print(1 + 1)")
    _require(
        compute.exit_code == 0 and compute.stdout.strip() == "2",
        "Python execution failed.",
    )
    print("[PASS] python execute")

    network = manager.execute_python(
        "import urllib.request\n"
        "try:\n"
        "    urllib.request.urlopen('https://example.com', timeout=2)\n"
        "except Exception:\n"
        "    print('NETWORK_BLOCKED')\n"
        "else:\n"
        "    print('NETWORK_ALLOWED')\n"
    )
    _require(
        network.exit_code == 0 and "NETWORK_BLOCKED" in network.stdout,
        "The sandbox unexpectedly reached the network.",
    )
    print("[PASS] network disabled")

    timeout_runtime = DockerSandboxRuntime(timeout_seconds=1.0)
    timeout_result = SandboxManager(timeout_runtime).execute_python(
        "while True:\n    pass"
    )
    _require(timeout_result.timed_out, "Sandbox execution did not time out.")
    print("[PASS] timeout kill")

    leaked = runtime._get_client().containers.list(
        all=True,
        filters={"label": f"{SANDBOX_LABEL}=true"},
    )
    _require(not leaked, f"Sandbox containers remain after smoke execution: {leaked}")
    print("[PASS] container cleanup")


if __name__ == "__main__":
    main()
