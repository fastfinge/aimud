"""
Whose it is, and what follows from that.

Three relations, and the third is new. Containment says where a thing is,
placement says how it is there, and neither has ever been able to say whose it
is -- so a sword in a chest was the chest's problem, and a sword on the floor
was nobody's in a way that could not be told apart from a sword whose owner
had died holding it.

What is asserted here is mostly the seams. The record itself is three fields;
what is worth testing is that the cascade claims what the giver owned and
nothing else, that "nobody" covers both of its cases, and that the two actions
ownership turns on -- taking and giving -- reach their after-rules at all,
since both are mechanics that never go near the rulebooks on their own.
"""

from unittest import mock

from evennia import create_object

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from world import conditions as C
from world import effects, ownership


@tag("world")
class TheRecord(EvenniaTest):
    """What is written down, and what can be read back off it."""

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.sword = self.obj1
        self.sword.key = "sword"

    def test_an_owner_is_named_as_well_as_numbered(self):
        """
        The name is the half that survives its subject. An attribute holding
        an object reference reads back as None once that object is deleted,
        and "owned by nobody" has to be tellable from "owned by somebody who
        is no longer here".
        """
        ownership.set_owner(self.sword, self.char1)
        self.assertEqual(ownership.record(self.sword)["id"], self.char1.id)
        self.assertEqual(ownership.owner_name(self.sword), self.char1.key)
        self.assertIs(ownership.owner_of(self.sword), self.char1)

    def test_a_thing_cannot_own_anything(self):
        """An owner is a character. See 6.2."""
        self.assertFalse(ownership.may_own(self.obj2))
        ownership.set_owner(self.sword, self.obj2)
        self.assertTrue(ownership.unowned(self.sword))

    def test_but_an_npc_can(self):
        """NPCs are not DefaultCharacter subclasses here, which is the trap."""
        self.obj2.db.is_npc = True
        self.assertTrue(ownership.may_own(self.obj2))

    def test_nobody_means_both_of_its_cases(self):
        self.assertTrue(ownership.claimable(self.sword))
        ownership.set_owner(self.sword, self.char1)
        self.assertFalse(ownership.claimable(self.sword))

        # The owner leaves the world. The record stays, and says who it was.
        name, dead = self.char1.key, self.char1
        self.sword.location = self.room1
        dead.delete()
        self.assertTrue(ownership.orphaned(self.sword))
        self.assertTrue(ownership.claimable(self.sword))
        self.assertEqual(ownership.owner_name(self.sword), name)

    def test_claiming_leaves_somebody_elses_alone(self):
        ownership.set_owner(self.sword, self.char2)
        self.assertFalse(ownership.claim(self.char1, self.sword))
        self.assertTrue(ownership.owns(self.char2, self.sword))


@tag("world")
class TheCascade(EvenniaTest):
    """
    Handing somebody a box of things hands them the things -- and hands them
    nothing else. The cascade claims only what the previous owner owned.
    """

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.box = self.obj1
        self.box.key = "box"
        self.box.location = self.char1
        self.mine = self.obj2
        self.mine.key = "pipe"
        self.mine.location = self.box
        ownership.set_owner(self.box, self.char1)
        # Written on the pipe as well as the box, because a thing carries its
        # own answer: putting your pipe in your box is not what makes the pipe
        # yours, and the cascade is for transfers rather than for tidying up.
        ownership.set_owner(self.mine, self.char1)

    def test_what_was_the_givers_goes_with_it(self):
        ownership.set_owner(self.box, self.char2)
        self.assertTrue(ownership.owns(self.char2, self.mine))

    def test_but_somebody_elses_sword_in_your_chest_stays_theirs(self):
        hers = create_object(key="her sword", location=self.box)
        ownership.set_owner(hers, self.char2)
        ownership.set_owner(self.box, self.char1)
        self.assertTrue(ownership.owns(self.char2, hers))

    def test_and_unowned_pebbles_stay_unowned(self):
        pebble = create_object(key="pebble", location=self.box)
        ownership.set_owner(self.box, self.char2)
        self.assertTrue(ownership.claimable(pebble))

    def test_asking_does_not_walk_up_the_chain(self):
        """
        The other half of 6.3, and the half that is easy to get wrong: the
        cascade fires once, when ownership changes, and afterwards everything
        carries its own answer. Your sword in my chest is still your sword.
        """
        hers = create_object(key="her sword", location=self.box)
        ownership.set_owner(hers, self.char2)
        self.assertFalse(ownership.owns(self.char1, hers))
        self.assertTrue(ownership.owns_through_containers(self.char1, hers))


