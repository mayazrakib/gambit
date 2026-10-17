import os
from contextlib import contextmanager
from threading import Event

if os.name == "nt":
    import msvcrt
else:
    import fcntl

@contextmanager
def acquire_file_lock(
    stream,
    cancel_event: Event | None = None,
):
    if os.name == "nt":
        stream.seek(0,)

        if stream.read(1,) == b"":
            stream.write(b"\0",)
            stream.flush()

        stream.seek(0,)

        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("The file lock wait was cancelled.",)

            try:
                msvcrt.locking(
                    stream.fileno(),
                    msvcrt.LK_NBLCK if cancel_event is not None else msvcrt.LK_LOCK,
                    1,
                )

                break
            except OSError:
                if cancel_event is None:
                    raise

                cancel_event.wait(0.05,)
    else:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("The file lock wait was cancelled.",)

            try:
                fcntl.flock(
                    stream,
                    fcntl.LOCK_EX | (fcntl.LOCK_NB if cancel_event is not None else 0),
                )

                break
            except BlockingIOError:
                cancel_event.wait(0.05,)

    try:
        yield
    finally:
        if os.name == "nt":
            stream.seek(0,)

            msvcrt.locking(
                stream.fileno(),
                msvcrt.LK_UNLCK,
                1,
            )
        else:
            fcntl.flock(
                stream,
                fcntl.LOCK_UN,
            )
