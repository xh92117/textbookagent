import subprocess
import sys
import time

from common.log import _reset_logger, logger


def install(package):
    logger.info(f"Installing package into current Python environment: {sys.executable}")
    subprocess.run([sys.executable, "-m", "pip", "install", package], check=True)


def install_requirements(file):
    logger.info(f"Installing requirements into current Python environment: {sys.executable}")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", file, "--upgrade"], check=True)
    _reset_logger(logger)


def check_dulwich():
    needwait = False
    for i in range(2):
        if needwait:
            time.sleep(3)
            needwait = False
        try:
            import dulwich

            return
        except ImportError:
            try:
                install("dulwich")
            except Exception:
                needwait = True
    try:
        import dulwich
    except ImportError:
        raise ImportError("Unable to import dulwich")
