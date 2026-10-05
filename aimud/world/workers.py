"""
The threads slow work runs on, kept apart so one kind cannot starve another.

Everything that waits used to share Twisted's one thread pool: ten threads,
first come first served. Model calls, memory writes, memory recalls and
service calls all queued in it together. A busy world wrote a memory for
every character who saw every event, each write waited on a lock for a third
of a second while holding a thread, and a model call queued behind the lot
-- twice for a two-round answer. A two-round reply that takes six seconds on
its own was measured at 172 on the live server.

So there are pools, each sized for what it does:

* **model** -- model calls, and whatever else goes through `llm.fetch`. These
  spend nearly all their time waiting on the network, so threads are cheap
  and there are many: `MODEL_CALL_THREADS`.
* **memory** -- writing memories, in the background. Each world's writes are
  drained in order by one worker at a time (`world.memory`), so this only
  needs as many threads as worlds busy at once: `MEMORY_THREADS`.

Asset downloads and anything else still on `deferToThread` use Twisted's own
pool, which nothing here crowds any more.

A pool is made the first time it is asked for, and stopped when the reactor
shuts down: a pool left running holds the process open.
"""

import threading
import time

from django.conf import settings
from twisted.internet import reactor, threads
from twisted.python.threadpool import ThreadPool

#: Defaults, when settings say nothing.
SIZES = {"model": 16, "memory": 4}
SETTINGS = {"model": "MODEL_CALL_THREADS", "memory": "MEMORY_THREADS"}

_pools = {}
_making = threading.Lock()


def _daemon_thread(*args, **kwargs):
    """
    A worker that never holds the process open.

    The pools are stopped when the reactor shuts down, which lets running
    work finish. But a process with no reactor -- a test run, `evennia
    shell` -- never shuts one down, and a pool of ordinary threads kept it
    alive after its last line, waiting for ever. Found when the test suite
    finished and did not exit.
    """
    thread = threading.Thread(*args, **kwargs)
    thread.daemon = True
    return thread


class _Pool(ThreadPool):
    threadFactory = staticmethod(_daemon_thread)


def size_of(name):
    found = getattr(settings, SETTINGS[name], None)
    try:
        return max(1, int(found)) if found is not None else SIZES[name]
    except (TypeError, ValueError):
        return SIZES[name]


def pool(name):
    """The named pool, made and started on first use."""
    with _making:
        found = _pools.get(name)
        if found is None:
            found = _Pool(minthreads=0, maxthreads=size_of(name),
                          name=f"aimud-{name}")
            found.start()
            reactor.addSystemEventTrigger("during", "shutdown", found.stop)
            _pools[name] = found
        return found


def defer(name, work, *args, **kwargs):
    """Run `work` on the named pool; a Deferred fires with what it returns."""
    return threads.deferToThreadPool(reactor, pool(name), work, *args, **kwargs)


def timed(work, on_waited):
    """
    `work`, wrapped to report how long it queued before a thread took it.

    `on_waited(seconds)` is called in the worker thread, before the work
    starts, so the wait is known even when the work then fails.
    """
    queued = time.monotonic()

    def run(*args, **kwargs):
        on_waited(time.monotonic() - queued)
        return work(*args, **kwargs)

    return run


def waiting(name):
    """How many jobs are queued on the named pool and not yet started."""
    found = _pools.get(name)
    if found is None:
        return 0
    try:
        return int(found._team.statistics().backloggedWorkCount)
    except AttributeError:
        return 0
