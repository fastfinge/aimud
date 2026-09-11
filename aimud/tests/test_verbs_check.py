"""
What a player is told when a verb will not work.

`verbs.check` is now a thin call onto `world.conditions`, and these tests exist
to say that the thin call kept what the fat one was careful about. The verdict
was never the hard part; the sentence was. A refusal that says "you cannot do
that" teaches nobody anything, and the version this replaces went to real
trouble to say which requirement failed and what the thing would have been
good for instead.
"""

from django.test import tag
from evennia.utils.test_resources import EvenniaTest

from world import verbs


@tag("world")
class RefusingAVerb(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.bound = {"direct": self.obj1}

    def refuse(self, requires):
        return verbs.check(requires, self.bound, self.char1,
                           world_root=self.root)

    def test_nothing_wrong_is_nothing_said(self):
        self.assertIsNone(self.refuse({}))
        self.assertIsNone(self.refuse(None))
        self.assertIsNone(self.refuse({"direct": {"lacks": ["burning"]}}))

    def test_a_state_that_is_missing_is_named(self):
        said = self.refuse({"direct": {"is": ["open"]}})
        self.assertIn("not open", said)
        self.assertIn("Obj", said)

    def test_a_state_it_already_has_is_named(self):
        verbs.apply_states(self.obj1, add=["burning"], world_root=self.root)
        said = self.refuse({"direct": {"lacks": ["burning"]}})
        self.assertIn("already burning", said)

    def test_a_missing_affordance_says_what_the_thing_is_for(self):
        """
        The sentence that answers "then what can I do with it?" without
        costing another attempt. A bottle that cannot be sat on can still be
        drunk from.
        """
        self.obj1.db.affordances = {"drink": True, "break": True}
        said = self.refuse({"direct": {"has": ["read"]}})
        self.assertIn("cannot read", said)
        self.assertIn("drink", said)
        self.assertIn("break", said)

    def test_an_adjective_is_folded_to_the_verb_it_meant(self):
        """
        39 of the first 42 requirements written after the vocabulary changed
        were adjectives, and every one would have been unsatisfiable.
        """
        self.obj1.db.affordances = {"read": True}
        self.assertIsNone(self.refuse({"direct": {"has": ["readable"]}}))

    def test_a_requirement_about_the_actor_says_you(self):
        said = self.refuse({"actor": {"is": ["seated"]}})
        self.assertIn("You are not seated", said)

    def test_holding_a_role_rather_than_a_name(self):
        """"To throw it you must be holding it" -- the thing being thrown."""
        said = self.refuse({"actor": {"holds": ["direct"]}})
        self.assertIn("not holding", said)
        self.obj1.move_to(self.char1, quiet=True)
        self.assertIsNone(self.refuse({"actor": {"holds": ["direct"]}}))

    def test_holding_something_by_name_drops_the_article(self):
        said = self.refuse({"actor": {"holds": ["a brass key"]}})
        self.assertIn("the brass key", said)
        self.assertNotIn("the a brass", said)

    def test_a_clause_written_as_one_word_is_not_read_letter_by_letter(self):
        """
        Asked for one condition a model writes a word, not a list of one.
        Read as written that was six requirements, one per letter, and the
        player was told to fetch "the d".
        """
        said = self.refuse({"actor": {"holds": "direct"}})
        self.assertIn("not holding", said)
        self.assertNotIn(" d.", said)

    def test_a_trait_that_is_not_high_enough(self):
        from world import traits

        traits.ensure(self.char1, "stamina", world_root=self.root, base=2)
        said = self.refuse({"actor": {"trait": {"stamina": {"min": 10}}}})
        self.assertTrue(said)
        self.assertIn("stamina", said.lower())

    def test_a_missing_participant_is_reported_rather_than_crashed(self):
        said = verbs.check({"direct": {"is": ["open"]}}, {}, self.char1,
                           world_root=self.root)
        self.assertTrue(said)

    def test_no_more_than_three_complaints(self):
        """Past two or three a refusal stops being read."""
        said = self.refuse({"direct": {"is": ["open", "lit", "clean",
                                              "dry", "warm"]}})
        self.assertLessEqual(said.count("."), verbs.MAX_COMPLAINTS)

    def test_the_same_requirements_give_the_same_sentence_twice(self):
        """
        Clause order is fixed rather than dictionary order, so a refusal does
        not shuffle between runs.
        """
        requires = {"direct": {"lacks": ["burning"], "is": ["open"],
                               "has": ["read"]}}
        self.assertEqual(self.refuse(requires), self.refuse(requires))

    def test_and_it_leads_with_what_the_thing_is(self):
        """
        Which is the half a player can do something about. What it affords,
        they cannot.
        """
        self.obj1.db.affordances = {}
        said = self.refuse({"direct": {"is": ["open"], "has": ["read"]}})
        self.assertLess(said.index("not open"), said.index("cannot read"))
