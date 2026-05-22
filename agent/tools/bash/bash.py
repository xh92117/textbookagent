"""
Bash tool - Execute bash commands
"""

import base64
import os
import re
import sys
import subprocess
import tempfile
from typing import Dict, Any

from agent.tools.base_tool import BaseTool, ToolResult
from agent.tools.utils.truncate import truncate_tail, format_size, DEFAULT_MAX_LINES, DEFAULT_MAX_BYTES
from common.log import logger
from common.utils import expand_path


class Bash(BaseTool):
    """Tool for executing bash commands"""

    _IS_WIN = sys.platform == "win32"

    name: str = "bash"
    description: str = f"""Execute a bash command in the current working directory. Returns stdout and stderr. Output is truncated to last {DEFAULT_MAX_LINES} lines or {DEFAULT_MAX_BYTES // 1024}KB (whichever is hit first). If truncated, full output is saved to a temp file.
{'''
PLATFORM: Windows (cmd.exe). Do NOT use Unix-only commands like grep, head, tail, sed, awk.
Prefer ASCII/English command text and stable machine-readable output. Summarize results to the user in Chinese.
If PowerShell is invoked, the tool normalizes PowerShell's output pipeline to UTF-8. Do not use PowerShell to write Chinese prose files.
''' if _IS_WIN else ''}
ENVIRONMENT: All API keys from env_config are auto-injected. Use $VAR_NAME directly.

SAFETY:
- Freely create/modify/delete files within the workspace
- Destructive commands targeting absolute paths outside the workspace are blocked
- Remote script execution patterns such as curl|sh or Invoke-Expression are blocked"""

    params: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Bash command to execute"
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (optional, default: 30)"
            }
        },
        "required": ["command"]
    }

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd", os.getcwd())
        # Ensure working directory exists
        if not os.path.exists(self.cwd):
            os.makedirs(self.cwd, exist_ok=True)
        self.default_timeout = self.config.get("timeout", 30)
        # Enable safety mode by default (can be disabled in config)
        self.safety_mode = self.config.get("safety_mode", True)
        self.workspace_root = os.path.realpath(self.config.get("workspace_root") or self.cwd)
        self.allow_destructive_outside_workspace = bool(
            self.config.get("allow_destructive_outside_workspace", False)
        )

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """
        Execute a bash command
        
        :param args: Dictionary containing the command and optional timeout
        :return: Command output or error
        """
        command = args.get("command", "").strip()
        timeout = args.get("timeout", self.default_timeout)

        if not command:
            return ToolResult.fail("Error: command parameter is required")

        if self._IS_WIN and self._looks_like_powershell_file_write(command):
            return ToolResult.fail(
                "Encoding safety guard: do not write or append text files through PowerShell "
                "Add-Content/Set-Content/Out-File from the bash tool. On Windows this can corrupt "
                "UTF-8 Chinese text. Use the write tool for full-file writes or the edit tool with "
                "oldText=\"\" for UTF-8 append instead. Keep each content chunk small."
            )

        # Security check: Prevent accessing sensitive config files
        if "~/.cow/.env" in command or "~/.cow" in command:
            return ToolResult.fail(
                "Error: Access denied. API keys and credentials must be accessed through the env_config tool only."
            )

        # Optional safety check - only warn about extremely dangerous commands
        if self.safety_mode:
            warning = self._get_safety_warning(command)
            if warning:
                return ToolResult.fail(
                    f"Safety Warning: {warning}\n\nIf you believe this command is safe and necessary, please ask the user for confirmation first, explaining what the command does and why it's needed.")

        try:
            # Prepare environment with .env file variables
            env = os.environ.copy()
            
            # Load environment variables from ~/.cow/.env if it exists
            env_file = expand_path("~/.cow/.env")
            dotenv_vars = {}
            if os.path.exists(env_file):
                try:
                    from dotenv import dotenv_values
                    dotenv_vars = dotenv_values(env_file)
                    env.update(dotenv_vars)
                    logger.debug(f"[Bash] Loaded {len(dotenv_vars)} variables from {env_file}")
                except ImportError:
                    logger.debug("[Bash] python-dotenv not installed, skipping .env loading")
                except Exception as e:
                    logger.debug(f"[Bash] Failed to load .env: {e}")

            # getuid() only exists on Unix-like systems
            if hasattr(os, 'getuid'):
                logger.debug(f"[Bash] Process UID: {os.getuid()}")
            else:
                logger.debug(f"[Bash] Process User: {os.environ.get('USERNAME', os.environ.get('USER', 'unknown'))}")
            
            # On Windows, convert $VAR references to %VAR% for cmd.exe
            if self._IS_WIN:
                env["PYTHONIOENCODING"] = "utf-8"
                command = self._convert_env_vars_for_windows(command, dotenv_vars)
                command = self._prepare_windows_command(command)

            result = subprocess.run(
                command,
                shell=True,
                cwd=self.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
            )
            
            logger.debug(f"[Bash] Exit code: {result.returncode}")
            logger.debug(f"[Bash] Stdout length: {len(result.stdout)}")
            logger.debug(f"[Bash] Stderr length: {len(result.stderr)}")
            
            # Workaround for exit code 126 with no output
            if result.returncode == 126 and not result.stdout and not result.stderr:
                logger.warning(f"[Bash] Exit 126 with no output - trying alternative execution method")
                # Try using argument list instead of shell=True
                import shlex
                try:
                    parts = shlex.split(command)
                    if len(parts) > 0:
                        logger.info(f"[Bash] Retrying with argument list: {parts[:3]}...")
                        retry_result = subprocess.run(
                            parts,
                            cwd=self.cwd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=timeout,
                            env=env
                        )
                        logger.debug(f"[Bash] Retry exit code: {retry_result.returncode}, stdout: {len(retry_result.stdout)}, stderr: {len(retry_result.stderr)}")
                        
                        # If retry succeeded, use retry result
                        if retry_result.returncode == 0 or retry_result.stdout or retry_result.stderr:
                            result = retry_result
                        else:
                            # Both attempts failed - check if this is openai-image-vision skill
                            if 'openai-image-vision' in command or 'vision.sh' in command:
                                # Create a mock result with helpful error message
                                from types import SimpleNamespace
                                result = SimpleNamespace(
                                    returncode=1,
                                    stdout='{"error": "图片无法解析", "reason": "该图片格式可能不受支持，或图片文件存在问题", "suggestion": "请尝试其他图片"}',
                                    stderr=''
                                )
                                logger.info(f"[Bash] Converted exit 126 to user-friendly image error message for vision skill")
                except Exception as retry_err:
                    logger.warning(f"[Bash] Retry failed: {retry_err}")

            # When command succeeds with stdout, keep output clean (stderr goes to server log only).
            # When command fails or stdout is empty, include stderr so the agent can diagnose.
            if result.returncode == 0 and result.stdout.strip():
                output = result.stdout
                if result.stderr:
                    logger.info(f"[Bash] stderr (not forwarded): {result.stderr[:500]}")
            else:
                output = result.stdout
                if result.stderr:
                    output += "\n" + result.stderr

            # Check if we need to save full output to temp file
            temp_file_path = None
            total_bytes = len(output.encode('utf-8'))

            if total_bytes > DEFAULT_MAX_BYTES:
                # Save full output to temp file
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log', prefix='bash-') as f:
                    f.write(output)
                    temp_file_path = f.name

            # Apply tail truncation
            truncation = truncate_tail(output)
            output_text = truncation.content or "(no output)"

            # Build result
            details = {}

            if truncation.truncated:
                details["truncation"] = truncation.to_dict()
                if temp_file_path:
                    details["full_output_path"] = temp_file_path

                # Build notice
                start_line = truncation.total_lines - truncation.output_lines + 1
                end_line = truncation.total_lines

                if truncation.last_line_partial:
                    # Edge case: last line alone > 30KB
                    last_line = output.split('\n')[-1] if output else ""
                    last_line_size = format_size(len(last_line.encode('utf-8')))
                    output_text += f"\n\n[Showing last {format_size(truncation.output_bytes)} of line {end_line} (line is {last_line_size}). Full output: {temp_file_path}]"
                elif truncation.truncated_by == "lines":
                    output_text += f"\n\n[Showing lines {start_line}-{end_line} of {truncation.total_lines}. Full output: {temp_file_path}]"
                else:
                    output_text += f"\n\n[Showing lines {start_line}-{end_line} of {truncation.total_lines} ({format_size(DEFAULT_MAX_BYTES)} limit). Full output: {temp_file_path}]"

            # Check exit code
            if result.returncode != 0:
                output_text += f"\n\nCommand exited with code {result.returncode}"
                return ToolResult.fail({
                    "output": output_text,
                    "exit_code": result.returncode,
                    "details": details if details else None
                })

            return ToolResult.success({
                "output": output_text,
                "exit_code": result.returncode,
                "details": details if details else None
            })

        except subprocess.TimeoutExpired:
            return ToolResult.fail(f"Error: Command timed out after {timeout} seconds")
        except Exception as e:
            return ToolResult.fail(f"Error executing command: {str(e)}")

    def _get_safety_warning(self, command: str) -> str:
        """
        Get safety warning for absolutely catastrophic commands only.
        Keep the blocklist minimal so the agent retains maximum freedom.

        :param command: Command to check
        :return: Warning message if dangerous, empty string if safe
        """
        # Tokenize to avoid substring false positives (e.g. `rm -rf /tmp/x`
        # must not match `rm -rf /`).
        tokens = command.lower().split()

        # `rm -rf /` or `rm -rf /*` targeting the real root.
        for i, tok in enumerate(tokens):
            if tok != "rm":
                continue
            has_rf = False
            for j in range(i + 1, len(tokens)):
                t = tokens[j]
                if t.startswith("-") and "r" in t and "f" in t:
                    has_rf = True
                elif t in ("--recursive", "--force"):
                    continue
                elif t in ("/", "/*"):
                    if has_rf:
                        return "This command will delete the entire filesystem"
                    break
                else:
                    break

        # Disk wiping
        if "if=/dev/zero" in command.lower() and "dd " in command.lower():
            return "This command can destroy disk data"

        remote_script_warning = self._remote_script_warning(command)
        if remote_script_warning:
            return remote_script_warning

        destructive_warning = self._destructive_path_warning(command)
        if destructive_warning:
            return destructive_warning

        # Power control - match only as a standalone word (\b enforces word boundary)
        if re.search(r'\b(shutdown|reboot|halt|poweroff)\b', command.lower()):
            return "This command will shut down or restart the system"

        return ""

    def _remote_script_warning(self, command: str) -> str:
        lowered = command.lower()
        if re.search(r'\b(curl|wget)\b.+\|\s*(sh|bash|zsh|python|python3|pwsh|powershell)\b', lowered):
            return "This command downloads and executes a remote script"
        if re.search(r'\b(iwr|irm|invoke-webrequest|invoke-restmethod)\b', lowered) and re.search(
            r'\b(iex|invoke-expression)\b', lowered
        ):
            return "This command downloads and executes a remote PowerShell script"
        if "downloadstring" in lowered and re.search(r'\b(iex|invoke-expression)\b', lowered):
            return "This command executes downloaded PowerShell content"
        return ""

    def _destructive_path_warning(self, command: str) -> str:
        if self.allow_destructive_outside_workspace:
            return ""

        destructive_verbs = {"rm", "del", "erase", "rmdir", "rd", "remove-item"}
        tokens = self._rough_tokens(command)
        for index, token in enumerate(tokens):
            verb = token.lower()
            if verb not in destructive_verbs:
                continue
            candidates = tokens[index + 1:]
            if verb == "remove-item":
                candidates = self._powershell_remove_item_targets(candidates)
            for candidate in candidates:
                clean = self._clean_path_token(candidate)
                if not clean or clean.startswith("-") or clean in {"/s", "/q"}:
                    continue
                if self._looks_like_shell_operator(clean):
                    break
                if os.path.isabs(clean):
                    real = os.path.realpath(clean)
                    if not self._is_within_workspace(real):
                        return (
                            "Destructive command targets an absolute path outside the workspace: "
                            f"{clean}"
                        )
        return ""

    @staticmethod
    def _rough_tokens(command: str) -> list:
        import shlex
        try:
            return shlex.split(command, posix=(os.name != "nt"))
        except ValueError:
            return command.split()

    @staticmethod
    def _powershell_remove_item_targets(tokens: list) -> list:
        result = []
        skip_next = False
        path_flags = {"-path", "-literalpath"}
        for idx, token in enumerate(tokens):
            lowered = token.lower()
            if skip_next:
                result.append(token)
                skip_next = False
                continue
            if lowered in path_flags and idx + 1 < len(tokens):
                skip_next = True
            elif not lowered.startswith("-"):
                result.append(token)
        return result

    @staticmethod
    def _clean_path_token(token: str) -> str:
        return token.strip().strip("'\"")

    @staticmethod
    def _looks_like_shell_operator(token: str) -> bool:
        return token in {"&&", "||", "|", ";", ">", ">>", "<"}

    def _is_within_workspace(self, path: str) -> bool:
        try:
            return os.path.commonpath([self.workspace_root, path]) == self.workspace_root
        except ValueError:
            return False

    @staticmethod
    def _looks_like_powershell_file_write(command: str) -> bool:
        lowered = command.lower()
        if "powershell" not in lowered and "pwsh" not in lowered:
            return False
        risky_cmdlets = ("add-content", "set-content", "out-file")
        if any(cmdlet in lowered for cmdlet in risky_cmdlets):
            return True
        return bool(re.search(r">\s*['\"]?[a-z]:\\", lowered))

    @classmethod
    def _prepare_windows_command(cls, command: str) -> str:
        """
        Prepare Windows commands for stable UTF-8 output.

        The bash tool is backed by cmd.exe on Windows. For normal cmd commands we
        switch the code page to UTF-8. For explicit PowerShell invocations we also
        force PowerShell's output pipeline encoding and use -EncodedCommand to avoid
        quote/locale corruption before subprocess sees the command.
        """
        stripped = (command or "").strip()
        if not stripped or stripped.lower().startswith("chcp"):
            return stripped

        powershell = cls._parse_powershell_invocation(stripped)
        if powershell:
            exe, script = powershell
            prelude = (
                "try{[Console]::InputEncoding=[System.Text.UTF8Encoding]::new($false)}catch{};"
                "$OutputEncoding=[System.Text.UTF8Encoding]::new($false);"
            )
            encoded = base64.b64encode(f"{prelude}\n{script}".encode("utf-16le")).decode("ascii")
            return f"chcp 65001 >nul 2>&1 && {exe} -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}"

        return f"chcp 65001 >nul 2>&1 && {stripped}"

    @classmethod
    def _parse_powershell_invocation(cls, command: str) -> tuple[str, str] | None:
        tokens = cls._rough_tokens(command)
        if not tokens:
            return None
        exe = tokens[0].strip("'\"")
        if not re.fullmatch(r"(?i)(?:powershell|powershell\.exe|pwsh|pwsh\.exe)", exe):
            return None

        for idx, token in enumerate(tokens[1:], start=1):
            lowered = token.lower()
            if lowered in {"-command", "-c", "/command", "/c"} and idx + 1 < len(tokens):
                script = " ".join(tokens[idx + 1:]).strip()
                return exe, cls._strip_outer_quotes(script)

        # Treat the remaining tokens as the script only when the invocation did
        # not consist solely of switches (for example, not `powershell -File x.ps1`).
        remaining = [token for token in tokens[1:] if token and not token.startswith("-")]
        if remaining:
            return exe, cls._strip_outer_quotes(" ".join(tokens[1:]).strip())
        return None

    @staticmethod
    def _strip_outer_quotes(value: str) -> str:
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            return value[1:-1]
        return value

    @staticmethod
    def _convert_env_vars_for_windows(command: str, dotenv_vars: dict) -> str:
        """
        Convert bash-style $VAR / ${VAR} references to cmd.exe %VAR% syntax.
        Only converts variables loaded from .env (user-configured API keys etc.)
        to avoid breaking $PATH, jq expressions, regex, etc.
        """
        if not dotenv_vars:
            return command

        def replace_match(m):
            var_name = m.group(1) or m.group(2)
            if var_name in dotenv_vars:
                return f"%{var_name}%"
            return m.group(0)

        return re.sub(r'\$\{(\w+)\}|\$(\w+)', replace_match, command)
