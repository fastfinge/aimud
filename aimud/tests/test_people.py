"""
Characters as a sort of thing, and the state nothing ever set.

Two faults found in play, on the first world built with this engine, from one
report: `greet` and `kill` both answered that the character was not alive.

They are not the same fault. A rule required the target to be `alive`, nothing
anywhere sets `alive`, and so every character was refused -- that is the
unsettable-state fault `worldcheck` exists to name, arriving in the one place it
does the most damage. Separately, characters had no kinds at all, which is not
what caused the message but is worth its own fixing: no rule could be filed
against `person.n.01`, the admission question never applied to anybody, and every
character in a world counted as one question to the attempt counters.
"""

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from world import conditions as C
from world import kinds, verbs


@tag("world")
class APersonIsASortOfThing(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root

    def test_a_character_has_a_kind(self):
        self.assertEqual(kinds.of(self.char1), [kinds.PERSON])

    def test_and_one_made_before_people_had_kinds_gets_one(self):
        """
        A world already in play cannot be asked to start again for this, so
        `at_init` fills it in when the object is next loaded.
        """
        self.char1.db.kinds = []
        self.char1.at_init()
        self.assertEqual(kinds.of(self.char1), [kinds.PERSON])

    def test_but_a_character_made_into_something_else_keeps_it(self):
        """First one wins, as for every other kind."""
        self.char1.db.kinds = ["ghost"]
        self.char1.at_init()
        self.assertEqual(kinds.of(self.char1), ["ghost"])

    def test_so_a_rule_can_be_filed_against_people(self):
        from world import rulebooks as R

        R.add(self.root, R.blank(
            action="greet", phase=R.CHECK, scope={"kind": kinds.PERSON},
            about="direct", name="you must be able to see who you greet",
            conditions=[{"subject": "direct", "visible_to": "actor"}]))
        book = R.for_attempt(self.root, "greet", {"direct": self.char2},
                             self.char1)
        self.assertTrue([r for r in book if r["scope"].get("kind")])

    def test_and_the_counters_tell_one_sort_of_person_from_another(self):
        from world import counters

        self.assertEqual(
            counters.scope_of({"direct": self.char2}, self.char1, self.root),
            f"kind:{kinds.PERSON}")


@tag("world")
class BeingAlive(EvenniaTest):
    """
    The fault behind the report. `alive` is in the seeded `life_status` group
    beside `dead`, and nothing anywhere set it -- so a rule asking for it could
    never pass, however long anybody played.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root

    def alive(self, who):
        ctx = C.context({"direct": who}, self.char1, self.root, "greet")
        return C.evaluate({"subject": "direct", "is": ["alive"]}, ctx)

    def test_a_character_nobody_has_killed_is_alive(self):
        self.assertTrue(self.alive(self.char2))

    def test_a_dead_one_is_not(self):
        verbs.apply_states(self.char2, add=["dead"], world_root=self.root)
        self.assertFalse(self.alive(self.char2))

    def test_and_is_alive_again_once_that_is_undone(self):
        """
        No rule needed for the way back. That is what a group default buys, and
        it is the other end of the 45 states in the old corpus that could be set
        and never unset.
        """
        verbs.apply_states(self.char2, add=["dead"], world_root=self.root)
        verbs.apply_states(self.char2, remove=["dead"], world_root=self.root)
        self.assertTrue(self.alive(self.char2))

    def test_lacking_dead_still_works_as_it_did(self):
        ctx = C.context({"direct": self.char2}, self.char1, self.root, "greet")
        self.assertTrue(C.evaluate({"subject": "direct", "lacks": ["dead"]},
                                   ctx))

    def test_being_alive_is_not_written_on_anybody(self):
        """
        Implied rather than stored, on purpose. Storing it would print "Rina is
        alive" under every look, need backfilling on to every character that
        already exists, and drift the first time something forgot to set it.
        """
        self.assertNotIn("alive", verbs.states(self.char2))
        self.assertIn("alive", verbs.implied_states(self.char2, self.root))

    def test_and_so_it_is_never_shown(self):
        self.assertEqual(verbs.condition(self.char2), "")

    def test_a_group_with_no_default_implies_nothing(self):
        self.assertNotIn("wet", verbs.implied_states(self.obj1, self.root))
        self.assertNotIn("seated", verbs.implied_states(self.obj1, self.root))

    def test_another_member_of_the_group_suppresses_the_default(self):
        verbs.apply_states(self.char2, add=["slain"], world_root=self.root)
        self.assertNotIn("alive", verbs.implied_states(self.char2, self.root))

    def test_a_world_may_declare_a_default_of_its_own(self):
        """
        The general mechanism, not a special case for people. A door that starts
        closed is the same shape, and directly attacks the same measured fault.
        """
        verbs.register_state(self.root, "open", means="standing open",
                             group="openness")
        verbs.register_state(self.root, "closed", means="shut",
                             group="openness")
        verbs.register_group(self.root, "openness", default="closed")
        self.assertIn("closed", verbs.implied_states(self.obj1, self.root))

        verbs.apply_states(self.obj1, add=["open"], world_root=self.root)
        self.assertNotIn("closed", verbs.implied_states(self.obj1, self.root))

    def test_it_works_without_a_world_root_in_hand(self):
        """A caller deep in a condition often has the thing and not the world."""
        self.char2.move_to(self.room1, quiet=True)
        self.assertIn("alive", verbs.implied_states(self.char2))


@tag("unit")
class TheDefaultIsPartOfAGroup(SimpleTestCase):

    def test_a_new_group_has_no_default(self):
        self.assertEqual(verbs.NEW_GROUP["default"], "")

    def test_life_status_defaults_to_alive(self):
        self.assertEqual(verbs.STATE_GROUPS["life_status"]["default"], "alive")

    def test_and_it_is_the_only_seeded_group_that_has_one(self):
        """
        Deliberately. The others are real questions a world should answer for
        itself -- a lamp is not obviously unlit and a person is obviously alive.
        """
        withs = [name for name, rules in verbs.STATE_GROUPS.items()
                 if rules.get("default")]
        self.assertEqual(withs, ["life_status"])


@tag("world")
class WhatAdmissionIsAbout(EvenniaTest):
    """
    Giving characters kinds broke every bare verb, and the fix is worth a test
    of its own because the coupling is not obvious.

    `_anchor` falls back to the actor when nothing was named, which is right for
    narration -- a laugh belongs to whoever laughed. `_admitted` used the same
    anchor, which is wrong: "does this sort of thing admit this verb" is a
    question about the object of the verb. It was harmless while characters had
    no kinds, and the moment they had one, `launch` typed bare aboard a ship
    asked whether a person can be launched and was refused before the redirect
    that gives it the ship could run.
    """

    def setUp(self):
        super().setUp()
        from world import attempt as attempt_mod

        self.attempt_mod = attempt_mod
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root

    def test_a_bare_verb_has_nothing_to_ask_about(self):
        self.assertIsNone(self.attempt_mod._anchor({}))

    def test_but_narration_still_belongs_to_whoever_did_it(self):
        self.assertIs(self.attempt_mod._anchor({}, self.char1), self.char1)

    def test_a_named_thing_is_what_admission_asks_about(self):
        self.assertIs(self.attempt_mod._anchor({"direct": self.obj1}),
                      self.obj1)

    def test_and_a_person_named_as_the_object_is_asked_about(self):
        """
        Which is the point of giving people kinds: "can a person be greeted"
        is a real question, asked once and cached for every person after.
        """
        self.assertIs(self.attempt_mod._anchor({"direct": self.char2}),
                      self.char2)