@tag("world")
class TheCondition(EvenniaTest):
    """`owned_by`, in all three of its moods."""

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.sword = self.obj1
        self.sword.key = "sword"
        self.ctx = C.context({"direct": self.sword}, self.char1, self.room1)

    def test_yours_is_met_and_says_nothing(self):
        ownership.set_owner(self.sword, self.char1)
        self.assertTrue(
            C.evaluate({"subject": "direct", "owned_by": "actor"}, self.ctx))

    def test_and_somebody_elses_is_refused_in_a_sentence(self):
        ownership.set_owner(self.sword, self.char2)
        said = C.describe({"subject": "direct", "owned_by": "actor"},
                          self.ctx, C.UNMET)
        self.assertIn("not yours", said)

    def test_nobody_is_a_predicate_value(self):
        condition = {"subject": "direct", "owned_by": C.NOBODY}
        self.assertTrue(C.evaluate(condition, self.ctx))
        ownership.set_owner(self.sword, self.char2)
        self.assertFalse(C.evaluate(condition, self.ctx))
        self.assertIn(self.char2.key,
                      C.describe(condition, self.ctx, C.UNMET))

    def test_a_want_reads_as_a_want(self):
        said = C.describe({"subject": "direct", "owned_by": "actor"},
                          self.ctx, C.WANT)
        self.assertTrue(said.startswith("own "))

    def test_and_it_reads_with_no_world_in_front_of_it(self):
        """What `rules` and `help` print, with nothing to evaluate against."""
        said = C.describe({"subject": "direct", "owned_by": "actor"},
                          None, C.ABSTRACT)
        self.assertIn("belongs to", said)
        self.assertIn(
            "nobody",
            C.describe({"subject": "direct", "owned_by": C.NOBODY},
                       None, C.ABSTRACT))

    def test_the_standing_inference_is_asked_for_or_not_had(self):
        box = create_object(key="box", location=self.room1)
        self.sword.location = box
        ownership.set_owner(box, self.char1)
        plain = {"subject": "direct", "owned_by": "actor"}
        through = {"subject": "direct",
                   "owned_by": {"role": "actor", "through": "containers"}}
        self.assertFalse(C.evaluate(plain, self.ctx))
        self.assertTrue(C.evaluate(through, self.ctx))


@tag("unit")
class ReadingItBackwards(SimpleTestCase):
    """What the planner may conclude from a `set_owner`, and what it may not."""

    def test_an_effect_that_would_make_it_yours(self):
        self.assertTrue(C.achieves(
            {"type": "set_owner", "name_role": "direct", "to": "actor"},
            {"subject": "direct", "owned_by": "actor"}))

    def test_but_not_for_somebody_else(self):
        self.assertFalse(C.achieves(
            {"type": "set_owner", "name_role": "direct", "to": "target"},
            {"subject": "direct", "owned_by": "actor"}))

    def test_nor_for_another_thing_entirely(self):
        self.assertFalse(C.achieves(
            {"type": "set_owner", "name_role": "instrument", "to": "actor"},
            {"subject": "direct", "owned_by": "actor"}))

    def test_giving_something_away_leaves_it_nobodys(self):
        self.assertTrue(C.achieves(
            {"type": "set_owner", "name_role": "direct", "to": "nobody"},
            {"subject": "direct", "owned_by": C.NOBODY}))

    def test_the_register_describes_it(self):
        entry = effects.VOCABULARY["set_owner"]
        self.assertTrue(entry["means"])
        self.assertTrue(entry["backwards"])

    def test_and_it_reads_as_a_clause(self):
        self.assertEqual(
            effects.say({"type": "set_owner", "name_role": "direct",
                         "to": "actor"}),
            "makes what you act on yours")


