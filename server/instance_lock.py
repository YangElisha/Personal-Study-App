"""One process at a time may own DATA_DIR: the server, the import CLI or the restore CLI.

An OS byte-range lock on DATA_DIR\\drill-server.lock. The OS releases it when the process
ends, even after a crash, so a stale lock file never blocks anything.
"""
from __future__ import annotations

import os
from pathlib import Path


class AlreadyRunning(Exception):
    pass


class InstanceLock:
    def __init__(self, path: Path, owner: str):
        self.path = path
        self.owner = owner
        self._fh = None

    def acquire(self) -> "InstanceLock":
        fh = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            raise AlreadyRunning(
                f"Another MonoSpace process (probably the server) is using {self.path.parent}. "
                "Stop it first (close its window or press Ctrl+C).") from None
        self._fh = fh
        return self

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self._fh.seek(0)
                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
