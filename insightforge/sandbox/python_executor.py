from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from insightforge.config import Settings
from insightforge.storage.database import TraceStore, utc_now


class PythonPolicyError(ValueError):
    pass


class PythonSandboxError(RuntimeError):
    pass


_ALLOWED_IMPORTS = {"json", "math", "statistics", "numpy", "pandas", "scipy"}
_FORBIDDEN_CALLS = {
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "exit",
    "getattr",
    "globals",
    "help",
    "input",
    "locals",
    "open",
    "quit",
    "setattr",
    "delattr",
    "vars",
    "__import__",
}
_FORBIDDEN_NAMES = {"__builtins__", "__loader__", "__spec__"}
_DATASET_READERS = {"read_csv", "read_parquet"}
_FORBIDDEN_ATTRIBUTES = {
    "environ",
    "getenv",
    "genfromtxt",
    "listdir",
    "load",
    "loadtxt",
    "popen",
    "read_feather",
    "read_html",
    "read_json",
    "read_orc",
    "read_pickle",
    "read_sql",
    "save",
    "savetxt",
    "scandir",
    "system",
    "to_csv",
    "to_parquet",
    "to_pickle",
    "to_sql",
    "urlopen",
    "walk",
}

_FORBIDDEN_ROOTS = {
    "builtins",
    "ctypes",
    "http",
    "importlib",
    "os",
    "pathlib",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "sys",
    "urllib",
}


def validate_python(code: str) -> None:
    if not code.strip():
        raise PythonPolicyError("Kode Python kosong.")
    if len(code) > 50_000:
        raise PythonPolicyError("Kode Python terlalu besar.")
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as error:
        raise PythonPolicyError(f"Syntax Python invalid: {error}") from error
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] not in _ALLOWED_IMPORTS:
                    raise PythonPolicyError(f"Import tidak diizinkan: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module_root = (node.module or "").split(".", 1)[0]
            if module_root not in _ALLOWED_IMPORTS:
                raise PythonPolicyError(f"Import tidak diizinkan: {node.module}")
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            raise PythonPolicyError(f"Name tidak diizinkan: {node.id}")
        elif isinstance(node, ast.Attribute):
            _validate_attribute(node)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_CALLS:
                raise PythonPolicyError(f"Call tidak diizinkan: {node.func.id}")
            if isinstance(node.func, ast.Attribute) and node.func.attr in _DATASET_READERS:
                if not node.args or not isinstance(node.args[0], ast.Name) or node.args[0].id != "DATASET_PATH":
                    raise PythonPolicyError("Dataset reader hanya boleh membaca DATASET_PATH.")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            raise PythonPolicyError("Global dan nonlocal tidak diizinkan.")


def _validate_attribute(node: ast.Attribute) -> None:
    if node.attr.startswith("_"):
        raise PythonPolicyError("Akses private/dunder tidak diizinkan.")
    if node.attr in _FORBIDDEN_ATTRIBUTES:
        raise PythonPolicyError(f"Attribute tidak diizinkan: {node.attr}")
    attribute_root: ast.AST = node.value
    while isinstance(attribute_root, ast.Attribute):
        attribute_root = attribute_root.value
    if isinstance(attribute_root, ast.Name) and attribute_root.id in _FORBIDDEN_ROOTS:
        raise PythonPolicyError(f"Module access tidak diizinkan: {attribute_root.id}")


class DockerPythonSandbox:
    marker = "__INSIGHTFORGE_RESULT__="

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(self, code: str, dataset_path: Path) -> dict[str, Any]:
        validate_python(code)
        if shutil.which("docker") is None:
            raise PythonSandboxError("Docker CLI tidak tersedia.")
        run_id = f"py_{uuid4().hex[:12]}"
        run_dir = self.settings.artifact_dir / "python_runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        script_path = run_dir / "runner.py"
        container_dataset = f"/data/dataset{dataset_path.suffix.lower()}"
        wrapper = (
            "import json, os\n"
            "DATASET_PATH = os.environ['INSIGHTFORGE_DATASET']\n"
            f"{code}\n"
            "if 'result' not in globals():\n"
            "    raise RuntimeError('Code must assign JSON-serializable variable result')\n"
            f"print('{self.marker}' + json.dumps(result, default=str, ensure_ascii=False))\n"
        )
        script_path.write_text(wrapper, encoding="utf-8")
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--pids-limit",
            "64",
            "--memory",
            f"{self.settings.python_memory_limit_mb}m",
            "--cpus",
            "1",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "-e",
            f"INSIGHTFORGE_DATASET={container_dataset}",
            "-v",
            f"{script_path.resolve()}:/workspace/runner.py:ro",
            "-v",
            f"{dataset_path.resolve()}:{container_dataset}:ro",
            "--entrypoint",
            "python",
            self.settings.python_sandbox_image,
            "-I",
            "/workspace/runner.py",
        ]
        started = perf_counter()
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=self.settings.python_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise PythonSandboxError(
                f"Python execution melebihi {self.settings.python_timeout_seconds} detik."
            ) from error
        output_limit = self.settings.python_max_output_kb * 1024
        if len(completed.stdout) + len(completed.stderr) > output_limit:
            raise PythonSandboxError("Output Python melebihi batas.")
        stdout = completed.stdout.decode("utf-8", errors="replace")
        stderr = completed.stderr.decode("utf-8", errors="replace")
        if completed.returncode != 0:
            raise PythonSandboxError(stderr.strip() or f"Container exit {completed.returncode}.")
        marker_line = next(
            (line for line in reversed(stdout.splitlines()) if line.startswith(self.marker)), None
        )
        if marker_line is None:
            raise PythonSandboxError("Python result marker tidak ditemukan.")
        try:
            result = json.loads(marker_line.removeprefix(self.marker))
        except json.JSONDecodeError as error:
            raise PythonSandboxError("Python result bukan JSON valid.") from error
        visible_stdout = "\n".join(
            line for line in stdout.splitlines() if not line.startswith(self.marker)
        )
        return {
            "run_id": run_id,
            "result": result,
            "stdout": visible_stdout,
            "stderr": stderr,
            "latency_ms": int((perf_counter() - started) * 1000),
            "script_uri": str(script_path.resolve()),
            "engine": "docker-python",
            "network_access": False,
        }


class PythonExecutionService:
    def __init__(self, store: TraceStore, sandbox: DockerPythonSandbox) -> None:
        self.store = store
        self.sandbox = sandbox

    def run(self, dataset_id: str, code: str) -> dict[str, Any]:
        dataset = self.store.get_dataset(dataset_id)
        if dataset is None:
            raise KeyError(dataset_id)
        plan = {"type": "python", "policy": "docker-read-only-no-network"}
        analysis = self.store.create_analysis(
            dataset_id, "Restricted Python execution", "approval", "running", plan
        )
        started = perf_counter()
        try:
            result = self.sandbox.execute(code, Path(dataset["storage_uri"]))
            self.store.add_step(
                analysis["id"],
                "python_agent",
                {"dataset_id": dataset_id},
                result,
                result["latency_ms"],
                "success",
                code=code,
            )
            return self.store.update_analysis(
                analysis["id"],
                status="completed",
                result_json={"python": result},
                final_answer="Python sandbox selesai.",
                completed_at=utc_now(),
            )
        except Exception as error:
            self.store.add_step(
                analysis["id"],
                "python_agent",
                {"dataset_id": dataset_id},
                {"error": str(error)},
                int((perf_counter() - started) * 1000),
                "failure",
                code=code,
            )
            return self.store.update_analysis(
                analysis["id"], status="failed", error=str(error), completed_at=utc_now()
            )