@tag("world")
class TakingClaims(EvenniaCommandTest):
    """
    The first of the two seeded rules. `get` is a command rather than a trip
    through the pipeline, so what is really being tested is that an after-rule
    about it fires at all.
    """

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.world_description = "A world."
        self.stone = self.obj1
        self.stone.key = "stone"
        self.stone.location = self.room1
        self.stone.db.ai_takeable = True

    def take(self, what="stone"):
        from commands.look_take_cmds import CmdAIGet

        return self.call(CmdAIGet(), what)

    def test_picking_up_something_nobodys_makes_it_yours(self):
        self.take()
        self.assertTrue(ownership.owns(self.char1, self.stone))

    def test_but_picking_up_hers_does_not(self):
        ownership.set_owner(self.stone, self.char2)
        self.take()
        self.assertEqual(self.stone.location, self.char1)
        self.assertTrue(ownership.owns(self.char2, self.stone))

    def test_and_a_dead_owners_sword_is_claimable(self):
        ownership.set_owner(self.stone, self.char2)
        self.char2.delete()
        self.take()
        self.assertTrue(ownership.owns(self.char1, self.stone))

    def test_the_rule_is_a_rule_a_world_can_read(self):
        from world import rulebooks, standard_rules

        standard_rules.seed(self.room1)
        after = rulebooks.for_attempt(self.room1, "get",
                                      {"direct": self.stone}, self.char1,
                                      phase=rulebooks.AFTER)
        self.assertTrue(any(standard_rules.is_standard(r) for r in after))


@tag("world")
class Giving(EvenniaCommandTest):
    """The mechanic, and the second of the two seeded rules."""

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.coin = self.obj1
        self.coin.key = "coin"
        self.coin.location = self.char1
        ownership.set_owner(self.coin, self.char1)
        self.char2.location = self.room1
        self.said = []

    def attempt(self, raw):
        from world import attempt as attempt_mod

        attempt_mod.attempt(
            self.char1, raw, _NoSponsor(),
            lambda actor_text, event=None: self.said.append(actor_text or ""))
        return "\n".join(self.said)

    def test_giving_moves_it(self):
        self.attempt(f"give coin to {self.char2.key}")
        self.assertEqual(self.coin.location, self.char2)

    def test_and_hands_over_the_owning_of_it(self):
        self.attempt(f"give coin to {self.char2.key}")
        self.assertTrue(ownership.owns(self.char2, self.coin))

    def test_saying_it_the_other_way_round_works_too(self):
        """"give jessica the coin" -- two nouns and no preposition."""
        self.attempt(f"give {self.char2.key} coin")
        self.assertEqual(self.coin.location, self.char2)

    def test_you_cannot_give_away_what_you_are_wearing(self):
        self.coin.db.worn = True
        said = self.attempt(f"give coin to {self.char2.key}")
        self.assertIn("take", said)
        self.assertEqual(self.coin.location, self.char1)

    def test_nor_what_you_are_not_carrying(self):
        self.coin.location = self.room1
        said = self.attempt(f"give coin to {self.char2.key}")
        self.assertIn("not carrying", said)

    def test_and_giving_up_is_not_this_at_all(self):
        """
        Declining is half the job. "give up" names nobody to give anything
        to, and a world is entitled to work out what it means.
        """
        from world import ownership as own

        handled = own.handle(self.char1, "give",
                             {"roles": {"direct": "up"}}, {},
                             lambda *args, **kwargs: None)
        self.assertFalse(handled)


@tag("world")
class TheCommand(EvenniaCommandTest):
    """
    What a player types. Evennia ships a `give` of its own and this game
    replaces it, which is the part worth asserting: without the replacement
    the mechanic is unreachable from the keyboard and only NPCs ever transfer
    anything.
    """

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.world_description = "A world."
        self.coin = self.obj1
        self.coin.key = "coin"
        self.coin.location = self.char1
        ownership.set_owner(self.coin, self.char1)
        self.char2.location = self.room1

    def give(self, said):
        from commands.give_cmds import CmdAIGive

        return self.call(CmdAIGive(), said)

    def test_typing_it_hands_the_thing_over(self):
        self.give(f"coin to {self.char2.key}")
        self.assertEqual(self.coin.location, self.char2)
        self.assertTrue(ownership.owns(self.char2, self.coin))

    def test_the_pipeline_owns_the_verb(self):
        """
        Otherwise the handoff bounces: the pipeline hands `give` back to the
        command set, which is our command, which hands it to the pipeline.
        """
        from world import verbs

        self.assertIn("give", verbs.PIPELINE_VERBS)

    def test_and_no_world_is_ever_asked_what_giving_means(self):
        from world import verbs

        self.assertIn("give", verbs.engine_verbs())


