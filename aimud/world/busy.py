"""
Telling a player that a model is still working.

A new verb can mean four model calls in a row, and a new room several more, and
each is allowed up to a minute. What a player saw was one line -- "You try to
pry the crate..." -- and then nothing for as long as it took, which from the
keyboard cannot be told apart from a game that has stopped. This says, every so
often, that it has not.

**Only players are told.** A character nobody is playing cannot worry that the
game has crashed, and a line in its working memory would be one more thing its
next prompt has to read past. So a character is refused when it is added to a
wait, rather than being sent something and filtered later.

**A wait is the whole job, not one call.** It is opened where somebody starts
waiting and closed where the answer is delivered, so a verb that needs four
calls is one wait with one elapsed time. `stage` says what it is doing now, and
the notice says that rather than merely that something is still going.

**Nothing here cancels anything.** A room that arrives late is still a room.
The safety limit stops the notices for a wait whose callback was lost, and
nothing else.

Reactor only, and in memory only: a reload ends every wait, and the work it was
waiting on with it.
"""

from evennia.utils import logger
from twisted.internet import reactor

#: How often a player is told, in seconds, when they have not said.
DEFAULT_INTERVAL = 10

#: What `busy <seconds>` accepts. Below five the notices would talk over the
#: answer; above two minutes nobody would believe the game was still there.
LEAST = 5
MOST = 120

#: Where a player's choice is kept: on the account, because it is a preference
#: of the person at the keyboard rather than of any one character. 0 is never.
ATTR = "busy_interval"

#: How long a wait may stay open before it is assumed lost, in seconds. Real
#: work always ends sooner, because every model call has a timeout.
LIFETIME = 15 * 60

#: The clock waits run on. None is the reactor; a test puts one it can move by
#: hand here (see `tests.support.clock`).
CLOCK = None


def _the_clock(clock=None):
    return clock or CLOCK or reactor


def account_of(who):
    """The account behind `who`, or None for anything nobody is playing."""
    from evennia.accounts.accounts import DefaultAccount

    if isinstance(who, DefaultAccount):
        return who
    return getattr(who, "account", None)


def _present(who):
    """Whether anybody is still connected to be told."""
    try:
        return bool(who.sessions.count())
    except AttributeError:
        return False


# ---------------------------------------------------------------------------
# How often
# ---------------------------------------------------------------------------

def interval_for(who):
    """
    Seconds between notices for whoever is behind `who`, or 0 for never.

    0 for anything nobody plays, too, which is the same answer: nobody is told.
    """
    account = account_of(who)
    if account is None:
        return 0
    stored = account.attributes.get(ATTR)
    if stored is None:
        return DEFAULT_INTERVAL
    try:
        return max(0, int(stored))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL


def chosen(account):
    """What this account set, or None when it has left it at the default."""
    return account.attributes.get(ATTR) if account is not None else None


def parse_interval(text):
    """
    (seconds, complaint) for what somebody typed after `busy`.

    0 is off. None with no complaint means go back to the default.
    """
    said = str(text or "").strip().lower()
    if said in ("off", "never", "none", "0"):
        return 0, ""
    if said in ("default", "reset", "clear"):
        return None, ""
    try:
        seconds = int(said)
    except ValueError:
        return None, (f"Give a number of seconds from {LEAST} to {MOST}, or "
                      f"|woff|n.")
    if not LEAST <= seconds <= MOST:
        return None, f"That has to be from {LEAST} to {MOST} seconds, or |woff|n."
    return seconds, ""


def set_interval(account, seconds):
    """Keep a player's choice. None goes back to the default."""
    if seconds is None:
        account.attributes.remove(ATTR)
    else:
        account.attributes.add(ATTR, int(seconds))


# ---------------------------------------------------------------------------
# A wait
# ---------------------------------------------------------------------------

class Wait:
    """
    Somebody waiting on one job, and the notices that tell them it is going.

    Each waiter has their own timer, at their own interval, so two players at
    one door each hear about it as often as they asked to.
    """

    def __init__(self, doing, clock=None, lifetime=LIFETIME):
        self.doing = str(doing or "working").strip()
        self.current = ""
        self._clock = _the_clock(clock)
        self._started = self._clock.seconds()
        self._waiters = []
        self._timers = {}
        self._closed = False
        self._expiry = (self._clock.callLater(lifetime, self._expire)
                        if lifetime else None)

    @property
    def open(self):
        return not self._closed

    @property
    def waiters(self):
        return list(self._waiters)

    def add(self, who):
        """
        Tell `who` about this wait as well. True if they will be told.

        A character nobody is playing is refused here, and so is anything
        added to a wait that has already closed.
        """
        if self._closed or who is None or account_of(who) is None:
            return False
        if not any(waiter is who for waiter in self._waiters):
            self._waiters.append(who)
            self._schedule(who)
        return True

    def stage(self, text):
        """Say what the job is doing now. The next notice says it."""
        text = str(text or "").strip()
        if text:
            self.current = text

    def done(self):
        """The answer has arrived, or gone wrong. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        if self._waiters:
            # What a player actually waited, which no ledger entry says: a
            # verb that needs four calls is four entries and one wait. Only
            # when a player was waiting, because that is what is being
            # measured. The soak in docs/generator-tool-loops.md reads these.
            seconds = self._clock.seconds() - self._started
            logger.log_info(f"busy: waited {seconds:.1f}s for {self.doing!r}")
        for timer in self._timers.values():
            _cancel(timer)
        self._timers.clear()
        _cancel(self._expiry)
        self._expiry = None

    def _schedule(self, who):
        seconds = interval_for(who)
        if seconds > 0:
            self._timers[id(who)] = self._clock.callLater(seconds, self._tell,
                                                          who)

    def _tell(self, who):
        self._timers.pop(id(who), None)
        if self._closed:
            return
        if not _present(who):
            # Gone. Nobody to tell, and nobody to tell again later.
            self._waiters = [w for w in self._waiters if w is not who]
            return
        elapsed = int(self._clock.seconds() - self._started)
        # No colour codes, and the same opening word every time: a screen
        # reader user learns this line quickly and can skip straight past it.
        who.msg(f"Still {self.current or self.doing}... ({elapsed} seconds)")
        self._schedule(who)

    def _expire(self):
        self._expiry = None
        if self._closed:
            return
        logger.log_info(
            f"busy: stopped telling anybody about {self.doing!r}; nothing "
            f"closed the wait, so its answer was probably lost")
        self.done()


def _cancel(timer):
    try:
        if timer is not None and timer.active():
            timer.cancel()
    except Exception:
        pass


def start(who, doing, clock=None, lifetime=LIFETIME):
    """Open a wait for `who`, who is told only if somebody is playing them."""
    wait = Wait(doing, clock=clock, lifetime=lifetime)
    wait.add(who)
    return wait


def closing(wait, callback):
    """`callback`, closing `wait` first, so no notice lands after the answer."""
    def closed(*args, **kwargs):
        if wait is not None:
            wait.done()
        return callback(*args, **kwargs)

    return closed
