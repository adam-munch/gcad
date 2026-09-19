"""Thread-scoped operation events; workers never touch Tk widgets."""
from contextlib import contextmanager
from contextvars import ContextVar


_listener = ContextVar('gcad_progress', default=None)


def is_reporting():
    return _listener.get() is not None


@contextmanager
def operation_progress(listener):
    token = _listener.set(listener)
    try:
        yield
    finally:
        _listener.reset(token)


def report(message, completed=None, total=None, level='info'):
    listener = _listener.get()
    if listener:
        listener(message, completed, total, level)
