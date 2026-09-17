"""
What time it is in a world.

**Every world has a clock, and until it is told otherwise it is the real one:**
the server's local date and time, running at real speed. A world never turns a
clock on, and "what time is it" always has an answer. The most usual change is
only the year -- a Victorian London is real time in 1852, a starship real time
in 2253 -- and a world that wants slower days sets a longer day. See
docs/becoming-and-time.md §8.

The date is a `datetime` in the real Gregorian calendar, so weekdays, month
lengths and leap years come from the standard library and nothing here can get
them wrong. It is read, never kept: nothing is written as it advances, so a
world nobody is watching costs nothing, and its clock goes on running while it
sleeps, exactly as quest deadlines do. There is no setting to stop it.

Why not `evennia.utils.gametime`: that is one clock for the whole server, set
by `TIME_FACTOR` in settings, and its `schedule` makes a persistent Script per
event. Worlds on one server keep different days.

    world_root.db.clock = {"epoch": real timestamp,
                           "began": "1852-06-14T06:00:00",
                           "speed": 1.0}

All three are optional. The date is `began` plus `(now - epoch) * speed`.
"""

import threading
import time
from datetime import datetime, timedelta

from evennia.utils import logger

#: Where a world keeps its clock.
ATTR = "clock"

#: The group the time of day is kept in, and the periods every world starts
#: with, in real-world hours. A range includes its start and not its end.
PERIOD_GROUP = "time_of_day"
PERIODS = (
    ("dawn", "the sun coming up", 5, 7),
    ("day", "daylight", 7, 18),
    ("dusk", "the sun going down", 18, 20),
    ("night", "dark, after the sun has gone down", 20, 5),
)

#: Marks a world as having had its periods seeded, so seeding is idempotent
#: and a world that renamed or removed one is not given it back.
SEEDED = "clock_periods_seeded"

#: What `time.time()` is, for a test that needs to stand still or move on.
NOW = None

_PINNED = threading.local()


def _real_now():
    stack = getattr(_PINNED, "stack", None)
    if stack:
        return stack[-1]
    return (NOW or time.time)()


class pinned:
    """
    Read every clock as it was at real timestamp `when`, for the length of it.

    For asking what a condition said at a moment other than now: just before a
    boundary, to know whether it rose there. See `world.becoming`.
    """

    def __init__(self, when):
        self.when = float(when)

    def __enter__(self):
        stack = getattr(_PINNED, "stack", None)
        if stack is None:
            stack = _PINNED.stack = []
        stack.append(self.when)
        return self

    def __exit__(self, *exc):
        _PINNED.stack.pop()
        return False


def settings(world_root):
    """This world's clock settings, as a plain dict. Empty for real time."""
    if world_root is None:
        return {}
    try:
        return dict(getattr(world_root.db, ATTR, None) or {})
    except (TypeError, ValueError):
        return {}


def speed(world_root):
    """How many seconds pass here for each real one."""
    try:
        return max(float(settings(world_root).get("speed") or 1.0), 0.0) or 1.0
    except (TypeError, ValueError):
        return 1.0


def now(world_root=None):
    """The date and time in this world, as a `datetime`."""
    real = _real_now()
    found = settings(world_root)
    began = found.get("began")
    if not began:
        return datetime.fromtimestamp(real)
    try:
        start = datetime.fromisoformat(str(began))
        epoch = float(found.get("epoch") or real)
        return start + timedelta(seconds=(real - epoch) * speed(world_root))
    except (TypeError, ValueError, OverflowError) as exc:
        logger.log_info(f"clock: {world_root} has a clock that cannot be read "
                        f"({exc}); using real time")
        return datetime.fromtimestamp(real)


def hour(world_root=None):
    """The hour on a 24-hour dial, with the minutes as a fraction: 20.5."""
    moment = now(world_root)
    return moment.hour + moment.minute / 60 + moment.second / 3600


# ---------------------------------------------------------------------------
# Changing it
# ---------------------------------------------------------------------------

def _write(world_root, began, clock_speed):
    setattr(world_root.db, ATTR, {"epoch": _real_now(),
                                  "began": began.isoformat(timespec="seconds"),
                                  "speed": float(clock_speed)})
    _changed(world_root)


def _changed(world_root):
    """A clock that moved has new boundaries, so its timer is set afresh."""
    from world import becoming

    becoming.arm_clock(world_root)


def set_year(world_root, year):
    """
    Make it that year, keeping the day and the hour. Returns the new date.

    The change most worlds make. 29 February becomes the 28th in a year that
    has none. Years run from 1 to 9999, the standard library's own limit.
    """
    year = int(year)
    if not 1 <= year <= 9999:
        raise ValueError("a year from 1 to 9999")
    current = now(world_root)
    try:
        moved = current.replace(year=year)
    except ValueError:
        moved = current.replace(year=year, day=28)
    _write(world_root, moved, speed(world_root))
    return moved


def set_now(world_root, moment):
    """Make it this date and time, from here on. Returns it."""
    _write(world_root, moment, speed(world_root))
    return moment


