"""
After rules that can ask how things came out.

An after rule's `when` used to be tested with the rest of the book, before
carry-out ran, so a guard about the result was answered about the world as it
was: "after reading, when the book is worn" never fired, and "when it is not
worn" always did. Guards are tested after carry-out now, all together and
before any after rule lands. See docs/becoming-and-time.md 6.8.
"""

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from tests import test_phases
from world import conditions as C
from world import rulebooks as R
from world import rulecheck, traits, verbs


@tag("world")
class AGuardSeesWhatHappened(test_phases.RunningTheAttempt):

    def reading_wears_it(self):
        R.add(self.root, R.blank(
            action="read", phase=R.CARRY_OUT, scope={"world": True},
            name="reading wears a book",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["worn"]}]))

    def after_reading(self, when, add):
        R.add(self.root, R.blank(
            action="read", phase=R.AFTER, scope={"world": True},
            name=f"then {add}", when=when,
            effects=[{"type": "set_state", "role": "direct", "add": [add]}]))

    def test_a_guard_on_the_result_is_met_by_the_result(self):
        self.reading_wears_it()
        self.after_reading([{"subject": "direct", "is": ["worn"]}],
                           "dog_eared")
        self.try_it("read book")
        self.assertIn("dog_eared", verbs.states(self.obj1))

    def test_a_guard_against_the_result_is_not(self):
        self.reading_wears_it()
        self.after_reading([{"subject": "direct", "lacks": ["worn"]}],
                           "pristine")
        self.try_it("read book")
        self.assertNotIn("pristine", verbs.states(self.obj1))

    def test_one_after_rule_does_not_set_another_going(self):
        """
        Guards are tested together, before any of them lands. The second rule
        is waiting on what the first one does, and must not see it.
        """
        self.after_reading([], "marked")
        self.after_reading([{"subject": "direct", "is": ["marked"]}],
                           "stained")
        self.try_it("read book")
        self.assertIn("marked", verbs.states(self.obj1))
        self.assertNotIn("stained", verbs.states(self.obj1))

    def test_a_participant_carry_out_destroyed_is_gone(self):
        R.add(self.root, R.blank(
            action="read", phase=R.CARRY_OUT, scope={"world": True},
            name="the book crumbles as it is read",
            effects=[{"type": "destroy_object", "name_role": "direct"}]))
        R.add(self.root, R.blank(
            action="read", phase=R.AFTER, scope={"world": True},
            name="and the reader is shaken", about="actor",
            when=[{"subject": "direct", "gone": True}],
            effects=[{"type": "set_trait", "trait": "composure",
                      "change": -1}]))
        self.try_it("read book")
        self.assertIsNone(self.obj1.pk)
        self.assertEqual(traits.value(self.char1, "composure"), -1)


@tag("world")
class HereIsWhereItHappened(GameTest):
    second_room = True

    def test_here_is_the_room_asked_about_not_where_the_actor_went(self):
        verbs.apply_states(self.room1, add=["bridge"])
        self.char1.move_to(self.room2, quiet=True)
        condition = {"subject": "here", "is": ["bridge"]}
        self.assertFalse(C.evaluate(condition, C.context({}, self.char1)))
        self.assertTrue(C.evaluate(condition,
                                   C.context({}, self.char1, room=self.room1)))


@tag("unit")
class AnAfterRuleThatCanNeverFire(SimpleTestCase):

    def book(self, forbids):
        return {"rules": {
            "r1": {"id": "r1", "phase": "carry_out", "action": "light",
                   "effects": [{"type": "set_state", "role": "direct",
                                "add": ["lit"]}]},
            "r2": {"id": "r2", "phase": "after", "action": "light",
                   "name": "then it smokes",
                   "when": [{"subject": "direct", "lacks": [forbids]}],
                   "effects": [{"type": "set_state", "role": "direct",
                                "add": ["smoking"]}]},
        }}

    def test_a_guard_forbidding_what_its_verb_makes_is_found(self):
        found = rulecheck.scan(self.book("lit"))["after_self_defeating"]
        self.assertEqual(found, [("r2", "light", ["lit"], "then it smokes")])

    def test_a_guard_forbidding_something_else_is_not(self):
        self.assertEqual(
            rulecheck.scan(self.book("wet"))["after_self_defeating"], [])

    def test_the_report_says_so(self):
        said = rulecheck.report(rulecheck.scan(self.book("lit")))
        self.assertIn("after rules follow only when", said)
