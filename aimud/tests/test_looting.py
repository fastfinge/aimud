"""
Emptying something out, and what a world says when it cannot say.

Three times across two worlds a model was asked what looting a crate does, and
answered that it could not say: "move all contents of the container to the
actor's inventory" was not something the effect vocabulary could express,
because `move_object` names one thing. `cannot_say` is the measurement built
for exactly that, and it has now been taken -- so there is a `move_contents`,
and looting, emptying, unpacking and tipping out are all one effect.

What the player saw in the meantime is the other half of this. With no rule
filed the narrator still wrote prose, so "you rummage through the stout wooden
crate, quickly pulling out whatever looks useful" was read twice over a crate
nothing had been taken from, and the third attempt was refused outright.
"""

from django.test import tag
from evennia import create_object
from evennia.utils.test_resources import EvenniaTest

from tests.support import FakeSponsor, finishing, immediately, replying
from world import effects, relations


class _Crate(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.world_root = self.root
        self.root.db.is_world_root = True
        from world import kinds

        self.crate = create_object("typeclasses.objects.Object", key="Crate",
                                   location=self.room1)
        # A thing only holds what its kind says it holds, so the crate has to
        # be the sort of thing you can put something in before anything can
        # be taken out of it again.
        specs = dict(getattr(self.root.db, kinds.ATTR, None) or {})
        specs["crate.n.01"] = {"affordances": {}, "holds": ["in", "on"]}
        setattr(self.root.db, kinds.ATTR, specs)
        self.crate.db.kinds = ["crate.n.01"]
        self.key = create_object("typeclasses.objects.Object", key="brass key",
                                 location=self.room1)
        self.candle = create_object("typeclasses.objects.Object",
                                    key="tallow candle", location=self.room1)
        for thing in (self.key, self.candle):
            placed, why = relations.place(thing, self.crate, "in")
            self.assertTrue(placed, why)

    def loot(self, **effect):
        return effects.apply(
            self.char1, self.room1,
            [{"type": "move_contents", "name_role": "direct", **effect}],
            bound={"direct": self.crate}, world_root=self.root)


@tag("world")
class EmptyingSomethingOut(_Crate):

    def test_everything_it_holds_goes_to_whoever_acted(self):
        self.loot(to="actor")
        self.assertIs(self.key.location, self.char1)
        self.assertIs(self.candle.location, self.char1)
        self.assertEqual(relations.contents(self.crate), [])

    def test_and_the_room_is_told_what_came_out(self):
        said = " ".join(self.loot(to="actor"))
        self.assertIn("brass key", said)
        self.assertIn("tallow candle", said)
        self.assertIn("Crate", said)

    def test_or_out_onto_the_floor(self):
        self.loot(to="room")
        self.assertIs(self.key.location, self.room1)
        self.assertIsNone(relations.host_of(self.key))

    def test_only_what_is_in_it_when_that_is_what_was_asked(self):
        lid = create_object("typeclasses.objects.Object", key="iron lid",
                            location=self.room1)
        relations.place(lid, self.crate, "on")
        self.loot(to="actor", **{"from": "in"})
        self.assertIs(self.key.location, self.char1)
        self.assertIs(lid.location, self.crate,
                      "what is on it was not asked for")

    def test_an_empty_thing_changes_nothing_and_says_nothing(self):
        self.key.move_to(self.room1, quiet=True)
        self.candle.move_to(self.room1, quiet=True)
        self.assertEqual(self.loot(to="actor"), [])

    def test_clothes_somebody_is_wearing_are_not_looted(self):
        """They are on them, not in them. Stripping is a different verb."""
        from typeclasses.npcs import NPC
        from world import clothing

        bram = create_object(NPC, key="Bram", location=self.room1)
        coat = clothing.create({"name": "wool coat", "description": "Worn.",
                                "kind": "coat", "clothing_type": "top",
                                "affordances": {"wear": True}},
                               location=bram, worn_on=bram)
        purse = create_object("typeclasses.objects.Object", key="purse",
                              location=bram)
        effects.apply(self.char1, self.room1,
                      [{"type": "move_contents", "name_role": "direct",
                        "to": "actor"}],
                      bound={"direct": bram}, world_root=self.root)
        self.assertIs(purse.location, self.char1)
        self.assertIs(coat.location, bram)

    def test_what_the_rulebook_says_it_does(self):
        said = effects.say({"type": "move_contents", "name_role": "direct",
                            "to": "actor"})
        self.assertIn("empties", said)

    def test_a_rule_may_be_written_with_it(self):
        from world import rule_gen

        kept, complaints = rule_gen.validate(
            {"rules": [{"phase": "carry_out", "scope": "world",
                        "name": "looting a crate empties it",
                        "effects": [{"type": "move_contents",
                                     "name_role": "direct", "to": "actor"}]}]},
            [("world", "everywhere", {"world": True})], "loot", self.root)
        self.assertEqual(complaints, [])
        self.assertEqual(len(kept), 1)


@tag("world")
class WhenAWorldCannotSayWhatAVerbDoes(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.world_root = self.root
        self.root.db.is_world_root = True
        self.root.db.is_ai_room = True
        self.crate = create_object("typeclasses.objects.Object", key="crate",
                                   location=self.room1)

    def test_the_reason_is_remembered_rather_than_only_logged(self):
        """
        The two empty answers mean opposite things. Nothing needed saying is
        how smiling works, and is narrated like any other verb; the
        vocabulary having no way to say it is not.
        """
        from world import rule_gen

        rule_gen.note_fruitless(self.root, "loot", "no way to move contents")
        rule_gen.note_fruitless(self.root, "smile")
        self.assertIn("move contents", rule_gen.cannot_say(self.root, "loot"))
        self.assertEqual(rule_gen.cannot_say(self.root, "smile"), "")

    def test_it_says_so_rather_than_narrating_a_success(self):
        said = []
        with immediately(), replying(finishing(
                declare_action={"applies_to": [{"role": "direct"}]},
                file_rules={"rules": [],
                            "cannot_say": "no way to move what it holds"},
                narrate={"actor": "You rummage through the crate.",
                         "room": "{actor} $pconj(rummage)."})) as recorder:
            from world import attempt as attempt_mod

            attempt_mod.attempt(self.char1, "loot crate", FakeSponsor(),
                                on_message=lambda text, event=None:
                                    said.append(text or ""))
        answer = " ".join(part for part in said if part)
        self.assertIn("Nothing here knows how to loot", answer)
        self.assertNotIn("rummage", answer)
        asked = [schema["function"]["name"]
                 for index in range(recorder.count)
                 for schema in recorder.tools(index) or ()]
        self.assertNotIn("narrate", asked, "nothing happened to narrate")