def set_speed(world_root, clock_speed):
    """
    Let this many seconds pass here for each real one, from now on.

    The date is kept where it is, so the hour does not jump. Returns the speed.
    """
    clock_speed = float(clock_speed)
    if clock_speed <= 0:
        raise ValueError("a speed above nothing")
    _write(world_root, now(world_root), clock_speed)
    return clock_speed


def set_day_length(world_root, real_minutes):
    """Make a day here last this many real minutes."""
    minutes = float(real_minutes)
    if minutes <= 0:
        raise ValueError("a day that lasts some time")
    return set_speed(world_root, (24 * 60) / minutes)


def reset(world_root):
    """Put this world back on real time."""
    if world_root is None:
        return
    try:
        world_root.attributes.remove(ATTR)
    except Exception:
        setattr(world_root.db, ATTR, None)
    _changed(world_root)


def day_length_minutes(world_root):
    """How many real minutes a day here lasts."""
    return (24 * 60) / speed(world_root)


def is_real(world_root):
    """True for a world on the real date and time."""
    return not settings(world_root).get("began")


# ---------------------------------------------------------------------------
# The dial
# ---------------------------------------------------------------------------

def in_range(at, start, end):
    """
    Whether hour `at` is in the range from `start` to `end`.

    Includes the start and not the end, and wraps past midnight when the end
    comes first, so the range and its swap cover the day exactly once between
    them. A range that starts where it ends is empty.
    """
    at, start, end = float(at) % 24, float(start) % 24, float(end) % 24
    if start == end:
        return False
    if start < end:
        return start <= at < end
    return at >= start or at < end


def real_seconds_until(world_root, target_hour):
    """
    Real seconds until this world's dial next reaches `target_hour`.

    Never nought: a dial exactly on the hour next reaches it a day later.
    """
    here = hour(world_root)
    ahead = (float(target_hour) - here) % 24
    if ahead == 0:
        ahead = 24
    return ahead * 3600 / speed(world_root)


def real_time_of_last(world_root, target_hour, before=None):
    """The real timestamp at which the dial last reached `target_hour`."""
    real = _real_now() if before is None else float(before)
    with pinned(real):
        here = hour(world_root)
    behind = (here - float(target_hour)) % 24
    return real - behind * 3600 / speed(world_root)


# ---------------------------------------------------------------------------
# Saying it
# ---------------------------------------------------------------------------

_NUMBERS = ("twelve", "one", "two", "three", "four", "five", "six", "seven",
            "eight", "nine", "ten", "eleven")


def hour_words(at):
    """
    An hour as somebody would say it: "eight at night", "half past six in the
    morning", "noon", "midnight".
    """
    at = float(at) % 24
    whole = int(at)
    minutes = int(round((at - whole) * 60))
    if minutes == 60:
        whole, minutes = (whole + 1) % 24, 0
    if minutes == 0 and whole == 0:
        return "midnight"
    if minutes == 0 and whole == 12:
        return "noon"
    if whole < 12:
        part = "in the morning"
    elif whole < 17:
        part = "in the afternoon"
    elif whole < 20:
        part = "in the evening"
    else:
        part = "at night"
    said = _NUMBERS[whole % 12]
    if minutes == 0:
        return f"{said} {part}"
    if minutes == 30:
        return f"half past {said} {part}"
    return f"{whole % 12 or 12}:{minutes:02d} {part}"


def _part_of_day(at):
    if 5 <= at < 12:
        return "morning"
    if 12 <= at < 17:
        return "afternoon"
    if 17 <= at < 21:
        return "evening"
    return "night"


def said(world_root=None):
    """
    The date as a line a character can be told: "It is a Tuesday evening in
    June, 1852."
    """
    moment = now(world_root)
    at = moment.hour + moment.minute / 60
    return (f"It is a {moment.strftime('%A')} {_part_of_day(at)} in "
            f"{moment.strftime('%B')}, {moment.year}.")


def exactly(world_root=None):
    """The date and time in full, for `view world`: "14 June 1852, 7:05pm"."""
    moment = now(world_root)
    clock_hour = moment.hour % 12 or 12
    half = "am" if moment.hour < 12 else "pm"
    return (f"{moment.day} {moment.strftime('%B')} {moment.year}, "
            f"{clock_hour}:{moment.minute:02d}{half}")


# ---------------------------------------------------------------------------
# The periods of the day, as derived states of the world
# ---------------------------------------------------------------------------

def seed_periods(world_root):
    """
    Give a world dawn, day, dusk and night, once.

    Derived states of the world itself, in an exclusive group, so a rule says
    `{"subject": "world", "is": ["night"]}` and never mentions an hour. Each
    can be edited or renamed -- a station may keep shifts -- and a world that
    has had them once is never given them again.
    """
    from world import verbs

    if world_root is None or getattr(world_root.db, SEEDED, False):
        return
    for slug, means, start, end in PERIODS:
        verbs.register_state(
            world_root, slug, means=means, group=PERIOD_GROUP, of="world",
            when=[{"subject": "world", "clock": {"from": start, "to": end}}])
    setattr(world_root.db, SEEDED, True)
