"""
What a world is missing: wants nothing can satisfy, and faults in its rules.

Phase 4 of docs/generator-tool-loops.md, the free half of §5.1 and §5.2. No
model is involved anywhere here. Players are told the truth about why a goal
has no next step, a character that gives up says why, and the hints a
generator will be given in later phases are worked out and held still.
"""

from unittest import mock

from django.test import SimpleTestCase, tag
from evennia import create_object

from tests.base import GameTest
from tests.test_rulecheck import rule, world
from world import goals, planner, quests, rulecheck, verbs


@tag("unit")
class WhatTheFaultsSayAboutOneAttempt(SimpleTestCase):

    def pair_world(self):
        return world(
            {"open": rule(adds=["open"]),
             "read": rule(needs=["closed"], adds=["read"])},
            vocabulary={"open": {"group": "openness"},
                        "closed": {"group": "openness"},
                        "ajar": {"group": "openness"},
                        "dusty": {"group": "dirt"}},
            groups={"openness": {"exclusive": True}})

    def hints(self, registers, verb, **kwargs):
        return rulecheck.relevant(rulecheck.scan(registers), registers, verb,
                                  **kwargs)

    def test_the_verb_that_would_close_the_gap_is_told_about_it(self):
        said = self.hints(self.pair_world(), "close")
        self.assertTrue(any("Nothing in this world can make anything closed"
                            in line for line in said), said)

    def test_so_is_any_verb_near_a_state_of_that_group(self):
        said = self.hints(self.pair_world(), "sniff", near={"open"})
        self.assertTrue(any("closed" in line for line in said), said)

    def test_but_not_a_verb_that_has_nothing_to_do_with_it(self):
        said = self.hints(self.pair_world(), "sniff", near={"dusty"})
        self.assertFalse(any("closed" in line for line in said), said)

    def test_unused_words_are_offered_only_from_the_groups_at_hand(self):
        registers = self.pair_world()
        near_openness = self.hints(registers, "sniff", near={"open"})
        self.assertTrue(any("used by nothing: ajar" in line
                            for line in near_openness), near_openness)
        near_dirt = self.hints(registers, "sniff", near={"dusty"})
        self.assertFalse(any("ajar" in line for line in near_dirt), near_dirt)

    def test_a_proposal_for_this_verb_is_offered_and_others_are_not(self):
        proposals = [{"id": "r7", "action": "close", "name": "closing it",
                      "why": "nothing closes anything"},
                     {"id": "r8", "action": "light", "name": "lighting it"}]
        said = self.hints(world(), "close", proposals=proposals)
        self.assertTrue(any("r7" in line for line in said), said)
        self.assertFalse(any("r8" in line for line in said), said)

    def test_wants_come_first_and_there_are_never_too_many(self):
        wants = [f"want {n}" for n in range(10)]
        said = self.hints(self.pair_world(), "close", wants=wants)
        self.assertEqual(len(said), rulecheck.MOST_HINTS)
        self.assertEqual(said[0], "want 0")

    def test_a_world_with_nothing_wrong_has_nothing_to_say(self):
        self.assertEqual(self.hints(world(), "close"), [])


