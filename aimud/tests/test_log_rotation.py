"""
Rotating the server log while something else holds it open.

The server always has a second handle on its own log -- the Portal points its
stdout there -- and on Windows that made every rotation close the log and then
fail to rename it, so logging stopped for good. `ASecondHandle` holds a file
open the way the Portal does. See server/conf/logrotation.py.
"""

import os
import shutil
import tempfile
from unittest import mock, skipUnless

from django.test import SimpleTestCase, tag

from server.conf import logrotation


class ASecondHandle(SimpleTestCase):
    """A small rotating log in a temporary directory, held open twice."""

    def setUp(self):
        from evennia.utils.logger import WeeklyLogFile

        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.log = WeeklyLogFile("server.log", self.directory, max_size=64)
        self.addCleanup(self._close, self.log)
        # What the Portal does: the log opened again, for appending, and kept.
        self.held = open(self.log.path, "a")
        self.addCleanup(self.held.close)

    @staticmethod
    def _close(log):
        try:
            log.close()
        except Exception:
            pass

    def rotated(self):
        return [name for name in os.listdir(self.directory)
                if name.startswith("server.log.")]


@tag("unit")
class TheOldRotation(ASecondHandle):

    @skipUnless(os.name == "nt", "renaming an open file only fails on Windows")
    def test_it_closed_the_log_for_good(self):
        """The fault, reproduced: past the size limit, writing fails."""
        self.log.write("x" * 80 + "\n")
        with mock.patch("evennia.utils.logger.log_trace"):
            with self.assertRaises(ValueError):
                self.log.write("the next line\n")


@tag("unit")
class RotatingInPlace(ASecondHandle):

    def setUp(self):
        super().setUp()
        from evennia.utils.logger import WeeklyLogFile

        patcher = mock.patch.object(WeeklyLogFile, "rotate",
                                    logrotation.rotate_in_place)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_log_goes_on_being_written(self):
        self.log.write("before " + "x" * 80 + "\n")
        self.log.write("after\n")
        self.log.flush()
        with open(self.log.path) as current:
            self.assertEqual(current.read(), "after\n")

    def test_what_was_there_is_kept_under_a_dated_name(self):
        self.log.write("before " + "x" * 80 + "\n")
        self.log.write("after\n")
        self.assertEqual(len(self.rotated()), 1)
        with open(os.path.join(self.directory, self.rotated()[0])) as kept:
            self.assertIn("before", kept.read())

    def test_the_size_starts_again(self):
        self.log.write("x" * 80 + "\n")
        self.log.write("after\n")
        self.assertLess(self.log.size, 64)

    def test_a_second_rotation_gets_its_own_name(self):
        for _ in range(3):
            self.log.write("x" * 80 + "\n")
        self.assertGreaterEqual(len(self.rotated()), 2)


@tag("unit")
class Recovering(ASecondHandle):

    def test_a_log_left_closed_is_reopened_and_rotated(self):
        self.log.write("x" * 80 + "\n")
        self.log._file.close()
        observer = mock.Mock(_outFile=self.log)
        self.assertEqual(logrotation.recover([observer]), 1)
        self.log.write("after\n")
        self.log.flush()
        with open(self.log.path) as current:
            self.assertEqual(current.read(), "after\n")

    def test_an_open_log_is_left_alone(self):
        observer = mock.Mock(_outFile=self.log)
        self.assertEqual(logrotation.recover([observer]), 0)
        self.assertEqual(self.rotated(), [])

    def test_anything_that_is_not_a_rotating_log_is_ignored(self):
        self.assertEqual(logrotation.recover([mock.Mock(_outFile=None),
                                              object()]), 0)


@tag("unit")
class Installing(SimpleTestCase):

    def test_it_replaces_evennias_rotation(self):
        from evennia.utils.logger import WeeklyLogFile

        with mock.patch.object(WeeklyLogFile, "rotate", WeeklyLogFile.rotate):
            logrotation.install()
            self.assertIs(WeeklyLogFile.rotate, logrotation.rotate_in_place)
