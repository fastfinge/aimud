"""
What a rule about a verb has to do, declared on the verb.

Guidance was the answer before this and it was not enough. "Combining two
things always produces a new thing" in a world's Rules guidance reaches the
rule writer and does not bind it, and a model that reaches for `narrate`
files "and that is all that happens" -- for that pair, for good, because a
rule is written once per pair of things and kept. One forgetful answer and
combining earth and water is prose for the life of the world.

So a declaration may say what a carry-out rule for the verb is not finished
without, and `rule_gen.validate` sends back a rule that falls short instead of
filing it. It says nothing about *what* is made: that is still the rule's own
answer, and a different one for every pair.
"""

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from world import actions, rule_gen, rulesets
from world import rulebooks as R


@tag("unit")
class TheVocabulary(SimpleTestCase):

    def test_every_entry_names_effects_that_exist(self):
        from world import effects

        for name, said, wanted in actions.MUST:
            with self.subTest(must=name):
                self.assertTrue(wanted, "a requirement nothing satisfies")
                for etype in wanted:
                    self.assertIn(etype, effects.VOCABULARY)
                self.assertGreater(len(said), 10, "say it as a verb phrase")

    def test_names_and_the_table_agree(self):
        self.assertEqual(set(actions.MUSTS),
                         {name for name, _s, _e in actions.MUST})

    def test_an_unknown_one_is_dropped(self):
        self.assertEqual(actions.clean_must(["makes", "juggles"]), ["makes"])

    def test_duplicates_are_dropped(self):
        self.assertEqual(actions.clean_must(["makes", "makes"]), ["makes"])

    def test_it_is_said_as_a_phrase(self):
        self.assertIn("being", actions.said_must("makes"))


