"""An overall time limit shared by every GitHub request in one run."""

import math
import time

DEFAULT_CLI_TIME_LIMIT = 30 * 60
DEFAULT_WEB_TIME_LIMIT = 5 * 60


class DeadlineExceeded(Exception):
    """The run's overall time limit was reached.

    This is deliberately not a requests exception, so it is never mistaken for
    a single request timing out.
    """


def _now():
    return time.monotonic()


def parse_time_limit(text):
    """Parse a positive, finite number of seconds."""
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"Time limit must be a positive number of seconds, not {text!r}.")
    return value


class Deadline:
    def __init__(self, seconds, clock=None):
        self.seconds = parse_time_limit(seconds)
        self._clock = clock
        self._end = self._time() + self.seconds

    def _time(self):
        return (self._clock or _now)()

    def remaining(self):
        return self._end - self._time()

    def expired(self):
        return self.remaining() <= 0

    def error(self, context):
        return DeadlineExceeded(
            f"Overall time limit of {self.seconds:g} seconds reached {context}."
        )