class _World(GameTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.room1.db.world_root = self.root
        self.room1.db.is_world_root = True


@tag("world")
class WhyThereIsNoStep(_World):
    loose_objects = 2

    def why(self, condition, who=None):
        return planner.blocker(who or self.char1, self.root, condition)

    def test_a_thing_that_exists_nowhere(self):
        self.assertEqual(self.why({"type": "holds", "object": "raw ore"}),
                         (planner.MISSING_THING, "raw ore"))

    def test_a_sort_of_thing_that_exists_nowhere(self):
        reason, what = self.why({"type": "holds", "kind": "anvil"})
        self.assertEqual(reason, planner.MISSING_THING)
        self.assertEqual(what, "anvil")

    def test_a_room_nobody_built(self):
        self.assertEqual(self.why({"type": "in_room", "room": "Library"}),
                         (planner.MISSING_ROOM, "Library"))

    def test_a_thing_here_that_nothing_can_change(self):
        reason, what = self.why({"type": "state", "object": self.obj1.key,
                                 "is": ["unlit"]})
        self.assertEqual(reason, planner.NO_RULE)
        self.assertEqual(what, self.obj1.key)

    def test_a_thing_there_is_no_way_to(self):
        elsewhere = create_object("typeclasses.rooms.Room", key="Vault")
        elsewhere.tags.add(str(self.root.id), category="ai_world")
        # A name nothing here resembles: the planner binds names loosely, and
        # "Obj2" is near enough to the Obj on the floor to be offered that.
        self.obj2.key = "brass sextant"
        self.obj2.location = elsewhere
        self.assertEqual(self.why({"type": "holds", "object": "brass sextant"}),
                         (planner.OUT_OF_REACH, "brass sextant"))

    def test_no_reason_when_there_is_a_step(self):
        self.assertEqual(self.why({"type": "holds", "object": self.obj1.key}),
                         (None, ""))

    def test_a_player_is_told_the_truth(self):
        action, note = planner.advise(self.char1, self.root,
                                      [{"type": "holds", "object": "raw ore"}])
        self.assertIsNone(action)
        self.assertIn("Nothing you can do", note)
        self.assertIn("no raw ore anywhere in this world yet", note)


@tag("world")
class WhatPeopleWantAndCannotGet(_World):
    loose_objects = 1
    # A player's quest comes before an NPC's goal, and world/goals.py tells
    # them apart by whether an account is behind the character.
    accounts = True

    def setUp(self):
        super().setUp()
        from typeclasses.npcs import NPC

        self.npc = create_object(NPC, key="Bram", location=self.room1)

    def test_nothing_without_a_world(self):
        self.assertEqual(goals.blocked_wants(None), [])

    def test_a_players_goal_and_the_words_it_accepts(self):
        self.char1.db.goal = [{"type": "holds", "object": "raw ore"}]
        found = goals.blocked_wants(self.root)
        entry = next(entry for entry in found if entry["who"] is self.char1)
        self.assertTrue(entry["player"])
        self.assertEqual(entry["reason"], planner.MISSING_THING)
        self.assertIn("'raw ore'", entry["words"])

    def test_a_sort_of_thing_is_accepted_by_kind(self):
        self.char1.db.goal = [{"type": "holds", "kind": "anvil"}]
        entry = goals.blocked_wants(self.root)[0]
        self.assertEqual(entry["words"], "of kind 'anvil'")

    def test_a_characters_own_want_is_not_hinted_to_its_own_room(self):
        self.npc.db.goal = [{"type": "holds", "object": "raw ore"}]
        entry = next(entry for entry in goals.blocked_wants(self.root)
                     if entry["who"] is self.npc)
        self.assertFalse(entry["player"])
        self.assertIn(self.room1.id, entry["avoid"])

    def test_a_players_quest_comes_first_and_avoids_the_givers_room(self):
        self.npc.db.goal = [{"type": "holds", "object": "iron nail"}]
        quests.offer(self.npc, self.char1, title="Ore",
                     description="bring me raw ore",
                     conditions=[{"type": "holds", "object": "raw ore"}])
        quests.accept(self.char1)
        found = goals.blocked_wants(self.root)
        self.assertEqual(found[0]["whose"], "quest")
        self.assertIs(found[0]["who"], self.char1)
        self.assertIn(self.room1.id, found[0]["avoid"])

    def test_a_want_with_a_step_is_not_blocked(self):
        self.char1.db.goal = [{"type": "holds", "object": self.obj1.key}]
        self.assertEqual([entry for entry in goals.blocked_wants(self.root)
                          if entry["who"] is self.char1], [])

    def test_a_character_that_gives_up_says_why(self):
        goal = [{"type": "holds", "object": "raw ore"}]
        self.npc.db.goal = goal
        self.npc.db.goal_stalls = self.npc.GOAL_STALL_LIMIT - 1
        with mock.patch("evennia.utils.logger.log_info") as logged:
            self.npc._give_up_eventually(goal, self.root)
        said = " ".join(str(call.args[0]) for call in logged.call_args_list)
        self.assertIn("missing_thing: raw ore", said)
        self.assertEqual(self.npc.db.goal, [])


@tag("world")
class TheStatesNearAnAttempt(_World):
    loose_objects = 1

    def test_what_things_are_in_now_and_what_their_sorts_have_been_in(self):
        verbs.apply_states(self.obj1, add=["dusty"], world_root=self.root)
        self.assertIn("dusty", rulecheck.states_near(self.root,
                                                     {"direct": self.obj1}))
