"""
What is true of a character: being told it, keeping it, and getting out of it.

Three faults found in the phase 13 playtest, and they compound. A player was
killed and read only the narration -- "you lunge at them, they scramble onto
the defensive" -- with not one word about being dead. Every verb afterwards was
refused by the standard rule that says you must be able to act, which is
correct and says nothing about why. Walking into another world took the death
with them, because states and traits lived on the character rather than per
world. And nothing could ever lift it, because check rules are monotone: no
rule a world can write makes an action looser, so `respawn` was refused by the
same gate as everything else.

Each fix is one of the three classes below, and the order they are in is the
order the player met them.
"""

from django.test import tag
from evennia.utils.test_resources import EvenniaTest

from tests.support import FakeAccount, as_json, immediately, replying
from world import actions, conditions as C, crossing, rulebooks as R
from world import attempt as attempt_mod
from world import standard_rules, traits, verbs


class ACharacter(EvenniaTest):
    """One world, one room in it, and somebody standing there."""

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room2.db.world_root = self.root
        self.room2.db.is_ai_room = True
        self.char1.move_to(self.room2, quiet=True)
        standard_rules.seed(self.root)
        verbs.register_state(self.root, "dead", group="life_status")
        self.heard = []
        self.char1.msg = lambda text="", **kwargs: self.heard.append(str(text))

    def told(self):
        return "\n".join(self.heard)


@tag("world")
class BeingToldWhatHappenedToYou(ACharacter):
    """
    `traits.adjust` has told a character about every figure that moved since
    traits existed, on the stated ground that a number changing silently is not
    a trait anyone can play with. States said nothing at all, and states are
    the half that can end the game.
    """

    def test_a_state_arriving_is_announced(self):
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        self.assertIn("now dead", self.told())

    def test_and_a_state_leaving_names_what_you_are_instead(self):
        """
        `life_status` has a default, so there is an other end to say. "You are
        no longer dead" is true and useless; "you are alive again" is the
        sentence somebody stuck needs.
        """
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        self.heard.clear()
        verbs.apply_states(self.char1, remove=["dead"], world_root=self.root)
        self.assertIn("alive again", self.told())

    def test_a_state_that_replaced_another_is_said_once(self):
        """Standing up is reported as standing up, not also as unsitting."""
        verbs.apply_states(self.char1, add=["seated"], world_root=self.root)
        self.heard.clear()
        verbs.apply_states(self.char1, add=["standing"], world_root=self.root)
        said = self.told()
        self.assertIn("now standing", said)
        self.assertNotIn("no longer seated", said)

    def test_what_a_state_means_comes_with_it(self):
        verbs.register_state(self.root, "winded", means="short of breath")
        verbs.apply_states(self.char1, add=["winded"], world_root=self.root)
        self.assertIn("short of breath", self.told())

    def test_nothing_is_said_when_nothing_changed(self):
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        self.heard.clear()
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        self.assertEqual(self.told(), "")

    def test_a_thing_is_not_told_anything(self):
        """There is nobody in a lantern. What the room sees is narration."""
        self.assertEqual(
            verbs.announce_states(self.obj1, set(), {"lit"}, self.root), [])

    def test_an_effect_that_kills_somebody_tells_them(self):
        from world import effects

        effects.apply(self.char1, self.room2,
                      [{"type": "set_state", "role": "actor",
                        "add": ["dead"]}],
                      bound={}, world_root=self.root)
        self.assertIn("now dead", self.told())


@tag("world")
class ConditionIsPerWorld(ACharacter):
    """
    A name is per world and so is a description. Condition was not, so being
    killed in the infinite dungeon made a character dead at the magical girl
    university as well -- and a world that has no way back had taken every
    other world with it.
    """

    def setUp(self):
        super().setUp()
        from evennia import create_object

        self.other_root = create_object("typeclasses.rooms.Room",
                                        key="Elsewhere")
        self.other_root.db.is_world_root = True
        self.other_root.db.world_root = self.other_root
        self.elsewhere = create_object("typeclasses.rooms.Room", key="Cloister")
        self.elsewhere.db.world_root = self.other_root

    def test_a_state_does_not_cross(self):
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        self.char1.move_to(self.elsewhere, quiet=True)
        self.assertNotIn("dead", verbs.states(self.char1))

    def test_and_is_waiting_when_you_come_back(self):
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        self.char1.move_to(self.elsewhere, quiet=True)
        self.char1.move_to(self.room2, quiet=True)
        self.assertIn("dead", verbs.states(self.char1))

    def test_a_trait_does_not_cross_either(self):
        traits.adjust(self.char1, "stamina", set_to=40, world_root=self.root)
        self.char1.move_to(self.elsewhere, quiet=True)
        self.assertIsNone(traits.value(self.char1, "stamina"))

    def test_and_comes_back_at_the_figure_it_was(self):
        traits.adjust(self.char1, "stamina", set_to=40, world_root=self.root)
        self.char1.move_to(self.elsewhere, quiet=True)
        traits.adjust(self.char1, "stamina", set_to=5,
                      world_root=self.other_root)
        self.char1.move_to(self.room2, quiet=True)
        self.assertEqual(traits.value(self.char1, "stamina"), 40)

    def test_walking_about_inside_one_world_changes_nothing(self):
        """
        The test is the world root and not the room, so almost every move is
        not a crossing at all and costs one comparison.
        """
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        self.char1.move_to(self.room1, quiet=True)
        self.assertIn("dead", verbs.states(self.char1))

    def test_restoring_says_nothing(self):
        """
        Restoring a condition is not causing one. A character walking back into
        a world they were killed in already knows; being told "you are now
        dead" on the doorstep would read as it having just happened.
        """
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        self.char1.move_to(self.elsewhere, quiet=True)
        self.heard.clear()
        self.char1.move_to(self.room2, quiet=True)
        self.assertNotIn("now dead", self.told())

    def test_leaving_every_world_keeps_the_body_as_it_was(self):
        """Limbo has nothing to be in a condition about, and a blank is not more true."""
        from evennia import create_object

        limbo = create_object("typeclasses.rooms.Room", key="Limbo")
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        self.char1.move_to(limbo, quiet=True)
        self.assertIn("dead", verbs.states(self.char1))


