"""workers.tools package exports commonly used helpers.

This file keeps imports lazy to avoid heavy startup cost in workers.
Only export names that are used across the codebase.
"""
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # For type checkers only
    from .telegram_helper import send_message, send_photo  # noqa: F401
    from .x_helper import post_tweet  # noqa: F401


def _lazy(name: str):
    mod_name, obj_name = name.rsplit('.', 1)
    mod = import_module(mod_name)
    return getattr(mod, obj_name)


def __getattr__(name: str):
    if name == 'send_message':
        return _lazy('workers.tools.telegram_helper.send_message')
    if name == 'send_photo':
        return _lazy('workers.tools.telegram_helper.send_photo')
    if name == 'post_tweet':
        return _lazy('workers.tools.x_helper.post_tweet')
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ['send_message', 'send_photo', 'post_tweet']
