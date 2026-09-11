"""
Who pays, asked from the room rather than from the player.

Two things are being held still here. One is the direction of the creator
link: an account has always listed the worlds it made, nothing on a world said
who made it, and everything the roadmap wants -- shared worlds, a spend ledger,
a world that answers nothing -- needs the question asked from the world's end.
The other is that a sponsor is allowed to have no money behind it. That is an
ordinary state, not an error, and the difference between `answers` saying no
and `key` raising is the difference between a generator deciding not to start
and a generator being stopped halfway.
"""

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from world import sponsor


@tag("unit")
class ASponsorWithNobodyBehindIt(SimpleTestCase):
    """
    The empty case, which is the one every caller meets first and the one a
    `ValueError` in the wrong place turns into a crash.
    """

    def test_answers_nothing(self):
        self.assertFalse(sponsor.Sponsor().answers)

    def test_and_says_why_rather_than_returning_an_empty_key(self):
        with self.assertRaises(ValueError):
            sponsor.Sponsor().key()

    def test_a_model_choice_is_still_a_string(self):
        """
        Every caller treats a model as a string -- an `or` fallback, a payload
        field, a log line -- so answering None here would move the failure into
        whichever of those ran first.
        """
        self.assertEqual(sponsor.Sponsor().model_for("commands"), "")

    def test_the_service_has_a_default(self):
        from world import llm

        self.assertEqual(sponsor.Sponsor().base_url, llm.BASE_URL)


@tag("world")
class FindingWhoPays(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.account.db.openrouter_api_key = "sk-test"

    def test_a_world_names_its_maker_once_it_is_claimed(self):
        sponsor.claim(self.root, self.account)
        self.assertEqual(sponsor.creator_of(self.root), self.account)

    def test_a_character_asks_the_room_rather_than_themselves(self):
        """
        The whole point. `char2` did not make this world and may have no key of
        their own; the key that pays is still the one belonging to whoever did.
        """
        sponsor.claim(self.root, self.account)
        found = sponsor.of(self.char2)
        self.assertEqual(found.payer, self.account)
        self.assertEqual(found.actor, self.char2)
        self.assertEqual(found.key(), "sk-test")

    def test_a_world_made_before_the_back_link_is_found_by_scanning(self):
        self.account.db.created_worlds = [self.root.id]
        self.assertEqual(sponsor.creator_of(self.root), self.account)

    def test_and_claims_itself_on_the_way_past(self):
        """
        So the scan is paid once per world at most. Without this the fallback
        is not a fallback, it is the implementation.
        """
        self.account.db.created_worlds = [self.root.id]
        sponsor.creator_of(self.root)
        self.assertEqual(self.root.db.created_by, self.account.id)

    def test_backfill_claims_every_unclaimed_world(self):
        self.account.db.created_worlds = [self.root.id]
        self.assertEqual(sponsor.backfill(), 1)
        self.assertEqual(self.root.db.created_by, self.account.id)

    def test_and_is_a_no_op_the_second_time(self):
        self.account.db.created_worlds = [self.root.id]
        sponsor.backfill()
        self.assertEqual(sponsor.backfill(), 0)

    def test_a_world_nobody_claims_has_no_payer(self):
        self.assertIsNone(sponsor.creator_of(self.root))
        self.assertFalse(sponsor.of(self.char1).answers)

    def test_a_world_whose_maker_has_no_key_answers_nothing(self):
        self.account.db.openrouter_api_key = ""
        sponsor.claim(self.root, self.account)
        self.assertFalse(sponsor.of(self.char1).answers)

    def test_and_tells_a_visitor_whose_key_is_missing(self):
        """
        A visitor cannot act on "use the apikey command", so they are not told
        to. The distinction is the reason `key` takes the actor at all.
        """
        self.account.db.openrouter_api_key = ""
        sponsor.claim(self.root, self.account)
        self.char2.account = None
        with self.assertRaises(ValueError) as caught:
            sponsor.of(self.char2).key()
        self.assertNotIn("apikey set", str(caught.exception))

    def test_while_the_owner_is_told_how_to_fix_it(self):
        self.account.db.openrouter_api_key = ""
        sponsor.claim(self.root, self.account)
        with self.assertRaises(ValueError) as caught:
            sponsor.of(self.char1).key()
        self.assertIn("apikey set", str(caught.exception))

    def test_somewhere_that_is_not_a_world_has_no_payer(self):
        """
        Limbo, or anywhere outside a generated world. Answered rather than
        raised, because a command reaching here has done nothing wrong.
        """
        self.room2.db.world_root = None
        self.char1.location = self.room2
        self.assertFalse(sponsor.of(self.char1).answers)

    def test_the_base_url_follows_the_account_that_pays(self):
        self.account.db.api_base_url = "https://nano-gpt.com/api/v1/"
        sponsor.claim(self.root, self.account)
        self.assertEqual(sponsor.of(self.char2).base_url,
                         "https://nano-gpt.com/api/v1")
