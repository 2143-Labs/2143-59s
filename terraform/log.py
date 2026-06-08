"""Shared logging for deploy scripts.

Replaces the old pulumi.log.info/warn/error calls with simple
timestamp-prefixed stdout output.
"""

import time


def _log(level: str, msg: str):
    t = time.strftime("%H:%M:%S")
    print(f"[{t}] [{level}] {msg}", flush=True)


def info(msg, *args, **kwargs):
    _log("INFO", msg)


def warn(msg, *args, **kwargs):
    _log("WARN", msg)


def error(msg, *args, **kwargs):
    _log("ERROR", msg)
