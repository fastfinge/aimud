"""
Rotating the server log without closing it, so rotation works on Windows.

**What went wrong.** Evennia rotates `server.log` once it passes
`SERVER_LOG_MAX_SIZE`, or once a week, with Twisted's `DailyLogFile.rotate`:
close the file, rename it, open a new one. On Windows a file cannot be renamed
while any other handle has it open -- and the server always has another handle
on its own log, because the Portal starts it with stdout pointed at
`server.log` (`evennia/server/portal/amp_server.py`) to catch anything printed
before logging is set up. So the rename always failed. The file had already
been closed, nothing reopened it, and every line afterwards raised "I/O
operation on closed file" -- including the line trying to report the failure.
It survived restarts, too: the log stayed over the limit, so every new server
tried to rotate on its first write and lost its log the same way.

**What this does instead.** Copy the log to its dated name, then empty the
original in place. Copying and truncating work with other handles open, the
file is never closed, and anything that goes wrong leaves the old log still
being written to rather than no log at all. It is the `copytruncate` strategy
logrotate uses for programs that cannot reopen their logs, for the same reason.

The one thing given up is the few lines that could land between the copy and
the truncate, from another process writing at that instant. The only other
writer is a server's own stdout, before its logging starts.

`install` swaps the method in; `recover` reopens a log that an earlier
rotation, before `install` ran, already closed. Both are called from
`at_server_init`, which is the earliest hook the game has.
"""

import os
import shutil


def rotate_in_place(self):
    """
    `WeeklyLogFile.rotate`, by copy and truncate. Never leaves the file closed.

    Silent on failure, as Twisted's own rotate is: a log that failed to rotate
    goes on growing, which is a smaller problem than one that stops.
    """
    try:
        newpath = f"{self.path}.{self.suffix(self.lastDate)}"
        if os.path.exists(newpath):
            return
        if _is_closed(self):
            self._openFile()
        self._file.flush()
        shutil.copyfile(self.path, newpath)
        self._file.seek(0)
        self._file.truncate()
        self.size = 0
        self.lastDate = self.toDate()
    except Exception:
        pass
    finally:
        if _is_closed(self):
            try:
                self._openFile()
            except Exception:
                pass


def _is_closed(logfile):
    handle = getattr(logfile, "_file", None)
    return handle is None or handle.closed


def install():
    """Make every Evennia rotating log rotate in place. Safe to call twice."""
    from evennia.utils.logger import WeeklyLogFile

    WeeklyLogFile.rotate = rotate_in_place


def recover(observers=None):
    """
    Reopen, and rotate, any Evennia log a failed rotation left closed.

    `observers` is for tests; by default it is every observer on Twisted's
    global log publisher, which is where the server log's lives. Returns how
    many logs were brought back.
    """
    from evennia.utils.logger import WeeklyLogFile

    if observers is None:
        from twisted.logger import globalLogPublisher

        observers = list(getattr(globalLogPublisher, "_observers", []))

    recovered = 0
    for observer in observers:
        logfile = getattr(observer, "_outFile", None)
        if not isinstance(logfile, WeeklyLogFile) or not _is_closed(logfile):
            continue
        rotate_in_place(logfile)
        if not _is_closed(logfile):
            recovered += 1
    return recovered
