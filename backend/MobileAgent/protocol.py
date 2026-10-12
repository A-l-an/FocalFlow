"""Protocol v1 context and cancellation primitives (no threads or IO on import)."""
import json
import re
import threading
from contextlib import contextmanager
from MobileAgent.failure import DeadlineExceeded
from MobileAgent.validation import require, bounded_json, tree_index, MAX_TREE_BYTES

VERSION = 1
MAX_MESSAGE_BYTES = MAX_TREE_BYTES + 65536
MAX_COUNTER = 9007199254740991
_UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z')
_ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')


def context(value):
    require(isinstance(value, dict) and set(value) == {'sessionId', 'taskEpoch', 'snapshotSeq'}, 'invalid context')
    require(isinstance(value['sessionId'], str) and _UUID.fullmatch(value['sessionId']), 'invalid session')
    for key in ('taskEpoch', 'snapshotSeq'):
        require(type(value[key]) is int and 0 <= value[key] <= MAX_COUNTER, 'invalid counter')
    return dict(value)


def header(obj):
    require(isinstance(obj, dict) and type(obj.get('protocolVersion')) is int and obj['protocolVersion'] == VERSION, 'invalid protocol')
    ctx = context(obj.get('context'))
    request_id = obj.get('requestId')
    require(isinstance(request_id, str) and _ID.fullmatch(request_id), 'invalid request ID')
    return ctx, request_id


def envelope(ctx, tree):
    return {'protocolVersion': VERSION, 'context': context(ctx), 'tree': tree}


def read_snapshot(path, expected):
    with open(path, 'rb') as stream:
        raw = stream.read(MAX_MESSAGE_BYTES + 1)
    require(len(raw) <= MAX_MESSAGE_BYTES, 'snapshot size limit')
    obj = bounded_json(raw.decode('utf-8'), MAX_MESSAGE_BYTES)
    require(isinstance(obj, dict) and set(obj) == {'protocolVersion', 'context', 'tree'}, 'invalid snapshot envelope')
    require(type(obj['protocolVersion']) is int and obj['protocolVersion'] == VERSION, 'invalid protocol')
    require(context(obj['context']) == context(expected), 'snapshot context mismatch')
    tree_index(obj['tree'])
    return obj['tree']


class Cancelled(RuntimeError):
    pass


class Work:
    def __init__(self, owner, obj, connection, role):
        self.owner, self.obj, self.connection, self.role = owner, obj, connection, role
        self.context, self.request_id = header(obj)
        self.cancelled = threading.Event()
        self.done = threading.Event()
        self.stoppers = []
        self.deadline = owner.clock() + owner.policy.request
        self.expired = False
        self.error_sent = False
        self.response = None
        self.terminal_sent = False

    def check(self):
        with self.owner._condition:
            if self.owner._active is not self or self.owner._connection is not self.connection:
                raise Cancelled('request invalidated')
            if self.expired:
                raise DeadlineExceeded()
            if self.cancelled.is_set():
                raise Cancelled('request invalidated')
            if self.owner.clock() >= self.deadline:
                self.expired = True
                self.cancel()
                raise DeadlineExceeded()

    def remaining(self):
        self.check()
        return max(0.001, self.deadline - self.owner.clock())

    def run(self, action):
        """Atomic state boundary; action must be internal metadata only, never external IO."""
        with self.owner._condition:
            self.check()
            return action()

    @contextmanager
    def own(self, create, start, abort, close, *, drain=None):
        # Reserve before creation. Only the cleanup lane ever closes this resource.
        with self.owner._condition:
            self.check()
            require(len(self.owner._audio_leases) < 4, 'owned audio capacity exhausted')
            lease = OwnedAudio(self, abort, close)
            self.stoppers.append(lease)
            self.owner._audio_leases.add(lease)
            self.owner._start_audio_cleanup()
        try:
            self.check()
            resource = create()
            with self.owner._condition:
                lease.resource = resource
            self.check()
            lease.start_attempted = True
            start(resource)  # Empty stream; no samples yet, and no control lock.
            lease.ready.set()
            self.check()
            yield resource
            if drain is not None:
                self.check()
                drain(resource)  # Opaque native call: cancellation is observed after it returns.
                self.check()
        except BaseException:
            lease.failed = True
            raise
        finally:
            # The worker has finished all start/read/write/drain operations. Cleanup may
            # now serially abort if cancelled, then close; it never overlaps these calls. Waiting owns no control lock.
            lease.ready.set()
            lease.finalized.set()
            with self.owner._condition:
                self._queue_cleanup(lease)
            lease.completed.wait()
            if lease.error is not None:
                raise RuntimeError('owned audio cleanup failed') from None

    def _queue_cleanup(self, lease):
        if not lease.queued:
            lease.queued = True
            self.owner._audio_pending.append(lease)
        self.owner._condition.notify_all()

    def _release_lease(self, lease):
        # A failed close retains capacity/ownership rather than risking a second
        # native close or accumulating unknown live handles without a bound.
        if lease.closed:
            self.owner._audio_leases.discard(lease)
            if lease in self.stoppers:
                self.stoppers.remove(lease)
        self.owner._condition.notify_all()

    def cancel(self):
        with self.owner._condition:
            self.cancelled.set()
            for lease in self.stoppers:
                self._queue_cleanup(lease)


class OwnedAudio:
    """One resource; abort then exactly one close belong only to the cleanup lane."""
    def __init__(self, work, abort, close):
        self.work, self.abort, self.close = work, abort, close
        self.resource = None
        self.ready = threading.Event()
        self.finalized = threading.Event()
        self.completed = threading.Event()
        self.start_attempted = False
        self.failed = False
        self.closed = False
        self.queued = False
        self.error = None
