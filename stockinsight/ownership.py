"""One foreground scheduler per workspace; the OS releases ownership on process exit."""

import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def scheduler(path):
    with (Path(path).parent / ".scheduler.lock").open("a+b") as lock:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b"1")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError(
                "This workspace already has a running scheduler. Stop it before handover."
            ) from None
        yield
