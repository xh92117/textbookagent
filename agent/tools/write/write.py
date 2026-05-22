"""
Write tool - Write file content
Creates or overwrites files, automatically creates parent directories
"""

import os
from typing import Dict, Any
from pathlib import Path

from agent.tools.base_tool import BaseTool, ToolResult
from common.utils import expand_path


class Write(BaseTool):
    """Tool for writing file content"""
    
    name: str = "write"
    description: str = "Write UTF-8 content to a file. Creates the file if it doesn't exist, overwrites if it does. Automatically creates parent directories. IMPORTANT: Single write should not exceed 10KB/6000 Chinese chars. For large files, create a skeleton first, then use edit with oldText=\"\" to append small UTF-8 chunks. Do not use bash/PowerShell to write Chinese text files."
    
    params: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to write (relative or absolute)"
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file"
            }
        },
        "required": ["path", "content"]
    }
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd", os.getcwd())
        self.memory_manager = self.config.get("memory_manager", None)
    
    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """
        Execute file write operation
        
        :param args: Contains file path and content
        :return: Operation result
        """
        path = args.get("path", "").strip()
        content = args.get("content", "")
        
        if not path:
            return ToolResult.fail("Error: path parameter is required")
        
        # Resolve path
        try:
            absolute_path = self._resolve_path(path)
        except ValueError as e:
            return ToolResult.fail(f"Error: {str(e)}")
        
        try:
            # Create parent directory (if needed)
            parent_dir = os.path.dirname(absolute_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            
            # Write file
            with open(absolute_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Get bytes written
            bytes_written = len(content.encode('utf-8'))
            
            # Auto-sync to memory database if this is a memory file
            if self.memory_manager and self._is_memory_path(path):
                self.memory_manager.mark_dirty()
            
            result = {
                "message": f"Successfully wrote {bytes_written} bytes to {path}",
                "path": path,
                "bytes_written": bytes_written
            }
            
            return ToolResult.success(result)
            
        except PermissionError:
            return ToolResult.fail(f"Error: Permission denied writing to {path}")
        except Exception as e:
            return ToolResult.fail(f"Error writing file: {str(e)}")
    
    def _resolve_path(self, path: str) -> str:
        """
        Resolve path to absolute path
        
        :param path: Relative or absolute path
        :return: Absolute path
        """
        # Expand ~ to user home directory
        path = expand_path(path)
        if os.path.isabs(path):
            return path
        if self.memory_manager and self._is_memory_path(path):
            return str(self._memory_file_path(path))
        return os.path.abspath(os.path.join(self.cwd, path))

    @staticmethod
    def _is_memory_path(path: str) -> bool:
        normalized = path.replace("\\", "/").lstrip("./")
        return normalized == "MEMORY.md" or normalized.startswith("memory/")

    def _memory_file_path(self, path: str) -> Path:
        normalized = path.replace("\\", "/").lstrip("./")
        if normalized == "MEMORY.md":
            relative = "MEMORY.md"
        else:
            relative = normalized[len("memory/"):]
        if not relative or any(part in ("", ".", "..") for part in Path(relative).parts):
            raise ValueError("Invalid memory path")
        memory_dir = self.memory_manager.config.get_memory_dir()
        return memory_dir / relative
