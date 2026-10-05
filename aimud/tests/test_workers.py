"""
Model calls in parallel, and memory per world. world/workers.py, world/memory.py.

A busy world used to back up because everything slow shared one pool of ten
threads and every memory in the game shared one lock. These hold the parts
that fixed it: model calls have a pool of their own, each world's memory has
a lock and an ordered queue of its own, and a recall goes before a write.

Real threads where the behaviour is about threads -- a recall holding a world
while a write waits, two worlds at once -- each joined with a timeout, so a
regression fails the test rather than hanging the suite.
"""

import itertools
import threading
import time
from unittest import mock

from django.test import SimpleTestCase, override_settings, tag

from world import memory, workers

_names = itertools.count()


def world_name():
    """A bank nobody else in the run is using: the table is module-wide."""
    return f"aimud-world-test-{next(_names)}"


@tag("unit")
class ThePools(SimpleTestCase):

    def test_model_calls_go_to_their_own_pool(self):
        from world import llm

        with mock.patch.object(workers, "defer") as deferred:
            llm.fetch(lambda: None, on_success=lambda _r: None,
                      on_error=lambda _f: None)
        self.assertEqual(deferred.call_args.args[0], "model")

    @override_settings(MODEL_CALL_THREADS=24, MEMORY_THREADS=2)
    def test_each_is_sized_by_its_setting(self):
        self.assertEqual(workers.size_of("model"), 24)
        self.assertEqual(workers.size_of("memory"), 2)

    @override_settings(MODEL_CALL_THREADS="lots")
    def test_and_a_setting_that_is_not_a_number_falls_back(self):
        self.assertEqual(workers.size_of("model"), workers.SIZES["model"])

    def test_their_threads_never_hold_a_process_open(self):
        """The suite once finished and did not exit; this is why."""
        thread = workers._daemon_thread(target=lambda: None)
        self.assertTrue(thread.daemon)

    def test_a_wait_is_measured_before_the_work_starts(self):
        waited = []
        run = workers.timed(lambda: "done", waited.append)
        time.sleep(0.05)
        self.assertEqual(run(), "done")
        self.assertGreaterEqual(waited[0], 0.04)


class _Queue(SimpleTestCase):
    """`_write_later` with its drain run here, by hand, rather than pooled."""

    def setUp(self):
        super().setUp()
        self.started = []
        patcher = mock.patch.object(
            workers, "defer",
            side_effect=lambda name, work, *args: self.started.append(
                (name, work, args)) or _NoDeferred())
        patcher.start()
        self.addCleanup(patcher.stop)
        now = mock.patch("twisted.internet.reactor.callFromThread",
                         side_effect=lambda function, *args: function(*args))
        now.start()
        self.addCleanup(now.stop)
        memory._closing = False
        self.addCleanup(setattr, memory, "_closing", False)

    def drain(self):
        for _name, work, args in list(self.started):
            work(*args)
        self.started.clear()


class _NoDeferred:
    def addErrback(self, *_args):
        return self

    def addCallbacks(self, *_args):
        return self


@tag("unit")
class WritesPerWorld(_Queue):

    def test_writes_land_in_the_order_they_happened(self):
        name, done = world_name(), []
        for n in range(5):
            memory._write_later(name, lambda n=n: done.append(n))
        self.drain()
        self.assertEqual(done, [0, 1, 2, 3, 4])

    def test_one_worker_per_world_however_many_writes(self):
        name = world_name()
        for n in range(5):
            memory._write_later(name, lambda: None)
        self.assertEqual(len(self.started), 1)
        self.assertEqual(self.started[0][0], "memory")

    def test_two_worlds_each_get_a_worker(self):
        memory._write_later(world_name(), lambda: None)
        memory._write_later(world_name(), lambda: None)
        self.assertEqual(len(self.started), 2)

    def test_there_is_no_cap(self):
        """Twelve was the cap, and it dropped 891 memories in a day."""
        name, done = world_name(), []
        for n in range(500):
            memory._write_later(name, lambda n=n: done.append(n))
        self.drain()
        self.assertEqual(done, list(range(500)))

    def test_a_long_queue_is_said_in_the_log(self):
        name = world_name()
        with mock.patch.object(memory, "QUEUE_WORTH_SAYING", 3), \
                mock.patch.object(memory.logger, "log_info") as said:
            for _ in range(3):
                memory._write_later(name, lambda: None)
        self.assertIn("3 writes waiting", said.call_args.args[0])
        self.drain()

    def test_an_answer_comes_back_for_a_caller_that_wants_one(self):
        name, answers = world_name(), []
        memory._write_later(name, lambda: 42, on_done=answers.append)
        self.drain()
        self.assertEqual(answers, [42])

    def test_a_failing_write_does_not_stop_the_rest(self):
        name, done = world_name(), []
        memory._write_later(name, lambda: 1 / 0)
        memory._write_later(name, lambda: done.append("after"))
        self.drain()
        self.assertEqual(done, ["after"])

    def test_a_server_going_down_lets_waiting_writes_go(self):
        name, done = world_name(), []
        memory._write_later(name, lambda: done.append(1))
        memory._closing = True
        self.drain()
        self.assertEqual(done, [])
        memory._closing = False
        memory._write_later(name, lambda: done.append(2))
        self.assertEqual(len(self.started), 1, "a stopped world starts again")
        self.drain()
        self.assertEqual(done, [2])


