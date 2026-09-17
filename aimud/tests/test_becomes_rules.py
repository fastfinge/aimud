"""
Rules that run because something became true.

"When a person's health becomes at most 0, they are dead" is one rule, filed
once, and not a line inside every verb that can hurt somebody. The door that
makes a change takes the before; settling asks again and fires what went from
false to true. See docs/becoming-and-time.md §6 and world/becoming.py.
"""

from unittest import mock

from django.test import SimpleTestCase, tag

from tests import test_phases
from tests.base import GameTest
from world import becoming, rulecheck, traits, verbs
from world import rulebooks as R


class BecomingTest(GameTest):
    loose_objects = 1

    def setUp(self):
        super().setUp()
        becoming.forget_waiting()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root

    def tearDown(self):
        becoming.forget_waiting()
        super().tearDown()

    def becomes(self, when, effects=(), scope=None, name="", report="",
                about="direct"):
        return R.add(self.root, R.blank(
            phase=R.BECOMES, scope=scope or {"world": True}, about=about,
            name=name, when=when, effects=list(effects), report=report))

    def health(self, who, figure):
        traits.adjust(who, "health", set_to=figure, world_root=self.root,
                      announce=False)
        becoming.settle()

    def dying(self, **extra):
        return self.becomes(
            [{"subject": "direct", "trait": "health", "max": 0}],
            [{"type": "set_state", "role": "direct", "add": ["dead"]}],
            name="no health left is dead", **extra)


@tag("world")
class WhenSomethingBecomesTrue(BecomingTest):

    def test_it_fires_when_the_condition_becomes_true(self):
        self.dying()
        self.health(self.char1, 10)
        self.assertNotIn("dead", verbs.states(self.char1))
        self.health(self.char1, 0)
        self.assertIn("dead", verbs.states(self.char1))

    def test_and_not_again_while_it_stays_true(self):
        self.becomes([{"subject": "direct", "trait": "health", "max": 0}],
                     [{"type": "set_trait", "trait": "deaths", "change": 1}])
        self.health(self.char1, 10)
        self.health(self.char1, 0)
        self.health(self.char1, -5)
        self.assertEqual(traits.value(self.char1, "deaths"), 1)

    def test_a_rule_added_later_waits_for_a_change(self):
        """Nothing crossed, so nothing fired: a new rule is not retroactive."""
        self.health(self.char1, 0)
        self.dying()
        becoming.settle()
        self.assertNotIn("dead", verbs.states(self.char1))

    def test_a_becomes_rule_is_never_part_of_an_attempt(self):
        self.dying()
        self.assertEqual(R.gather(self.root, "read", {}, self.char1), [])
        self.assertEqual(len(R.gather(self.root, "", {}, self.char1,
                                      phase=R.BECOMES, guarded=False)), 1)

    def test_it_is_filed_with_no_action_and_its_report_repaired(self):
        rule = self.dying(report="{direct} $pconj(collapse).")
        self.assertIsNone(rule["action"])
        self.assertEqual(rule["phase"], R.BECOMES)
        self.assertTrue(rule["report"])

    def test_settling_waits_while_something_is_being_done(self):
        self.dying()
        self.health(self.char1, 10)
        with becoming.caused_by(self.char1):
            traits.adjust(self.char1, "health", set_to=0,
                          world_root=self.root, announce=False)
            becoming.settle()
            self.assertNotIn("dead", verbs.states(self.char1))
        becoming.settle()
        self.assertIn("dead", verbs.states(self.char1))


@tag("world")
class StoppingBeing(BecomingTest):
    """A falling edge is the rising edge of the negation, and needs no syntax."""

    def setUp(self):
        super().setUp()
        self.becomes([{"subject": "direct", "lacks": ["boiling"]}],
                     [{"type": "set_state", "role": "direct",
                       "add": ["settled"]}], name="it stops boiling")

    def test_it_fires_when_the_thing_stops(self):
        verbs.apply_states(self.obj1, add=["boiling"], world_root=self.root)
        becoming.settle()
        self.assertNotIn("settled", verbs.states(self.obj1))
        verbs.apply_states(self.obj1, remove=["boiling"], world_root=self.root)
        becoming.settle()
        self.assertIn("settled", verbs.states(self.obj1))

    def test_and_never_for_a_thing_that_never_was(self):
        verbs.apply_states(self.obj1, add=["wet"], world_root=self.root)
        becoming.settle()
        self.assertNotIn("settled", verbs.states(self.obj1))


