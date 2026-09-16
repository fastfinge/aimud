"""
What a test starts with, and why it is usually less than you think.

Evennia's `EvenniaTest` builds the same world before every single test method:
two accounts, two rooms, an exit, two loose objects, two characters, a script
and a logged-in session. It is rebuilt from nothing 1,600-odd times a run, and
a survey of this suite found that almost none of it was being named: of the 232
database-backed test classes, eleven mention `self.account`, and not one
mentions `account2`, `session`, `script` or `exit`.

So the default here is the smallest fixture a world test can have -- one room,
one character standing in it -- and everything else is asked for by name. A
class that needs more says so at the top, which also means that reading a test
class tells you what world it thinks it is in.

    class TakingSomething(GameTest):
        loose_objects = 1

Measured on the whole suite rather than on a microbenchmark, which for this
flatters itself: 1,667 tests went from 630s to somewhere between 170s and 230s,
the spread being what wall clock on a developer machine does. Two warnings in
that, both learned the hard way here. Do not trust the cost of a single `setUp`
timed in a small file -- the first fixtures built in a process are several times
dearer than the steady state, and an empty world makes this game's
`return_appearance` chain look far cheaper than it is. And do not tune against
one run.


## The dials

Each is a class attribute, set on the test class, and each names exactly what
`EvenniaTest` would have built anyway -- the objects keep their upstream names
so that moving a test between categories is only ever a line at the top.

| attribute          | default | what it adds                                  |
|--------------------|---------|-----------------------------------------------|
| `characters`       | `1`     | `char1`; `2` also makes `char2`, same room    |
| `loose_objects`    | `0`     | `1` makes `obj1`; `2` also makes `obj2`       |
| `second_room`      | `False` | `room2`, and `exit` leading there from `room1` |
| `accounts`         | `False` | `account`/`account2`, puppeting the characters |
| `session`          | `False` | a logged-in session; implies `accounts`       |
| `script`           | `False` | a bare `Script`, as `self.script`             |

`room1` and `char1` are not dials. Something has to be somewhere, and a world
test with nobody in it is a `SimpleTestCase` that has not noticed yet.


## How a test was put in a category

Mechanically, and then checked by running it. An AST pass over `tests/` found
every `self.<fixture>` each class touches, counting what it inherits; that
gives the dials. Then the suite was run, and what failed was moved up a
category until it passed.

The second half is not a formality, because **a fixture can be load-bearing
without being named**. Nine classes here needed something no `self.` in them
asks for, and they came in two shapes:

* *Typed, not referenced.* `test_actions.TheSilentNoOpIsGone` types
  `"search obj"`, so there has to be something actually called Obj in the
  room. `test_phases.ThePhasesInOrder` is the same trick twice over: its
  parent renames `obj1` to Book, so `"order obj"` needs `obj2`.
* *A player is a character with an account.* That is the literal test in
  `world/goals.py`, so anything asking whether a want belongs to a player
  rather than an NPC needs `accounts`, however little it cares about login.

Those are the cases the run finds and the survey cannot. Each one has the dial
set with a comment saying why, because the next person to read it will
otherwise quite reasonably try to take it away again.


## Choosing for a new test

Start at `GameTest` and add only what the test actually reaches for. In
particular:

* **`accounts` is almost never the answer.** An account is the out-of-character
  layer -- login, puppeting, who pays for a model call. If the test is about
  something a character does in a room, it does not need one. Eleven classes
  set it, and they fall into two groups: sponsorship, billing and world
  creation, which are genuinely account-shaped; and anywhere the question is
  *is this a player or an NPC*, because `world/goals.py` answers that by
  whether an account is behind the character.
* **`session` is rarer still** -- two classes, both in `test_busy.py`. Nothing
  needs a session to *receive* messages: `GameCommandTest.call()` mocks `.msg`
  on the receiver, and `char.msg()` with nowhere to go is not an error. Set it
  only where the code under test asks whether anybody is connected, as
  `busy._present` does.
* **`characters = 2` costs the most of any dial**, because Evennia looks at the
  room on every character's arrival, and that runs this game's whole
  `return_appearance` chain over a room that now has more in it. Two characters
  is for tests about two people; a test about one person watching something
  happen wants one.

If a test needs a world that no dial describes -- a particular room layout, a
container with something in it -- build it in `setUp` after `super().setUp()`,
rather than reaching for a bigger fixture and using a corner of it.
"""

import evennia
from django.conf import settings
from django.test import override_settings
from evennia.utils import create
from evennia.utils.idmapper.models import flush_cache
from evennia.utils.test_resources import (
    EvenniaCommandTestMixin,
    EvenniaTest,
    EvenniaTestCase,
    EvenniaTestMixin,
)

#: What upstream sets while the standard rooms are built, so that a test can
#: spawn a named prototype. Kept because the fixture is otherwise upstream's.
_PROTOTYPES = ["evennia.utils.tests.data.prototypes_example"]