@tag("unit")
class ReadsGoFirst(_Queue):
    """A recall is somebody waiting to speak; a write can wait for it."""

    def test_a_write_waits_while_a_recall_holds_the_world(self):
        name, done = world_name(), []
        memory._write_later(name, lambda: done.append("written"))
        _name, work, args = self.started.pop()

        with memory._reading(name):
            writer = threading.Thread(target=work, args=args, daemon=True)
            writer.start()
            time.sleep(0.2)
            self.assertEqual(done, [], "the write went ahead of the recall")
        writer.join(timeout=5)
        self.assertFalse(writer.is_alive())
        self.assertEqual(done, ["written"])

    def test_a_write_steps_aside_for_a_recall_that_is_only_waiting(self):
        """
        The rule itself, not just the lock: a recall says it is waiting
        before it can have the lock, and a write that could take the lock
        does not, until nobody is waiting. Mutual exclusion alone would let
        the write straight in here.
        """
        name, done = world_name(), []
        bank = memory._bank(name)
        memory._write_later(name, lambda: done.append("written"))
        _name, work, args = self.started.pop()

        with bank.queue_lock:
            bank.readers += 1
        writer = threading.Thread(target=work, args=args, daemon=True)
        writer.start()
        time.sleep(0.3)
        self.assertEqual(done, [], "the write did not step aside")
        with bank.queue_lock:
            bank.readers -= 1
        with bank.lock:
            bank.lock.notify_all()
        writer.join(timeout=5)
        self.assertEqual(done, ["written"])

    def test_a_recall_waiting_steps_in_between_writes(self):
        name, order = world_name(), []
        holding = threading.Event()
        release = threading.Event()

        def first():
            order.append("write 1")
            holding.set()
            release.wait(timeout=5)

        memory._write_later(name, first)
        memory._write_later(name, lambda: order.append("write 2"))
        _name, work, args = self.started.pop()
        writer = threading.Thread(target=work, args=args, daemon=True)
        writer.start()
        holding.wait(timeout=5)

        def recall():
            with memory._reading(name):
                order.append("recall")

        reader = threading.Thread(target=recall, daemon=True)
        reader.start()
        time.sleep(0.1)
        release.set()
        reader.join(timeout=5)
        writer.join(timeout=5)
        self.assertEqual(order, ["write 1", "recall", "write 2"])


@tag("unit")
class WorldsDoNotWaitForEachOther(SimpleTestCase):

    def test_a_recall_in_one_world_while_another_is_held(self):
        held, other = world_name(), world_name()
        holding, release, read = (threading.Event(), threading.Event(),
                                  threading.Event())

        def hold():
            with memory._bank(held).lock:
                holding.set()
                release.wait(timeout=5)

        def recall():
            with memory._reading(other):
                read.set()

        holder = threading.Thread(target=hold, daemon=True)
        holder.start()
        holding.wait(timeout=5)
        reader = threading.Thread(target=recall, daemon=True)
        reader.start()
        self.assertTrue(read.wait(timeout=2),
                        "one world's memory waited for another's")
        release.set()
        holder.join(timeout=5)

    def test_but_one_world_still_waits_for_itself(self):
        name = world_name()
        holding, release, read = (threading.Event(), threading.Event(),
                                  threading.Event())

        def hold():
            with memory._bank(name).lock:
                holding.set()
                release.wait(timeout=5)

        def recall():
            with memory._reading(name):
                read.set()

        holder = threading.Thread(target=hold, daemon=True)
        holder.start()
        holding.wait(timeout=5)
        reader = threading.Thread(target=recall, daemon=True)
        reader.start()
        self.assertFalse(read.wait(timeout=0.3))
        release.set()
        self.assertTrue(read.wait(timeout=5))
        holder.join(timeout=5)


@tag("unit")
class TheSharedEmbedder(SimpleTestCase):
    """One model for every world, used by one thread at a time."""

    def model(self):
        class Model:
            inside = 0
            most = 0

            def embed(self, texts):
                Model.inside += 1
                Model.most = max(Model.most, Model.inside)
                time.sleep(0.02)
                Model.inside -= 1
                return (len(text) for text in texts)

        return Model()

    def guard(self, model):
        with mock.patch("mnemosyne.core.embeddings._get_model",
                        return_value=model):
            memory._guard_embedding()

    def test_its_answer_is_read_whole_inside_the_lock(self):
        model = self.model()
        self.guard(model)
        self.assertEqual(list(model.embed(["ab", "abc"])), [2, 3])

    def test_two_worlds_never_embed_at_once(self):
        model = self.model()
        self.guard(model)
        threads = [threading.Thread(target=lambda: list(model.embed(["x"])),
                                    daemon=True) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(type(model).most, 1)

    def test_guarding_twice_is_guarding_once(self):
        model = self.model()
        self.guard(model)
        first = model.embed
        self.guard(model)
        self.assertIs(model.embed, first)
