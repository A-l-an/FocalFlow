"""Initial, injectable failure limits and content-free errors for the live path."""
import math
import threading
import time
from dataclasses import dataclass


class OperationError(RuntimeError):
    def __init__(self, stage, code, status=None):
        self.stage, self.code, self.status = stage, code, status
        super().__init__('%s:%s%s' % (stage, code, '' if status is None else ':%d' % status))


class DeadlineExceeded(OperationError):
    def __init__(self):
        super().__init__('request', 'DEADLINE_EXCEEDED')


@dataclass(frozen=True)
class FailurePolicy:
    attempts: int = 1
    connect: float = 5.0
    read: float = 30.0
    request: float = 120.0
    adb: float = 10.0
    write: float = 5.0
    frame: float = 30.0
    backoff: float = 0.5

    def __post_init__(self):
        if type(self.attempts) is not int or not 1 <= self.attempts <= 3:
            raise ValueError('attempts must be an integer from 1 to 3')
        for name in ('connect', 'read', 'request', 'adb', 'write', 'frame', 'backoff'):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError('invalid positive finite timeout: ' + name)


class CallBudget:
    def __init__(self, policy=None, guard=None, clock=time.monotonic, wait=None):
        self.policy = policy or FailurePolicy()
        self.guard, self.clock = guard, clock
        self.deadline = clock() + self.policy.request
        self.waiter = wait

    def check(self):
        if self.guard is not None:
            self.guard.check()
        if self.clock() >= self.deadline:
            raise DeadlineExceeded()

    def remaining(self):
        self.check()
        left = self.deadline - self.clock()
        if self.guard is not None:
            left = min(left, self.guard.remaining())
        return max(0.001, left)

    def http_timeout(self):
        left = self.remaining()
        return min(self.policy.connect, left), min(self.policy.read, left)

    def pause(self):
        delay = min(self.policy.backoff, self.remaining())
        if self.waiter is not None:
            self.waiter(delay)
        elif self.guard is not None:
            self.guard.cancelled.wait(delay)
        else:
            threading.Event().wait(delay)
        self.check()


def checked_bytes(iterator, budget, limit, stage):
    result = bytearray()
    iterator = iter(iterator)
    while True:
        budget.check()
        try:
            chunk = next(iterator)
        except StopIteration:
            break
        budget.check()
        if len(result) + len(chunk) > limit:
            raise OperationError(stage, 'RESPONSE_LIMIT')
        result.extend(chunk)
    budget.check()
    return bytes(result)
