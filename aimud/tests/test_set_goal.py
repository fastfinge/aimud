"""
A rule can give somebody something to work towards.

The half a world with no model was missing. A character's goal was reachable
three ways and every one of them needed a model: it set one for itself out of
what it had just said, it accepted an errand somebody offered, or the dialogue
model decided. So `ask apprentice for steam` could be *matched* by a rule --
`called` sees the word whether or not any steam exists -- and the rule had no
way to finish the sentence.

Nothing here plans and nothing here is paid for. The goal is a list of
conditions the planner already knows how to test and to work backwards from,
so a world that has settled that combining fire and water makes steam already
holds the step: "steam exists" is a purpose the apprentice can actually get to.
"""

from django.test import tag

from tests.base import GameTest
from world import actions, effects, goals, rulebooks


def _asking(what):
    """"Ask the apprentice for steam", as a rule."""
    return {
        "name": f"asking for {what}",
        "phase": rulebooks.CARRY_OUT,
        "action": "ask",
        "scope": {rulebooks.WORLD: True},
        "when": [{"subject": "target", "called": what}],
        "effects": [{"type": "set_goal", "role": "direct",
                     "goal": [{"type": "exists", "object": what}]}],
    }


@tag("world")
class SettingOne(GameTest):
    characters = 2

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.char2.db.is_npc = True

    def apply(self, effect, **bound):
        return effects.apply(self.char1, self.room1, [effect],
                             bound=bound or {"direct": self.char2},
                             world_root=self.root)

    def test_it_lands_on_the_character(self):
        self.apply({"type": "set_goal", "role": "direct",
                    "goal": [{"type": "exists", "object": "steam"}]})
        self.assertEqual(self.char2.db.goal,
                         [{"type": "exists", "object": "steam"}])

    def test_it_says_so(self):
        said = self.apply({"type": "set_goal", "role": "direct",
                           "goal": [{"type": "exists", "object": "steam"}]})
        self.assertEqual(said, [f"{self.char2.key} sets about it."])

    def test_a_stalled_count_starts_again(self):
        self.char2.db.goal_stalls = 4
        self.apply({"type": "set_goal", "role": "direct",
                    "goal": [{"type": "exists", "object": "steam"}]})
        self.assertEqual(self.char2.db.goal_stalls, 0)

    def test_a_goal_it_was_waiting_on_is_dropped(self):
        self.char2.db.goal_waiting = {"until": 999}
        self.apply({"type": "set_goal", "role": "direct",
                    "goal": [{"type": "exists", "object": "steam"}]})
        self.assertIsNone(self.char2.db.goal_waiting)

    def test_the_goal_is_held_to_what_can_be_tested(self):
        self.apply({"type": "set_goal", "role": "direct",
                    "goal": [{"type": "nonsense", "object": "steam"},
                             {"type": "exists", "object": "steam"}]})
        self.assertEqual(self.char2.db.goal,
                         [{"type": "exists", "object": "steam"}])

    def test_a_goal_with_nothing_testable_sets_none(self):
        said = self.apply({"type": "set_goal", "role": "direct",
                           "goal": [{"type": "nonsense"}]})
        self.assertEqual(said, [])
        self.assertFalse(self.char2.db.goal)

    def test_a_goal_with_nothing_in_it_sets_none(self):
        self.assertEqual(
            self.apply({"type": "set_goal", "role": "direct", "goal": []}), [])
        self.assertFalse(self.char2.db.goal)

    def test_nobody_in_that_role_does_nothing(self):
        self.assertEqual(
            self.apply({"type": "set_goal", "role": "instrument",
                        "goal": [{"type": "exists", "object": "steam"}]}), [])

    def test_a_player_is_not_given_one(self):
        """Nothing plans for a player, so a goal on one would sit unread."""
        said = self.apply({"type": "set_goal", "role": "direct",
                           "goal": [{"type": "exists", "object": "steam"}]},
                          direct=self.char1)
        self.assertEqual(said, [])
        self.assertFalse(self.char1.db.goal)

    def test_an_errand_already_promised_is_not_thrown_over(self):
        self.char2.db.goal = [{"type": "exists", "object": "rope"}]
        self.char2.db.goal_from_quest = "q1"
        said = self.apply({"type": "set_goal", "role": "direct",
                           "goal": [{"type": "exists", "object": "steam"}]})
        self.assertEqual(said, [])
        self.assertEqual(self.char2.db.goal,
                         [{"type": "exists", "object": "rope"}])

    def test_but_a_goal_of_its_own_is(self):
        self.char2.db.goal = [{"type": "exists", "object": "rope"}]
        self.apply({"type": "set_goal", "role": "direct",
                    "goal": [{"type": "exists", "object": "steam"}]})
        self.assertEqual(self.char2.db.goal,
                         [{"type": "exists", "object": "steam"}])

    def test_the_actor_may_be_the_one_set(self):
        self.char1.db.is_npc = True
        self.apply({"type": "set_goal", "role": "actor",
                    "goal": [{"type": "exists", "object": "steam"}]})
        self.assertTrue(self.char1.db.goal)


