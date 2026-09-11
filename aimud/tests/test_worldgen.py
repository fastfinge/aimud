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

from django.test import tag
from evennia.utils.test_resources import EvenniaTest

from tests.support import as_json, immediately, replying
from world import sponsor as sponsor_mod

PLAN = as_json({"zones": [{"name": "Hall", "purpose": "people pass through",
                           "room_types": ["hall"], "room_budget": 4}],
                "singleton_types": []})
NAME = as_json({"name": "Front Hall", "type": "hall",
                "category": "circulation", "zone": "Hall",
                "zone_purpose": "", "exits": []})
DESC = as_json({"description": "A plain hall.", "trait_bonuses": {}})


@tag("world")
class MakingTheFirstRoom(EvenniaTest):

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
        with immediately(), replying(PLAN, NAME, DESC):
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
class RecordingWhoMadeIt(EvenniaTest):

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
