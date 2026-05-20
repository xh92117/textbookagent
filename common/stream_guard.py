# encoding:utf-8

import queue
import threading
import time
from typing import Iterable


def iter_with_idle_guard(
    stream: Iterable,
    idle_timeout: float = 30,
    first_chunk_timeout: float = 180,
    logger=None,
    label: str = "LLM stream",
):
    """
    Yield items from a blocking stream without waiting forever for a missing
    terminal frame after useful deltas have already arrived.
    """
    events = queue.Queue()
    stop_event = threading.Event()

    def _pump():
        try:
            for item in stream:
                if stop_event.is_set():
                    break
                events.put(("chunk", item))
        except BaseException as exc:
            events.put(("error", exc))
        finally:
            events.put(("done", None))

    worker = threading.Thread(target=_pump, name="llm-stream-guard-pump", daemon=True)
    worker.start()

    start_time = time.time()
    last_chunk_time = start_time
    yielded_any = False
    idle_timeout = max(1.0, float(idle_timeout or 30))
    first_chunk_timeout = max(2.0, float(first_chunk_timeout or 180))

    def _request_stop(reason: str):
        if logger:
            logger.warning(f"[StreamGuard] {label} closing stream: {reason}")
        stop_event.set()
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:
                if logger:
                    logger.debug(f"[StreamGuard] {label} close skipped: {exc}")

    while True:
        try:
            kind, payload = events.get(timeout=1.0)
        except queue.Empty:
            now = time.time()
            if yielded_any and now - last_chunk_time >= idle_timeout:
                _request_stop(f"idle {int(now - last_chunk_time)}s after receiving deltas")
                break
            if not yielded_any and now - start_time >= first_chunk_timeout:
                _request_stop(f"no first chunk after {int(now - start_time)}s")
                raise TimeoutError(
                    f"{label} did not produce the first chunk within {int(first_chunk_timeout)}s"
                )
            continue

        if kind == "chunk":
            yielded_any = True
            last_chunk_time = time.time()
            yield payload
        elif kind == "error":
            raise payload
        elif kind == "done":
            break
