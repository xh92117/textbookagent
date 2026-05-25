import os
from dataclasses import dataclass
from pathlib import PurePosixPath

from config import conf


class UploadLimitError(ValueError):
    pass


@dataclass(frozen=True)
class UploadLimits:
    max_file_bytes: int
    max_files: int
    max_dir_depth: int
    allowed_extensions: set


def get_upload_limits(prefix: str = "web_upload") -> UploadLimits:
    max_file_mb = int(conf().get(f"{prefix}_max_file_mb", 100) or 100)
    max_files = int(conf().get(f"{prefix}_max_files", 500) or 500)
    max_dir_depth = int(conf().get(f"{prefix}_max_dir_depth", 12) or 12)
    raw_exts = conf().get(f"{prefix}_allowed_extensions", []) or []
    if isinstance(raw_exts, str):
        raw_exts = [part.strip() for part in raw_exts.split(",") if part.strip()]
    allowed = {
        ext.lower() if str(ext).startswith(".") else f".{str(ext).lower()}"
        for ext in raw_exts
    }
    return UploadLimits(
        max_file_bytes=max(1, max_file_mb) * 1024 * 1024,
        max_files=max(1, max_files),
        max_dir_depth=max(1, max_dir_depth),
        allowed_extensions=allowed,
    )


def validate_file_upload(filename: str, content_size: int, limits: UploadLimits) -> None:
    ext = os.path.splitext(str(filename or ""))[1].lower()
    if limits.allowed_extensions and ext not in limits.allowed_extensions:
        raise UploadLimitError(f"File type is not allowed: {ext or '(none)'}")
    if content_size > limits.max_file_bytes:
        limit_mb = limits.max_file_bytes // (1024 * 1024)
        raise UploadLimitError(f"File is too large; maximum size is {limit_mb} MB")


def validate_directory_upload(rel_paths, limits: UploadLimits) -> None:
    rel_paths = list(rel_paths or [])
    if len(rel_paths) > limits.max_files:
        raise UploadLimitError(f"Too many files; maximum count is {limits.max_files}")
    for rel_path in rel_paths:
        normalized = str(rel_path or "").replace("\\", "/").strip("/")
        parts = PurePosixPath(normalized).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise UploadLimitError("Invalid directory upload path")
        if len(parts) > limits.max_dir_depth:
            raise UploadLimitError(f"Directory upload is too deep; maximum depth is {limits.max_dir_depth}")
        validate_file_upload(parts[-1], 0, limits)