@tag("unit")
class ReadingItBack(GameTest):
    """What `view rules`, `help` and the effect listing say about one."""

    def test_it_reads_as_a_sentence(self):
        said = effects.say({"type": "set_goal", "role": "direct",
                            "goal": [{"type": "exists", "object": "steam"}]})
        self.assertIn("steam", said)
        self.assertIn("what you act on", said)

    def test_a_purposeless_one_still_reads(self):
        said = effects.say({"type": "set_goal", "role": "direct"})
        self.assertIn("purpose", said)

    def test_it_is_in_the_register(self):
        self.assertIn("set_goal", effects.VOCABULARY)
        self.assertEqual(effects.VOCABULARY["set_goal"]["fields"],
                         ("role", "goal"))

    def test_it_is_not_read_backwards(self):
        """Handing somebody a want changes nothing, so it achieves nothing."""
        self.assertFalse(effects.VOCABULARY["set_goal"]["backwards"])

    def test_a_model_is_not_offered_the_goal_field(self):
        """
        Withheld, not forgotten. A goal is a list of spelled-out conditions,
        and this schema already sits inside a list of effects inside a list of
        rules: three deep is what Google refuses outright on the call that
        names the tool it must use, which is the last round of every loop.
        See tests/test_schema_portability.py.
        """
        self.assertNotIn("goal", effects.schema()["properties"])

    def test_but_can_name_an_errand(self):
        """`offer_quest` read `quest` and the schema never offered it."""
        said = effects.schema()
        self.assertIn("quest", said["properties"])

    def test_a_model_that_reaches_for_it_is_told(self):
        """
        The only shape a model could write is an empty one, and an empty
        purpose does nothing for ever. Sent back, with what to do instead.
        """
        from world import rule_gen

        kept, complaints = rule_gen.validate(
            {"rules": [{"phase": "carry_out", "scope": "world",
                        "name": "asking sets them to it",
                        "effects": [{"type": "set_goal", "role": "direct"}]}]},
            [("world", "everywhere", {rulebooks.WORLD: True})], "ask")
        self.assertEqual(kept, [])
        self.assertIn("no goal in it", complaints[0])


@tag("world")
class AskingForSomething(GameTest):
    """
    The whole sentence, end to end: `ask apprentice for steam`.

    What makes it work is three pieces meeting. `called` finds the rule from
    the word, with no steam in the world to find it by; `set_goal` hands the
    apprentice the purpose; and the planner reads the world's own combining
    rule backwards to get there. None of it calls a model.
    """

    characters = 2

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room1.db.is_ai_room = True
        self.char2.db.is_npc = True
        self.char2.key = "apprentice"
        actions.declare(self.root, "ask", [
            {"role": "direct", "access": "visible"},
            {"role": "target", "access": "visible", "optional": True}])

    def test_the_rule_is_reached_and_the_goal_is_set(self):
        from world import conditions

        rulebooks.add(self.root, _asking("steam"))
        book = rulebooks.for_attempt(
            self.root, "ask", {"direct": self.char2}, self.char1,
            phase=rulebooks.CARRY_OUT, words={"target": "steam"})
        self.assertEqual([r["name"] for r in book], ["asking for steam"])

        effects.apply(self.char1, self.room1, book[0]["effects"],
                      bound={"direct": self.char2}, world_root=self.root)
        self.assertEqual(self.char2.db.goal,
                         [{"type": "exists", "object": "steam"}])

    def test_asking_for_something_else_reaches_its_own_rule(self):
        rulebooks.add(self.root, _asking("steam"))
        rulebooks.add(self.root, _asking("mud"))
        book = rulebooks.for_attempt(
            self.root, "ask", {"direct": self.char2}, self.char1,
            phase=rulebooks.CARRY_OUT, words={"target": "mud"})
        self.assertEqual([r["name"] for r in book], ["asking for mud"])

    def test_the_goal_is_not_yet_met(self):
        rulebooks.add(self.root, _asking("steam"))
        self.char2.db.goal = goals.sanitise(
            [{"type": "exists", "object": "steam"}], owner=self.char2)
        self.assertFalse(goals.satisfied(self.char2.db.goal, self.char2,
                                         self.root))

    def test_and_is_met_once_the_steam_exists(self):
        self.char2.db.goal = goals.sanitise(
            [{"type": "exists", "object": "steam"}], owner=self.char2)
        effects.apply(self.char2, self.room1,
                      [{"type": "create_object", "name": "steam",
                        "kind": "steam", "location": "room"}],
                      bound={}, world_root=self.root)
        self.assertTrue(goals.satisfied(self.char2.db.goal, self.char2,
                                        self.root))