@tag("world")
class TheyAddAndChain(BecomingTest):

    def test_the_phoenix_dies_and_then_rises(self):
        self.dying()
        self.becomes(
            [{"subject": "direct", "is": ["dead"]}],
            [{"type": "set_state", "role": "direct", "remove": ["dead"]},
             {"type": "set_trait", "role": "direct", "trait": "health",
              "set_to": 10}],
            scope={"object": self.char1.id}, name="the phoenix rises")
        self.health(self.char1, 10)
        self.health(self.char1, 0)
        self.assertNotIn("dead", verbs.states(self.char1))
        self.assertEqual(traits.value(self.char1, "health"), 10)
        # And both are ready for the next death.
        self.health(self.char1, 0)
        self.assertEqual(traits.value(self.char1, "health"), 10)

    def test_the_specific_rule_has_the_last_word(self):
        edge = [{"subject": "direct", "is": ["struck"]}]
        self.becomes(edge, [{"type": "set_trait", "role": "direct",
                             "trait": "mark", "set_to": 1}], name="general")
        self.becomes(edge, [{"type": "set_trait", "role": "direct",
                             "trait": "mark", "set_to": 2}],
                     scope={"object": self.char1.id}, name="specific")
        verbs.apply_states(self.char1, add=["struck"], world_root=self.root)
        becoming.settle()
        self.assertEqual(traits.value(self.char1, "mark"), 2)

    def test_a_chain_that_does_not_end_is_stopped_and_counted(self):
        ids = []
        for step in range(1, 7):
            rule = self.becomes(
                [{"subject": "direct", "is": [f"stage{step}"]}],
                [{"type": "set_state", "role": "direct",
                  "add": [f"stage{step + 1}"]}], name=f"step {step}")
            ids.append(rule["id"])
        verbs.apply_states(self.obj1, add=["stage1"], world_root=self.root)
        becoming.settle()
        counted = dict(self.root.db.becomes_overflow or {})
        self.assertEqual(list(counted), [ids[becoming.MAX_PASSES - 1]])
        self.assertEqual(becoming.waiting(), 0)


@tag("world")
class WhoCausedIt(BecomingTest):
    characters = 2

    def setUp(self):
        super().setUp()
        self.becomes(
            [{"subject": "direct", "trait": "health", "max": 0},
             {"subject": "cause", "unbound": False}],
            [{"type": "set_trait", "role": "cause", "trait": "renown",
              "change": 1}], name="a killing is remembered")
        self.health(self.char1, 10)

    def blow(self, figure):
        with becoming.caused_by(self.char2):
            traits.adjust(self.char1, "health", set_to=figure,
                          world_root=self.root, announce=False)
        becoming.settle()

    def test_whoever_did_it_is_the_cause(self):
        self.blow(0)
        self.assertEqual(traits.value(self.char2, "renown"), 1)

    def test_striking_a_body_that_is_already_at_nought_is_not_a_second_kill(self):
        self.blow(0)
        self.blow(-3)
        self.assertEqual(traits.value(self.char2, "renown"), 1)

    def test_a_death_nobody_caused_credits_nobody(self):
        self.health(self.char1, 0)
        self.assertIsNone(traits.value(self.char2, "renown"))

    def test_a_cause_given_when_settling_fills_one_not_yet_known(self):
        traits.adjust(self.char1, "health", set_to=0, world_root=self.root,
                      announce=False)
        becoming.settle(cause=self.char2)
        self.assertEqual(traits.value(self.char2, "renown"), 1)


