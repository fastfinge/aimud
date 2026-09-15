"""
Ownership with a consequence.

P5 made things somebody's and P6 let a player say whose, and neither changed
anything that happens in play. This is the phase that does: one standard rule
a world can switch on, one thing a character wants when it watches its
property walk off, and the witnesses told whose it was.

What is asserted here is mostly that the rule is *reached*. It ships
suspended, and the two actions it is about are a command and a mechanic that
never go near the check phase on their own -- so a rule that could be restored
and then consulted by nothing would pass every test that only read the book.
"""

from unittest import mock

from django.test import tag
from evennia import create_object
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from world import conditions as C
from world import goals, ownership, rulebooks, standard_rules

RULE = "you may not take what is not yours"


def _the_rule(root):
    standard_rules.seed(root)
    return next(r for r in rulebooks.all_rules(root) if r["name"] == RULE)


def _restore(root):
    rulebooks.set_listed(root, _the_rule(root)["id"], True)


@tag("world")
class Somebody(EvenniaTest):
    """The guard the rule needs, since the condition language has no "not"."""

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.stone = self.obj1
        self.stone.key = "stone"

    def met(self):
        ctx = C.context({"direct": self.stone}, self.char1, self.room1)
        return C.evaluate({"subject": "direct", "owned_by": C.SOMEBODY}, ctx)

    def test_is_anybody_but_nobody(self):
        self.assertFalse(self.met())
        ownership.set_owner(self.stone, self.char2)
        self.assertTrue(self.met())
        ownership.set_owner(self.stone, self.char1)
        self.assertTrue(self.met())

    def test_and_a_dead_owner_is_nobody(self):
        ownership.set_owner(self.stone, self.char2)
        self.char2.delete()
        self.assertFalse(self.met())

    def test_it_reads_as_a_clause(self):
        said = C.describe({"subject": "direct", "owned_by": C.SOMEBODY})
        self.assertIn("somebody's", said)


@tag("world")
class TheRule(EvenniaCommandTest):
    """Every world has it; no world is bound by it until it says so."""

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.world_description = "A world."
        self.char2.location = self.room1
        self.stone = self.obj1
        self.stone.key = "stone"
        self.stone.location = self.room1
        self.stone.db.ai_takeable = True
        ownership.set_owner(self.stone, self.char2)

    def take(self, what="stone"):
        from commands.look_take_cmds import CmdAIGet

        return self.call(CmdAIGet(), what)

    def test_it_ships_suspended(self):
        self.assertFalse(_the_rule(self.room1)["listed"])
        self.take()
        self.assertEqual(self.stone.location, self.char1)

    def test_a_world_that_restores_it_refuses(self):
        _restore(self.room1)
        said = self.take()
        self.assertIn("not yours", said)
        self.assertEqual(self.stone.location, self.room1)

    def test_but_not_what_is_yours(self):
        ownership.set_owner(self.stone, self.char1)
        _restore(self.room1)
        self.take()
        self.assertEqual(self.stone.location, self.char1)

    def test_nor_what_is_nobodys_which_is_still_claimed(self):
        ownership.disown(self.stone)
        _restore(self.room1)
        self.take()
        self.assertEqual(self.stone.location, self.char1)
        self.assertTrue(ownership.owns(self.char1, self.stone))

    def test_nor_a_dead_owners(self):
        self.char2.delete()
        _restore(self.room1)
        self.take()
        self.assertEqual(self.stone.location, self.char1)

    def test_taking_it_out_of_something_is_taking_it(self):
        from world import kinds, relations

        chest = create_object(key="chest", location=self.room1)
        chest.db.kinds = ["chest.n.01"]
        # Whether a chest holds things is settled where that is tested.
        store = dict(getattr(self.room1.db, kinds.ATTR, None) or {})
        store["chest.n.01"] = {"affordances": {}, "holds": ["in"]}
        setattr(self.room1.db, kinds.ATTR, store)
        ok, why = relations.place(self.stone, chest, "in", quiet=True)
        self.assertTrue(ok, why)
        _restore(self.room1)
        said = []
        relations._take_from(self.char1, self.stone, chest,
                             lambda text, event=None: said.append(text))
        self.assertIn("not yours", said[0])
        self.assertIsNot(self.stone.location, self.char1)

    def test_restoring_it_survives_the_next_edition(self):
        """
        A world restores this rule to say what sort of place it is, and a new
        edition of the standard rules is not a reason to undo that.
        """
        _restore(self.room1)
        setattr(self.room1.db, standard_rules.VERSION_ATTR,
                standard_rules.VERSION - 1)
        standard_rules.seed(self.room1)
        self.assertTrue(_the_rule(self.room1)["listed"])

    def test_and_so_does_suspending_one_that_ships_in_force(self):
        standard_rules.seed(self.room1)
        reach = next(r for r in rulebooks.all_rules(self.room1)
                     if r["name"] == "you must be able to reach what you act on")
        rulebooks.set_listed(self.room1, reach["id"], False)
        setattr(self.room1.db, standard_rules.VERSION_ATTR,
                standard_rules.VERSION - 1)
        standard_rules.seed(self.room1)
        again = next(r for r in rulebooks.all_rules(self.room1)
                     if r["name"] == reach["name"])
        self.assertFalse(again["listed"])

    def test_a_check_rule_about_giving_is_asked_too(self):
        coin = create_object(key="coin", location=self.char1)
        rulebooks.add(self.room1, rulebooks.blank(
            action="give", phase=rulebooks.CHECK, name="gifts come home",
            conditions=[{"subject": "direct", "owned_by": "target"}]))
        ok, said, _event = ownership.give(self.char1, coin, self.char2)
        self.assertFalse(ok)
        self.assertTrue(said)
        self.assertEqual(coin.location, self.char1)


