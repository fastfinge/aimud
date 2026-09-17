"""
Things a rule makes, worked out once by the item generator.

A rule names what `create_object` makes and why. What sort of thing that is --
its kind, what can be done with it, what it looks like -- is asked of the item
generator once, when the rule is filed, with the rule as the reason, and kept
on the rule. Firing it builds the same thing every time and asks nothing.
"""

from unittest import mock

from django.test import tag

from tests.base import GameTest
from tests.support import FakeSponsor, finishing, immediately, replying
from world import effects, item_gen, llm, rule_gen, verbs
from world import rulebooks as R

LOAF = {"name": "Crusty Loaf", "description": "A round loaf, still warm.",
        "kind": "loaf", "affordances": {"eat": True}, "takeable": True}


class RuleItemTest(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_root = self.root

    def baking(self, **extra):
        effect = {"type": "create_object", "name": "loaf of bread",
                  "why": "what baking makes", "location": "actor"}
        effect.update(extra)
        return R.add(self.root, R.blank(
            action="bake", phase=R.CARRY_OUT, name="baking makes bread",
            effects=[effect]))


@tag("world")
class AskingWhatAThingIs(RuleItemTest):

    def test_a_spec_is_answered_and_nothing_is_made(self):
        from evennia.objects.models import ObjectDB

        before = ObjectDB.objects.count()
        answered = []
        with immediately(), replying(finishing(make_item=LOAF)):
            item_gen.ask_for_item(FakeSponsor(), "loaf of bread",
                                  answered.append, answered.append,
                                  world_root=self.root)
        self.assertEqual(ObjectDB.objects.count(), before)
        self.assertEqual(answered[0]["kind"], "loaf")

    def test_a_rules_thing_is_asked_about_as_the_rules_thing(self):
        wanted = item_gen.Wanted(verb="bake", role="made",
                                 made_by="baking makes bread",
                                 why="what baking makes")
        with immediately(), replying(finishing(make_item=LOAF)) as recorder:
            item_gen.ask_for_item(FakeSponsor(), "loaf of bread",
                                  lambda spec: None, lambda why: None,
                                  world_root=self.root, wanted=wanted)
        prompt = "\n".join(m["content"] for m in recorder.prompts[0]
                           if m["role"] == "user")
        self.assertIn("made by this world's rule \"baking makes bread\"",
                      prompt)
        self.assertIn("what baking makes", prompt)
        self.assertIn("Generate the item this rule makes", prompt)


@tag("world")
class FillingInARule(RuleItemTest):

    def test_the_answer_is_kept_on_the_rule_and_the_name_is_not_changed(self):
        rule = self.baking()
        with immediately(), replying(finishing(make_item=LOAF)):
            rule_gen.flesh_out(FakeSponsor(), self.root, [rule])
        effect = R.get(self.root, rule["id"])["effects"][0]
        self.assertEqual(effect["name"], "loaf of bread")
        self.assertEqual(effect["kind"], "loaf")
        self.assertEqual(dict(effect["affordances"]), {"eat": True})
        self.assertEqual(effect["description"], "A round loaf, still warm.")
        self.assertEqual(effect["location"], "actor")

    def test_a_description_the_rule_wrote_is_kept(self):
        rule = self.baking(description="A flat grey loaf.")
        with immediately(), replying(finishing(make_item=LOAF)):
            rule_gen.flesh_out(FakeSponsor(), self.root, [rule])
        effect = R.get(self.root, rule["id"])["effects"][0]
        self.assertEqual(effect["description"], "A flat grey loaf.")
        self.assertEqual(effect["kind"], "loaf")

    def test_firing_it_builds_that_thing_and_asks_nothing(self):
        rule = self.baking()
        with immediately(), replying(finishing(make_item=LOAF)):
            rule_gen.flesh_out(FakeSponsor(), self.root, [rule])
        stored = R.get(self.root, rule["id"])
        with mock.patch.object(llm, "converse") as asked:
            effects.apply(self.char1, self.room1, stored["effects"],
                          world_root=self.root)
        asked.assert_not_called()
        loaf = [obj for obj in self.char1.contents
                if obj.key == "loaf of bread"][0]
        self.assertIn("eat", verbs.affordances(loaf))

    def test_an_unanswered_question_leaves_the_rule_as_it_was(self):
        rule = self.baking()
        with immediately(), replying(llm.LLMError("no route")):
            rule_gen.flesh_out(FakeSponsor(), self.root, [rule])
        effect = R.get(self.root, rule["id"])["effects"][0]
        self.assertTrue(R.thin_creation(effect))

    def test_a_thing_already_described_is_not_asked_about(self):
        rule = self.baking(kind="loaf", affordances={"eat": True})
        with mock.patch.object(item_gen, "ask_for_item") as asked:
            rule_gen.flesh_out(FakeSponsor(), self.root, [rule])
        asked.assert_not_called()


@tag("world")
class WhenARuleIsLearned(RuleItemTest):

    def test_learning_a_rule_that_makes_something_fills_it_in(self):
        reply = finishing(file_rules={"rules": [{
            "phase": "carry_out", "scope": "world",
            "name": "baking makes bread",
            "effects": [{"type": "create_object", "name": "loaf of bread",
                         "why": "what baking makes"}]}]})
        learned = []
        with immediately(), replying(reply, finishing(make_item=LOAF)):
            rule_gen.learn(FakeSponsor(), self.root, "bake", {}, self.char1,
                           learned.extend, learned.append)
        baking = [rule for rule in R.all_rules(self.root)
                  if rule.get("action") == "bake"]
        self.assertEqual(len(baking), 1)
        self.assertEqual(baking[0]["effects"][0]["kind"], "loaf")
