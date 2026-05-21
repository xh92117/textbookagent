import logging
import os
import sys
from logging.handlers import RotatingFileHandler


_LOG_PATH = None


class _FlushingStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        try:
            self.flush()
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _log_settings(config=None):
    config = config or {}
    log_dir = (
        config.get("log_dir")
        or os.environ.get("TEXTBOOKAGENT_LOG_DIR")
        or "logs"
    )
    log_file = (
        config.get("log_file")
        or os.environ.get("TEXTBOOKAGENT_LOG_FILE")
        or "run.log"
    )
    max_bytes = _coerce_int(
        config.get("log_max_bytes") or os.environ.get("TEXTBOOKAGENT_LOG_MAX_BYTES"),
        5 * 1024 * 1024,
    )
    backup_count = _coerce_int(
        config.get("log_backup_count") or os.environ.get("TEXTBOOKAGENT_LOG_BACKUP_COUNT"),
        5,
    )
    return log_dir, log_file, max_bytes, backup_count


def get_log_path():
    return _LOG_PATH or os.path.abspath(os.path.join("logs", "run.log"))


def _reset_logger(log, config=None):
    global _LOG_PATH
    for handler in log.handlers:
        handler.close()
        log.removeHandler(handler)
        del handler
    log.handlers.clear()
    log.propagate = False

    stdout = sys.stdout
    if hasattr(stdout, "reconfigure"):
        try:
            stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass

    formatter = logging.Formatter(
        "[%(levelname)s][%(asctime)s][%(filename)s:%(lineno)d] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handle = _FlushingStreamHandler(stdout)
    console_handle.setFormatter(formatter)

    log_dir, log_file, max_bytes, backup_count = _log_settings(config)
    os.makedirs(log_dir, exist_ok=True)
    _LOG_PATH = os.path.abspath(os.path.join(log_dir, log_file))
    file_handle = RotatingFileHandler(
        _LOG_PATH,
        maxBytes=max(1024 * 1024, max_bytes),
        backupCount=max(1, backup_count),
        encoding="utf-8",
    )
    file_handle.setFormatter(formatter)

    log.addHandler(file_handle)
    log.addHandler(console_handle)


def _get_logger(config=None):
    log = logging.getLogger("log")
    _reset_logger(log, config)
    log.setLevel(logging.INFO)
    return log


def configure_logging(config=None):
    """Reconfigure file logging after config.json has been loaded."""
    log = logging.getLogger("log")
    _reset_logger(log, config)
    return log


# Shared application logger.
logger = _get_logger()