@tag("world")
class ActingInSpiteOfIt(ACharacter):
    """
    The way out, and why it has to be on the declaration.

    "You must be able to act" applies to every action there is, and check
    rules are monotone by construction -- adding one can only make an action
    stricter. So no rule a world writes can let a dead character do anything,
    which is right for every verb except the ones whose whole purpose is to end
    the state. A world says so once, when it declares the action.
    """

    def test_by_default_a_dead_character_can_do_nothing(self):
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        actions.declare(self.root, "respawn", [{"role": "direct",
                                                "optional": True}])
        ctx = C.context({}, self.char1, self.root, "respawn")
        gate = {"subject": "actor", "able": "acting"}
        self.assertFalse(C.evaluate(gate, ctx))
        self.assertIn("dead", C.unmet([gate], ctx))

    def test_a_world_may_declare_a_verb_that_works_anyway(self):
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        actions.declare(self.root, "respawn",
                        [{"role": "direct", "optional": True}],
                        despite=["acting"])
        ctx = C.context({}, self.char1, self.root, "respawn")
        self.assertTrue(C.evaluate({"subject": "actor", "able": "acting"}, ctx))

    def test_and_that_says_nothing_about_any_other_verb(self):
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        actions.declare(self.root, "respawn", [], despite=["acting"])
        ctx = C.context({}, self.char1, self.root, "read")
        self.assertFalse(C.evaluate({"subject": "actor", "able": "acting"}, ctx))

    def test_a_gate_nobody_has_heard_of_is_not_a_waiver(self):
        self.assertEqual(
            actions.declare(self.root, "loiter", [],
                            despite=["acting", "flying", ""])["despite"],
            ["acting"])

    def test_looking_happens_in_spite_of_the_gates(self):
        """
        Reading the world is not acting on it, and a game that answers every
        single thing you type with the same refusal has stopped telling you
        anything -- including how you got there. A world that means "the dead
        see nothing" has `visible_to` and a check rule, which is per object and
        reversible.
        """
        self.assertTrue(actions.waives(self.root, "look", "acting"))

    def test_a_dead_character_can_still_look_round(self):
        self.room2.db.desc = "A low stone cellar."
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        said = []
        with immediately(), replying("{}"):
            attempt_mod.attempt(
                self.char1, "look", FakeAccount(),
                on_message=lambda actor_text, room_text=None:
                    said.append(actor_text or ""))
        self.assertIn("A low stone cellar", "\n".join(said))

    def test_the_whole_way_back(self):
        """
        End to end, and the thing the playtest could not do: a world that has
        declared reviving as something the dead may attempt, with a rule saying
        what it does, lets somebody up again -- and tells them.
        """
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        actions.declare(self.root, "respawn",
                        [{"role": "direct", "optional": True}],
                        despite=["acting"])
        R.add(self.root, {
            "name": "respawning brings you back",
            "phase": R.CARRY_OUT, "action": "respawn",
            "scope": {R.WORLD: True}, "about": "actor",
            "effects": [{"type": "set_state", "role": "actor",
                         "remove": ["dead"]}]})
        self.heard.clear()
        said = []
        with immediately(), replying(as_json({"actor": "You draw breath.",
                                              "room": "{actor} sits up."})):
            attempt_mod.attempt(
                self.char1, "respawn", FakeAccount(),
                on_message=lambda actor_text, room_text=None:
                    said.append(actor_text or ""))
        self.assertNotIn("dead", verbs.states(self.char1))
        self.assertIn("alive again", self.told())


@tag("world")
class TheGateIsStillThere(ACharacter):
    """The waiver is a decision, so the refusal it lifts has to still work."""

    def test_a_verb_with_no_waiver_is_refused_while_dead(self):
        from world import kinds

        self.obj1.key = "Book"
        self.obj1.db.kinds = ["book.n.01"]
        self.obj1.move_to(self.room2, quiet=True)
        # Settled up front, so the attempt reaches the check phase rather than
        # being turned back by a question about books that is tested elsewhere.
        kinds.admit(self.root, self.obj1.db.kinds, "read", True)
        actions.declare(self.root, "read", [{"role": "direct"}])
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        said = []
        with immediately(), replying(as_json({"rules": []})):
            attempt_mod.attempt(
                self.char1, "read book", FakeAccount(),
                on_message=lambda actor_text, room_text=None:
                    said.append(actor_text or ""))
        self.assertIn("dead", "\n".join(said))