class GameTest(EvenniaTest):
    """
    One room, one character in it, and whatever else the class asks for.

    See the module docstring for the dials and for how to pick them.
    """

    #: `char1`, and `char2` as well if this is 2.
    characters = 1
    #: `obj1` if this is 1, `obj1` and `obj2` if it is 2, on the floor of `room1`.
    loose_objects = 0
    #: `room2`, and `exit` leading to it from `room1`.
    second_room = False
    #: `account` and `account2`, puppeting `char1` and `char2`.
    accounts = False
    #: A logged-in session for `account`. Implies `accounts`. Note that this
    #: name does double duty, as upstream's does: it is the flag until `setUp`
    #: runs, and the session itself (or `None`) afterwards.
    session = False
    #: A bare `Script`, as `self.script`.
    script = False

    # -- the pieces, each one upstream's with a condition in front ----------

    def create_accounts(self):
        # `None` rather than absent: `EvenniaCommandTestMixin.call()` assigns
        # `self.account` onto the command it builds without checking, and a
        # command with no account behind it is the ordinary case in this game.
        if not (self.accounts or self.session):
            self.account = None
            self.account2 = None
            return
        super().create_accounts()

    def teardown_accounts(self):
        # Upstream guards this with `hasattr`, which is true of the `None`s
        # above. Truthiness is the question actually being asked.
        if getattr(self, "account", None):
            self.account.delete()
        if getattr(self, "account2", None):
            self.account2.delete()

    @override_settings(PROTOTYPE_MODULES=_PROTOTYPES)
    def create_rooms(self):
        self.room1 = create.create_object(self.room_typeclass, key="Room",
                                          nohome=True)
        self.room1.db.desc = "room_desc"
        if not self.second_room:
            return
        self.room2 = create.create_object(self.room_typeclass, key="Room2")
        self.exit = create.create_object(
            self.exit_typeclass, key="out", location=self.room1,
            destination=self.room2)

    def create_objs(self):
        if self.loose_objects >= 1:
            self.obj1 = create.create_object(
                self.object_typeclass, key="Obj", location=self.room1,
                home=self.room1)
        if self.loose_objects >= 2:
            self.obj2 = create.create_object(
                self.object_typeclass, key="Obj2", location=self.room1,
                home=self.room1)

    def create_chars(self):
        self.char1 = create.create_object(
            self.character_typeclass, key="Char", location=self.room1,
            home=self.room1)
        self.char1.permissions.add("Developer")
        if self.characters >= 2:
            self.char2 = create.create_object(
                self.character_typeclass, key="Char2", location=self.room1,
                home=self.room1)
        if not (self.accounts or self.session):
            return
        self.char1.account = self.account
        self.account.db._last_puppet = self.char1
        if self.characters >= 2:
            self.char2.account = self.account2
            self.account2.db._last_puppet = self.char2

    def create_script(self):
        if self.script:
            super().create_script()

    def setup_session(self):
        if not self.session:
            self.session = None
            return
        super().setup_session()

    # -- teardown ----------------------------------------------------------

    @override_settings(PROTOTYPE_MODULES=_PROTOTYPES)
    def tearDown(self):
        """
        Upstream's, with the session line guarded.

        This is a copy rather than a `super()` call because upstream's version
        ends in an unconditional `del SESSION_HANDLER[self.session.sessid]`,
        and most tests here no longer have a session for it to delete. Kept
        line-for-line otherwise, so that a change upstream is easy to spot.
        """
        flush_cache()
        try:
            evennia.SESSION_HANDLER.data_out = self.backups[0]
            evennia.SESSION_HANDLER.disconnect = self.backups[1]
            settings.DEFAULT_HOME = self.backups[2]
            settings.PROTOTYPE_MODULES = self.backups[3]
        except AttributeError as err:
            raise AttributeError(
                f"{err}: Teardown error. If you overrode the `setUp()` method "
                "in your test, make sure you also added `super().setUp()`!"
            )
        if self.session is not None:
            del evennia.SESSION_HANDLER[self.session.sessid]
        self.teardown_accounts()
        # Skips `EvenniaTestMixin.tearDown`, which is what this replaces.
        super(EvenniaTestMixin, self).tearDown()


class GameCommandTest(GameTest, EvenniaCommandTestMixin):
    """
    A `GameTest` with `.call()`, for driving a command and reading it back.

    Same dials. `.call()` needs no session and no account: it mocks `.msg` on
    whoever is receiving, so what the command sent is captured either way.
    """


#: No database objects at all -- for logic that never touches the world. The
#: cheapest thing in this module by a distance; prefer it, and prefer a plain
#: `SimpleTestCase` over it when there is no database in the picture whatsoever.
NoWorldTest = EvenniaTestCase
