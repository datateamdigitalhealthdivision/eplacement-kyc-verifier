"""Tiny cross-platform lock file helper for cache writes."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def file_lock(lock_path: str | Path, timeout_seconds: float = 10.0, poll_interval: float = 0.1) -> Iterator[None]:
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout_seconds
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            break
        except FileExistsError:
            if time.time() >= deadline:
                raise TimeoutError(f"Unable to acquire lock {path}")
            time.sleep(poll_interval)
    try:
        yield
    finally:
        os.close(fd)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
