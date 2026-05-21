import logging

from common.log import configure_logging, get_log_path


def test_logging_uses_configurable_rotating_file(tmp_path):
    log_dir = tmp_path / "logs"
    try:
        configure_logging({
            "log_dir": str(log_dir),
            "log_file": "app.log",
            "log_max_bytes": 1024,
            "log_backup_count": 2,
        })
        logging.getLogger("log").info("hello configurable log")

        log_path = get_log_path()
        assert log_path.endswith("app.log")
        assert (log_dir / "app.log").is_file()
    finally:
        configure_logging({"log_dir": "logs", "log_file": "run.log"})