@tag("unit")
class DeclaringIt(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root

    def test_a_declaration_carries_it(self):
        actions.declare(self.root, "combine", [{"role": "direct"}],
                        must=["makes"])
        self.assertEqual(actions.must_of(self.root, "combine"), ["makes"])

    def test_a_declaration_without_one_asks_nothing(self):
        actions.declare(self.root, "shrug")
        self.assertEqual(actions.must_of(self.root, "shrug"), [])

    def test_a_verb_nobody_declared_asks_nothing(self):
        self.assertEqual(actions.must_of(self.root, "nonesuch"), [])

    def test_it_can_be_changed_on_a_verb_already_in_use(self):
        """Unlike the arity: this binds rules not yet written."""
        actions.declare(self.root, "combine", [{"role": "direct"}])
        self.assertEqual(actions.set_must(self.root, "combine", ["makes"]),
                         ["makes"])
        self.assertEqual(actions.must_of(self.root, "combine"), ["makes"])

    def test_and_taken_away_again(self):
        actions.declare(self.root, "combine", [{"role": "direct"}],
                        must=["makes"])
        actions.set_must(self.root, "combine", [])
        self.assertEqual(actions.must_of(self.root, "combine"), [])

    def test_setting_it_on_a_verb_that_is_not_declared_does_nothing(self):
        self.assertEqual(actions.set_must(self.root, "nonesuch", ["makes"]),
                         [])

    def test_what_is_unmet(self):
        actions.declare(self.root, "combine", [{"role": "direct"}],
                        must=["makes", "unmakes"])
        self.assertEqual(
            actions.unmet(self.root, "combine",
                          [{"type": "create_object", "name": "mud"}]),
            ["unmakes"])

    def test_nothing_is_unmet_when_both_are_there(self):
        actions.declare(self.root, "combine", [{"role": "direct"}],
                        must=["makes", "unmakes"])
        self.assertEqual(
            actions.unmet(self.root, "combine",
                          [{"type": "create_object", "name": "mud"},
                           {"type": "destroy_object", "name_role": "direct"}]),
            [])

    def test_narrating_meets_nothing(self):
        actions.declare(self.root, "combine", [{"role": "direct"}],
                        must=["makes"])
        self.assertEqual(
            actions.unmet(self.root, "combine", [{"type": "narrate"}]),
            ["makes"])

    def test_an_effect_that_is_not_an_object_is_survived(self):
        actions.declare(self.root, "combine", [{"role": "direct"}],
                        must=["makes"])
        self.assertEqual(actions.unmet(self.root, "combine", ["nonsense"]),
                         ["makes"])


@tag("unit")
class TheRuleWriterIsHeldToIt(GameTest):
    """`rule_gen.validate`, which is the whole point of the flag."""

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        actions.declare(self.root, "combine",
                        [{"role": "direct"}, {"role": "instrument"}],
                        means="to put two things together and see what they "
                              "make",
                        must=["makes"])
        self.offered = [("world", "everywhere", {R.WORLD: True})]

    def keep(self, *rules):
        return rule_gen.validate({"rules": list(rules)}, self.offered,
                                 "combine", self.root)

    def carrying_out(self, *effects):
        return {"phase": "carry_out", "scope": "world",
                "name": "combining makes something",
                "effects": list(effects)}

    def test_a_rule_that_only_narrates_is_refused(self):
        kept, complaints = self.keep(self.carrying_out({"type": "narrate"}))
        self.assertEqual(kept, [])
        self.assertEqual(len(complaints), 1)
        self.assertIn("combine", complaints[0])
        self.assertIn("being", complaints[0])

    def test_a_rule_that_makes_something_is_kept(self):
        kept, complaints = self.keep(self.carrying_out(
            {"type": "create_object", "name": "mud"}))
        self.assertEqual(complaints, [])
        self.assertEqual(len(kept), 1)

    def test_another_kind_of_change_is_not_enough(self):
        kept, _c = self.keep(self.carrying_out(
            {"type": "set_state", "role": "direct", "add": ["wet"]}))
        self.assertEqual(kept, [])

    def test_a_check_rule_is_not_asked_to_make_anything(self):
        """Checks only ever refuse; the requirement is about the act."""
        kept, complaints = self.keep(
            {"phase": "check", "scope": "world",
             "name": "both must be carried",
             "conditions": [{"subject": "actor", "holds": "direct"}]})
        self.assertEqual(complaints, [])
        self.assertEqual(len(kept), 1)

    def test_an_instead_rule_is_not_either(self):
        """It says the verb means something else, and leaves the doing there."""
        kept, complaints = self.keep(
            {"phase": "instead", "scope": "world", "name": "combining mixes",
             "effects": [{"type": "try", "action": "mix"}]})
        self.assertEqual(complaints, [])
        self.assertEqual(len(kept), 1)

    def test_a_verb_that_asks_nothing_may_narrate(self):
        actions.declare(self.root, "shrug")
        kept, complaints = rule_gen.validate(
            {"rules": [{"phase": "carry_out", "scope": "world",
                        "name": "shrugging is seen",
                        "effects": [{"type": "narrate"}]}]},
            self.offered, "shrug", self.root)
        self.assertEqual(complaints, [])
        self.assertEqual(len(kept), 1)

    def test_the_complaint_says_what_to_do(self):
        _kept, complaints = self.keep(self.carrying_out({"type": "narrate"}))
        self.assertIn("not finished", complaints[0])

    def test_the_prompt_says_it_before_the_first_try(self):
        said = rule_gen.prompt(self.root, "combine", {}, self.char1,
                               self.offered)
        self.assertIn("must bring something new into being", said)

    def test_a_verb_that_asks_nothing_says_nothing_in_the_prompt(self):
        actions.declare(self.root, "shrug")
        said = rule_gen.prompt(self.root, "shrug", {}, self.char1,
                               self.offered)
        self.assertNotIn("carry_out rule for it must", said)


@tag("unit")
class CraftingAsksForIt(GameTest):
    """
    The ruleset whose own sentence is that things can be made out of things.

    Shipped on the declaration rather than left to each world, because the
    report this came from was a crafting world: the guidance was written, the
    model read it, and the rule it filed still changed nothing.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root

    def test_combining_and_making_both_ask(self):
        rulesets.apply_choice(self.root, ["default", "crafting"])
        self.assertEqual(actions.must_of(self.root, "combine"), ["makes"])
        self.assertEqual(actions.must_of(self.root, "make"), ["makes"])

    def test_the_document_is_valid(self):
        self.assertEqual(rulesets.problems(rulesets.get("crafting")), [])

    def test_a_requirement_nothing_knows_is_refused(self):
        doc = dict(rulesets.get("crafting"))
        doc["actions"] = [{"action": "combine", "must": ["juggles"]}]
        self.assertTrue(any("juggles" in said
                            for said in rulesets.problems(doc)))

    def test_a_world_may_take_it_off_again(self):
        rulesets.apply_choice(self.root, ["default", "crafting"])
        actions.set_must(self.root, "combine", [])
        self.assertEqual(actions.must_of(self.root, "combine"), [])


@tag("unit")
class TheBuilderSideOfIt(GameTest):
    """
    Declaring it by hand, reading it back, and being told when a rule falls
    short of it.

    The rule form *says* rather than refuses, which is the standing rule for
    everything at the end of that form: the person reading the note is the one
    who declared the requirement, and a builder who knows what they are doing
    is allowed to write the rule anyway.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root

    def draft(self, **fields):
        from tests.test_building import _Draft

        return _Draft(fields, self.root, self.char1)

    def test_the_action_form_declares_it(self):
        from world.makers import doing

        word, _said = doing.keep_action(self.draft(
            action="combine", means="to put two things together",
            applies_to=[{"role": "direct", "access": "carried"}],
            must=["makes"]))
        self.assertEqual(actions.must_of(self.root, word), ["makes"])

    def test_the_form_reads_a_name_it_does_not_know(self):
        from world.makers import doing

        value, complaint = doing._read_must("makes juggles")
        self.assertIsNone(value)
        self.assertIn("juggles", complaint)

    def test_and_reads_one_it_does(self):
        from world.makers import doing

        value, complaint = doing._read_must("makes unmakes")
        self.assertEqual(value, ["makes", "unmakes"])
        self.assertEqual(complaint, "")

    def test_edit_action_can_turn_it_on_afterwards(self):
        """Which is when a world wants it: after reading a rule that did nothing."""
        from world.makers import doing

        actions.declare(self.root, "combine", [{"role": "direct"}])
        form = doing.edit_action(self.root, "combine")
        field = [item for item in form.items if item.key == "must"][0]
        field.set(self.draft(), ["makes"])
        self.assertEqual(actions.must_of(self.root, "combine"), ["makes"])

    def test_view_action_says_what_is_asked(self):
        from commands.rules_subject import one_verb

        actions.declare(self.root, "combine", [{"role": "direct"}],
                        must=["makes"])
        self.assertIn("must bring something new into being",
                      one_verb(self.root, "combine"))

    def test_view_action_is_quiet_when_nothing_is_asked(self):
        from commands.rules_subject import one_verb

        actions.declare(self.root, "shrug")
        self.assertNotIn("carry out rule for it must",
                         one_verb(self.root, "shrug"))

    def test_the_rule_form_says_when_a_rule_falls_short(self):
        from world.makers import rules

        actions.declare(self.root, "combine", [{"role": "direct"}],
                        must=["makes"])
        said = rules.phase_nudge(self.draft(
            phase="carry_out", action="combine",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["mixed"]}]))
        self.assertIn("always bring something new into being", said)
        self.assertIn("yours is kept", said)

    def test_and_is_quiet_when_it_does_not(self):
        from world.makers import rules

        actions.declare(self.root, "combine", [{"role": "direct"}],
                        must=["makes"])
        said = rules.phase_nudge(self.draft(
            phase="carry_out", action="combine",
            effects=[{"type": "create_object", "name": "mud"}]))
        self.assertNotIn("always bring", said)
