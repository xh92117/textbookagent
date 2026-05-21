import subprocess
import sys
import os
import tempfile
import time
import ast
from dataclasses import dataclass
from typing import Optional


@dataclass
class SandboxResult:
    success: bool = False
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    output_files: list = None
    execution_time: float = 0.0

    def __post_init__(self):
        if self.output_files is None:
            self.output_files = []


class SandboxExecutor:
    FORBIDDEN_IMPORTS = ['os', 'subprocess', 'shutil', 'socket', 'http', 'urllib', 'requests', 'sys']
    FORBIDDEN_CALLS = {'eval', 'exec', 'compile', '__import__', 'open', 'input'}
    FORBIDDEN_ATTRS = {'__subclasses__', '__globals__', '__code__', '__closure__'}

    def __init__(self, timeout: int = 30, output_dir: str = ""):
        self.timeout = timeout
        self.output_dir = output_dir or tempfile.mkdtemp(prefix="sandbox_")
        os.makedirs(self.output_dir, exist_ok=True)

    def _validate_code(self, code: str) -> tuple:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return False, f"Syntax error: {exc}"

        forbidden_roots = set(self.FORBIDDEN_IMPORTS)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root in forbidden_roots:
                        return False, f"Forbidden import: {root}"
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".", 1)[0]
                if root in forbidden_roots:
                    return False, f"Forbidden import: {root}"
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in self.FORBIDDEN_CALLS:
                    return False, f"Forbidden call: {node.func.id}"
                if (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "importlib"
                    and node.func.attr == "import_module"
                ):
                    return False, "Forbidden call: importlib.import_module"
            elif isinstance(node, ast.Attribute) and node.attr in self.FORBIDDEN_ATTRS:
                return False, f"Forbidden attribute: {node.attr}"
        return True, ""

    def execute(self, code: str, timeout: int = None) -> SandboxResult:
        timeout = timeout or self.timeout

        valid, reason = self._validate_code(code)
        if not valid:
            return SandboxResult(
                success=False,
                stderr=reason or "Code contains forbidden sandbox operations",
                exit_code=-1,
            )

        code = f"import sys\nsys.path.insert(0, '')\n{code}"

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(code)
            script_path = f.name

        try:
            start_time = time.time()
            env = {
                key: value
                for key, value in os.environ.items()
                if key in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"}
            }
            env['MPLCONFIGDIR'] = tempfile.mkdtemp()
            env['PYTHONPATH'] = self.output_dir
            env['PYTHONIOENCODING'] = 'utf-8'

            result = subprocess.run(
                [sys.executable, "-I", script_path],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=self.output_dir,
                env=env,
            )
            execution_time = time.time() - start_time

            output_files = []
            for f_name in os.listdir(self.output_dir):
                f_path = os.path.join(self.output_dir, f_name)
                if os.path.isfile(f_path) and f_name.endswith(('.png', '.jpg', '.svg', '.pdf', '.html')):
                    output_files.append(f_path)

            return SandboxResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                output_files=output_files,
                execution_time=execution_time,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                success=False,
                stderr=f"Execution timed out after {timeout} seconds",
                exit_code=-1,
                execution_time=timeout,
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                stderr=str(e),
                exit_code=-1,
            )
        finally:
            try:
                os.unlink(script_path)
            except:
                pass
