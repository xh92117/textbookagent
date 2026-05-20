import subprocess
import sys
import os
import tempfile
import time
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

    def __init__(self, timeout: int = 30, output_dir: str = ""):
        self.timeout = timeout
        self.output_dir = output_dir or tempfile.mkdtemp(prefix="sandbox_")
        os.makedirs(self.output_dir, exist_ok=True)

    def _validate_code(self, code: str) -> bool:
        for forbidden in self.FORBIDDEN_IMPORTS:
            patterns = [
                f'import {forbidden}',
                f'from {forbidden}',
            ]
            for pattern in patterns:
                if pattern in code:
                    return False
        return True

    def execute(self, code: str, timeout: int = None) -> SandboxResult:
        timeout = timeout or self.timeout

        if not self._validate_code(code):
            return SandboxResult(
                success=False,
                stderr="Code contains forbidden imports (os, subprocess, socket, etc.)",
                exit_code=-1,
            )

        code = f"import sys\nsys.path.insert(0, '')\n{code}"

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(code)
            script_path = f.name

        try:
            start_time = time.time()
            env = os.environ.copy()
            env['MPLCONFIGDIR'] = tempfile.mkdtemp()
            env['PYTHONPATH'] = self.output_dir

            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True,
                text=True,
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