@tag("world")
class WhatIsSaid(BecomingTest):

    def test_the_report_is_read_by_the_one_it_happened_to(self):
        self.dying(report="{direct} $pconj(collapse) to the ground.")
        self.health(self.char1, 10)
        with mock.patch.object(self.char1, "msg") as told:
            self.health(self.char1, 0)
        said = " ".join(str(call.args[0]) for call in told.call_args_list
                        if call.args)
        self.assertIn("collapse to the ground", said)

    def test_a_report_naming_nobody_is_held_back(self):
        self.dying(report="{direct} $pconj(fall), struck down by {cause}.")
        self.health(self.char1, 10)
        with mock.patch.object(self.char1, "msg") as told:
            self.health(self.char1, 0)
        said = " ".join(str(call.args[0]) for call in told.call_args_list
                        if call.args)
        self.assertNotIn("{cause}", said)
        self.assertIn("dead", verbs.states(self.char1))


@tag("world")
class NarrationComesFirst(BecomingTest):

    def test_what_became_true_is_said_after_what_was_done(self):
        """
        The blow is described, and then the character collapses -- because
        settling happens when the attempt releases its narration, whenever
        that narration arrives.
        """
        from world import attempt

        self.dying(report="{direct} $pconj(collapse) to the ground.")
        self.health(self.char1, 10)
        heard = []
        with mock.patch.object(self.char1, "msg",
                               side_effect=lambda text=None, **kw:
                               heard.append(str(text))):
            with becoming.caused_by(self.char1):
                traits.adjust(self.char1, "health", set_to=0,
                              world_root=self.root, announce=False)
            self.assertEqual(heard, [])
            attempt._release(self.char1,
                             lambda text, event=None: heard.append(text),
                             "The blow lands.")
        self.assertEqual(heard[0], "The blow lands.")
        self.assertIn("collapse", " ".join(heard[1:]))


@tag("world")
class ThroughAnAttempt(test_phases.RunningTheAttempt):

    def setUp(self):
        super().setUp()
        becoming.forget_waiting()

    def tearDown(self):
        becoming.forget_waiting()
        super().tearDown()

    def test_a_rule_fires_when_the_attempt_is_done_and_after_its_narration(self):
        R.add(self.root, R.blank(
            action="read", phase=R.CARRY_OUT, scope={"world": True},
            name="reading wears a book",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["worn"]}]))
        R.add(self.root, R.blank(
            phase=R.BECOMES, scope={"world": True}, name="a worn book frays",
            when=[{"subject": "direct", "is": ["worn"]}],
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["frayed"]}],
            report="{direct} $pconj(begin) to fray."))
        heard = []
        with mock.patch.object(self.char1, "msg",
                               side_effect=lambda text=None, **kw:
                               heard.append(("room", str(text)))):
            said = self.try_it("read book")
        self.assertIn("frayed", verbs.states(self.obj1))
        self.assertIn("You do it", said)
        self.assertTrue(any("fray" in line for _where, line in heard))


@tag("world")
class Listing(BecomingTest):

    def test_they_are_listed_in_the_order_they_fire(self):
        from commands.rules_subject import changing_lines

        general = self.becomes([{"subject": "direct", "is": ["struck"]}],
                               [{"type": "narrate"}], name="general")
        specific = self.becomes([{"subject": "direct", "is": ["struck"]}],
                                [{"type": "narrate"}], name="specific",
                                scope={"object": self.char1.id})
        lines = "\n".join(changing_lines(self.root, [specific, general]))
        self.assertLess(lines.index("general"), lines.index("specific"))


@tag("unit")
class ACauseNobodyAskedFor(SimpleTestCase):

    def book(self, guarded):
        when = [{"subject": "direct", "trait": "health", "max": 0}]
        if guarded:
            when.append({"subject": "cause", "unbound": False})
        return {"r1": {"id": "r1", "phase": "becomes", "name": "renown",
                       "when": when,
                       "effects": [{"type": "set_trait", "role": "cause",
                                    "trait": "renown", "change": 1}]}}

    def test_it_is_found(self):
        self.assertEqual(rulecheck.cause_unguarded(self.book(False)),
                         [("r1", "renown")])

    def test_and_the_guard_answers_it(self):
        self.assertEqual(rulecheck.cause_unguarded(self.book(True)), [])