@tag("world")
class TheOwnerNotices(EvenniaCommandTest):
    """Whose it was reaches the witnesses, and the owner wants it back."""

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.world_description = "A world."
        from typeclasses.npcs import NPC

        self.NPC = NPC
        self.olara = create_object(NPC, key="Olara Voss", location=self.room1)
        self.olara.db.is_npc = True
        self.crowbar = self.obj1
        self.crowbar.key = "crowbar"
        self.crowbar.location = self.room1
        self.crowbar.db.ai_takeable = True
        ownership.set_owner(self.crowbar, self.olara)
        # Being named wakes a character, which would be a model call.
        patcher = mock.patch.object(NPC, "_trigger_reaction")
        patcher.start()
        self.addCleanup(patcher.stop)

    def take(self):
        from commands.look_take_cmds import CmdAIGet

        return self.call(CmdAIGet(), "crowbar")

    def test_the_witnesses_are_told_whose_it_was(self):
        with mock.patch("world.npc_gen.notify_npcs") as told:
            self.take()
        self.assertIn("which belongs to Olara Voss", told.call_args[0][3])

    def test_the_sentence_keeps_its_full_stop(self):
        self.assertEqual(
            ownership.witnessed_taking("Raldor picks up the crowbar.",
                                       self.char1, self.crowbar),
            "Raldor picks up the crowbar, which belongs to Olara Voss.")

    def test_nobodys_things_are_only_picked_up(self):
        ownership.disown(self.crowbar)
        said = "Raldor picks up the crowbar."
        self.assertEqual(
            ownership.witnessed_taking(said, self.char1, self.crowbar), said)

    def test_the_owner_wants_it_back(self):
        self.take()
        self.assertEqual([dict(c) for c in self.olara.db.goal],
                         goals.recover(self.crowbar))
        self.assertFalse(goals.satisfied(self.olara.db.goal, self.olara,
                                         self.room1))
        self.crowbar.move_to(self.olara, quiet=True)
        self.assertTrue(goals.satisfied(self.olara.db.goal, self.olara,
                                        self.room1))

    def test_but_not_when_she_was_not_there_to_see_it(self):
        self.olara.location = self.room2
        self.take()
        self.assertFalse(self.olara.db.goal)

    def test_nor_over_an_errand_she_agreed_to(self):
        errand = [{"type": "in_room", "room": "Room2"}]
        self.olara.db.goal = errand
        self.olara.db.goal_from_quest = "q1"
        self.take()
        self.assertEqual([dict(c) for c in self.olara.db.goal], errand)

    def test_taking_it_through_the_pipeline_is_witnessed_the_same_way(self):
        """Out of a chest, say: an event, delivered rather than a sentence."""
        from world import events

        event = events.Event(
            actor=self.char1, room=self.room1, verb="get",
            roles={"direct": self.crowbar},
            room_template="{actor} $pconj(take) {direct} from the chest.")
        with mock.patch("world.npc_gen.notify_npcs") as told:
            events._tell_the_characters(event, event.room_template)
        self.assertIn("which belongs to Olara Voss", told.call_args[0][3])

    def test_a_character_taking_it_is_noticed_by_the_others(self):
        kell = create_object(self.NPC, key="Kell", location=self.room1)
        kell.db.is_npc = True
        with mock.patch.object(self.NPC, "_notify_other_npcs") as told:
            kell._execute_one("get", {"object_name": "crowbar"}, self.room1)
        self.assertEqual(self.crowbar.location, kell)
        self.assertIn("which belongs to Olara Voss", told.call_args[0][2])

    def test_and_is_refused_by_the_rule_like_anybody(self):
        kell = create_object(self.NPC, key="Kell", location=self.room1)
        kell.db.is_npc = True
        _restore(self.room1)
        kell._execute_one("get", {"object_name": "crowbar"}, self.room1)
        self.assertEqual(self.crowbar.location, self.room1)