@tag("world")
class MadeThings(EvenniaTest):
    """Rules three and four: what you make is yours, what you wear is yours."""

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.is_world_root = True

    def spec(self, name="cap"):
        return {"name": name, "description": "A cap.", "kinds": ["hat"],
                "affordances": {"wear": True}}

    def test_a_thing_made_on_somebody_is_theirs(self):
        from world import clothing

        made = clothing.create(self.spec(), location=self.char1)
        self.assertTrue(ownership.owns(self.char1, made))

    def test_but_a_room_furnishing_itself_owns_nothing(self):
        from world import clothing

        made = clothing.create(self.spec("bench"), location=self.room1)
        self.assertTrue(ownership.claimable(made))

    def test_and_what_a_verb_produces_belongs_to_whoever_did_it(self):
        made = effects.apply(self.char1, self.room1,
                             [{"type": "create_object", "name": "candle",
                               "description": "Wax."}],
                             world_root=self.room1)
        self.assertTrue(made)
        candle = next(o for o in self.room1.contents if o.key == "candle")
        self.assertTrue(ownership.owns(self.char1, candle))


@tag("world")
class WhatIsRecordedOfIt(EvenniaTest):
    """
    The provenance. Two writes, because they answer two different questions:
    the readable fact recall can find, and the exact temporal triple that
    outlives the thing it is about.
    """

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.sword = self.obj1
        self.sword.key = "sword"

    def test_a_transfer_is_written_both_ways(self):
        from world import memory

        with mock.patch.object(memory, "note_triple") as triple, \
                mock.patch.object(memory, "note_fact") as fact:
            ownership.set_owner(self.sword, self.char1)
        triple.assert_called_once()
        fact.assert_called_once()
        _where, subject, predicate, obj = triple.call_args[0]
        self.assertEqual(subject, f"#{self.sword.id}")
        self.assertEqual(predicate, "owned_by")
        self.assertEqual(obj, f"#{self.char1.id}")

    def test_the_triple_is_keyed_by_dbref_and_the_fact_by_name(self):
        """
        Two swords in a world are both called "sword", and `supersede` closes
        whatever shared a subject and a predicate -- so a name as the subject
        would have one sword's transfer ending the other's ownership.
        """
        from world import memory

        with mock.patch.object(memory, "note_triple"), \
                mock.patch.object(memory, "note_fact") as fact:
            ownership.set_owner(self.sword, self.char1)
        _where, subject, _predicate, owner = fact.call_args[0]
        self.assertEqual(subject, "sword")
        self.assertEqual(owner, self.char1.key)

    def test_writing_the_same_owner_again_records_nothing(self):
        from world import memory

        ownership.set_owner(self.sword, self.char1)
        with mock.patch.object(memory, "note_triple") as triple:
            ownership.set_owner(self.sword, self.char1)
        triple.assert_not_called()

    def test_destroying_a_thing_closes_the_record_rather_than_erasing_it(self):
        from world import memory

        ownership.set_owner(self.sword, self.char1)
        was = self.sword.id          # read now: it is about to be gone
        with mock.patch.object(memory, "end_triples") as ended:
            effects.apply(self.char1, self.room1,
                          [{"type": "destroy_object", "name": "sword"}],
                          world_root=self.room1)
        ended.assert_called_once()
        _where, subject, predicate = ended.call_args[0]
        self.assertEqual(subject, f"#{was}")
        self.assertEqual(predicate, "owned_by")


class _NoSponsor:
    """A sponsor that can pay for nothing, for a path that needs no model."""

    answers = False

    def key(self):
        raise ValueError("no key")

    def model_for(self, *_purposes):
        return ""
