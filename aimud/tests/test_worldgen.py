"""
Making a world, without paying for one.

This path had no test at all, and it is how two bugs reached a player in one
afternoon: `worldreset` passed an account where a sponsor goes, and then the
generator handed a Sponsor to something that stores accounts. Neither raised
anywhere near its cause. The first surfaced as `'str' object is not callable`
inside `generate_first_room`; the second as `'NoneType' object is not
callable` from inside Evennia's pickler, with no frame of ours in the message
a player saw.

Both are the same shape: a value of the wrong type travelling a long way
before anything looks at it. A test that runs the whole path end to end with
scripted replies costs nothing and catches every one of them.
"""

from unittest import mock

from django.test import tag

from tests.base import GameTest
from tests.support import finishing, immediately, replying
from world import sponsor as sponsor_mod

PLAN = ({"zones": [{"name": "Hall", "purpose": "people pass through",
                           "room_types": ["hall"], "room_budget": 4}],
                "singleton_types": []})
NAME = ({"name": "Front Hall", "type": "hall",
                "category": "circulation", "zone": "Hall",
                "zone_purpose": "", "exits": []})
DESC = ({"description": "A plain hall.", "trait_bonuses": {}})


@tag("world")
class MakingTheFirstRoom(GameTest):
    accounts = True

    def setUp(self):
        super().setUp()
        # A sponsor with a working key and no account behind it is not a state
        # a real one can be in -- `key()` reads the account -- so these use the
        # real thing throughout. That is the point: the fake is exactly what
        # let the account-shaped bug through.
        self.account.db.openrouter_api_key = "sk-test"

    def generate(self, sponsor, **kwargs):
        """Run the whole path and report (room, error)."""
        from world.worldgen import generate_first_room

        made, failed = [], []
        with immediately(), replying(finishing(
                plan_world=PLAN, name_room=NAME, describe_room=DESC)):
            generate_first_room(sponsor, {"description": "a quiet hall"},
                                on_success=made.append,
                                on_error=failed.append, **kwargs)
        return (made[0] if made else None), (failed[0] if failed else None)

    def test_a_world_is_built(self):
        """
        End to end, on the real sponsor. The fake never covered this: it has
        no account, so every line that reads one was skipped -- including the
        one that stored a Sponsor where an account belongs and failed inside
        a pickle.
        """
        room, error = self.generate(sponsor_mod.of_account(self.account))
        self.assertIsNone(error)
        self.assertIsNotNone(room)

    def test_and_the_world_knows_who_made_it(self):
        room, _error = self.generate(sponsor_mod.of_account(self.account))
        self.assertEqual(sponsor_mod.creator_of(room), self.account)

    def test_which_is_the_account_and_not_the_sponsor_carrying_it(self):
        """
        What went wrong, asserted on its own. `world_creator` is persisted, so
        storing the wrong kind of thing is not a wrong value -- it is a
        TypeError from Evennia's pickler with nothing of ours in the message.
        """
        room, _error = self.generate(sponsor_mod.of_account(self.account))
        self.assertNotIsInstance(room.db.world_creator, sponsor_mod.Sponsor)

    def test_a_sponsor_with_no_key_is_refused_before_any_prompt(self):
        self.account.db.openrouter_api_key = ""
        room, error = self.generate(sponsor_mod.of_account(self.account))
        self.assertIsNone(room)
        self.assertIn("API key", error)


@tag("world")
class RecordingWhoMadeIt(GameTest):
    accounts = True

    def test_claim_refuses_anything_that_is_not_an_account(self):
        """
        Loudly and in place, rather than several frames later inside a pickle.
        The value it was actually handed was a Sponsor, which is one rename
        away from the account inside it.
        """
        sponsor_mod.claim(self.room1, sponsor_mod.of_account(self.account))
        self.assertIsNone(self.room1.db.world_creator)

    def test_and_stores_an_account_as_it_always_did(self):
        sponsor_mod.claim(self.room1, self.account)
        self.assertEqual(self.room1.db.world_creator, self.account)


@tag("world")
class ADoorThatCouldNotBeBuilt(GameTest):
    """
    The invariant a stranded door broke: whatever happens, the way opens again.

    Found live. `exits.at_traverse` sets `ndb.generating` before it asks and
    clears it only from `on_success` / `on_error`, so a callback that raised
    left the door saying "a room is already being generated here" to everybody
    who tried it, for ever -- and nothing was logged, because the exception
    reached a Deferred nothing had an errback on. The reactor was idle, the
    threadpool was idle and no request was in flight.

    `llm._delivered` is the fix and `test_converse` holds the mechanism still.
    This holds the consequence still, which is the part a player notices.
    """

    accounts = True
    second_room = True

    def setUp(self):
        super().setUp()
        self.account.db.openrouter_api_key = "sk-test"
        self.room1.db.is_world_root = True
        self.room1.db.world_root = self.room1
        self.room1.db.world_description = "A quiet hall."

    def crossing(self, on_success=None):
        """Build the room beyond an exit, and report (made, failed)."""
        from world.worldgen import generate_connected_room

        made, failed = [], []
        with immediately(), replying(finishing(
                name_room=NAME, describe_room=DESC)):
            generate_connected_room(
                sponsor_mod.of_account(self.account),
                {"description": "a quiet hall"}, self.room1, "east",
                on_success or made.append, failed.append)
        return made, failed

    def test_a_fault_between_the_name_and_the_description_is_reported(self):
        """
        The seam that actually stranded the door. `generate_connected_room`
        guards `finish` -- the callback that runs once the description is back
        -- but not `with_name`, which runs between the two model calls. An
        exception there had nowhere to go at all.

        `_allowed_exits` stands in for whatever might fail in there; what is
        being held still is that the caller's `on_error` is reached, because
        that is what releases the door.
        """
        with mock.patch("world.worldgen._allowed_exits",
                        side_effect=RuntimeError("the exits made no sense")):
            _made, failed = self.crossing()
        self.assertEqual(len(failed), 1, "nobody was told, so nothing released")
        self.assertIn("the exits made no sense", failed[0])

    def test_a_fault_after_the_description_is_reported_as_it_always_was(self):
        """`finish`'s own try/except, which was there before and still is."""
        def boom(_room):
            raise RuntimeError("the door could not be retargeted")

        _made, failed = self.crossing(boom)
        self.assertEqual(len(failed), 1)
        self.assertIn("the door could not be retargeted", failed[0])

    def test_and_the_ordinary_crossing_still_works(self):
        made, failed = self.crossing()
        self.assertEqual(failed, [])
        self.assertEqual(len(made), 1)
