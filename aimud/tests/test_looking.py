"""
Looking, as an action with rulebooks.

The one sense no world could hold an opinion about. `look` was a command, so
describing happened in `CmdAILook` where no rule could reach it -- which meant a
cave could not be dark, a ghost could not need the right spectacles, and the
moon could not be looked at without being touched.

The test to read first is `TheVerbTheCommandSetStillAnswers`. Handing a verb
back to the command set that the pipeline also claims is an infinite bounce, and
this project has had one: "study scroll" folded to `look`, `look` was handed
over, "study scroll" was not a command, and the two passed it between them for
ever. Every spelling is asserted here for that reason.
"""

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from tests.support import FakeSponsor, as_json, immediately, replying
from world import attempt as attempt_mod
from world import actions, conditions as C, rulebooks as R
from world import gear, standard_rules, traits, verbs


@tag("unit")
class TheVerbThePipelineOwns(EvenniaTest):
    """Canonical spellings only, because everything folds before the test."""

    def test_look_is_owned_by_the_pipeline(self):
        self.assertIn("look", verbs.PIPELINE_VERBS)

    def test_and_every_way_of_typing_it_folds_to_that(self):
        for typed in ("look", "l", "x", "examine", "inspect", "study", "view"):
            self.assertEqual(verbs.canonical_verb(typed), "look", typed)


@tag("unit")
class DescribeSpeaksAndAchievesNothing(SimpleTestCase):
    """
    The one assertion in this file with no database in it, and it is here on
    purpose rather than by omission.

    `conditions.achieves` reads an effect backwards so the planner can use it,
    and 11.1 says an effect nobody can read backwards is a hole in the planner.
    `describe` is the deliberate exception: nothing is ever a goal "to have been
    told something". Asserting it keeps that a decision on the record instead of
    something a later reader finds missing and fixes.
    """

    def test_describe_is_an_effect_that_speaks_for_itself(self):
        from world import effects

        self.assertIn("describe", effects.SPEAKS_FOR_ITSELF)
        self.assertTrue(effects.speaks_for_itself([{"type": "describe"}]))
        self.assertFalse(effects.speaks_for_itself(
            [{"type": "set_state", "add": ["lit"]}]))

    def test_and_nothing_is_achieved_by_describing(self):
        for condition in ({"subject": "direct", "is": ["seen"]},
                          {"subject": "actor", "trait": "knowledge", "min": 1},
                          {"subject": "direct", "exists": True}):
            self.assertFalse(
                C.achieves({"type": "describe", "role": "direct"}, condition),
                condition)


@tag("world")
class Looking(EvenniaTest):
    """A world with a room, a thing in it, and the standard rules."""

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room2.db.world_root = self.root
        self.room2.db.is_ai_room = True
        self.char1.move_to(self.room2, quiet=True)

        self.thing = self.obj1
        self.thing.key = "Lantern"
        self.thing.db.desc = "A dented brass lantern."
        self.thing.move_to(self.room2, quiet=True)
        standard_rules.seed(self.root)

    def look(self, raw="look"):
        """One look, with no model permitted to answer."""
        said = []
        with immediately(), replying(
                as_json({"actor": "should not be asked",
                         "room": "should not be asked"})) as script:
            attempt_mod.attempt(
                self.char1, raw, FakeSponsor(),
                on_message=lambda a, r=None: said.append(a or ""))
            self.asked = script.count
        return "\n".join(s for s in said if s)


@tag("world")
class WhatLookingCosts(Looking):

    def test_looking_at_a_thing_costs_no_model_call(self):
        """
        The whole reason looking can be an action. `describe` returns the
        appearance, so there is nothing for a narrator to write.
        """
        said = self.look("look lantern")
        self.assertEqual(self.asked, 0, "nothing should have been asked")
        self.assertIn("dented brass lantern", said)

    def test_and_nothing_is_cached_to_be_replayed(self):
        """
        A narration is cached because it cost money. This did not, and caching
        it would mean a thing that changed went on being described as it was.
        """
        self.look("look lantern")
        self.assertFalse((self.thing.db.ai_commands or {}).get("look"))

    def test_the_room_is_not_told_that_somebody_looked(self):
        """
        Looking still happens -- it is an action, it has a verb and an object,
        and something wanting to play a sound for it later will want to know.
        What it does not have is anything for the room to read, which is what
        `seen` says and what used to be said by an empty string.
        """
        raised = []
        with immediately(), replying("{}"):
            attempt_mod.attempt(
                self.char1, "look lantern", FakeSponsor(),
                on_message=lambda a, event=None: raised.append(event))
        seen = [event for event in raised
                if event is not None and event.seen]
        self.assertEqual(seen, [])


@tag("world")
class BareLookingMeansTheRoom(Looking):
    """
    The redirect. `power` aboard a ship became powering the ship; `look` with
    nothing named becomes looking at the room, by the same mechanism and the
    same `unbound` guard.
    """

    def test_bare_look_describes_the_room(self):
        self.room2.db.desc = "A low stone cellar."
        said = self.look("look")
        self.assertIn("low stone cellar", said)

    def test_and_it_is_the_redirect_doing_it(self):
        book = R.for_attempt(self.root, "look", {}, self.char1)
        aside = [r for r in book if r["phase"] == R.INSTEAD]
        self.assertTrue(aside)
        self.assertEqual(aside[0]["effects"][0]["roles"]["direct"], C.HERE)

    def test_the_redirect_stands_aside_when_something_was_named(self):
        """Guarded by `unbound`, exactly as the datapad case needed."""
        book = R.for_attempt(self.root, "look", {"direct": self.thing},
                             self.char1)
        self.assertEqual([r for r in book if r["phase"] == R.INSTEAD], [])

    def test_so_looking_at_a_thing_does_not_describe_the_room(self):
        self.room2.db.desc = "A low stone cellar."
        said = self.look("look lantern")
        self.assertNotIn("low stone cellar", said)


@tag("world")
class SightIsNotReach(Looking):
    """
    §5.1 has given every role a `visible` / `touchable` / `carried` level since
    actions were declared, and nothing ever enforced it. So the one standard
    rule that applies to every action demanded reach -- of looking too.
    """

    def test_looking_ships_declared_visible(self):
        """
        Not bought from a model. The standard rules were written against this
        arity, so a world that guessed a different one would seed rules that
        never gather -- and an optional `direct` is what makes bare `look`
        reach the redirect instead of being answered "look at what?".
        """
        spec = actions.spec(self.root, "look")
        self.assertIsNotNone(spec)
        role = spec["applies_to"][0]
        self.assertEqual(role["access"], "visible")
        self.assertTrue(role["optional"])

    def test_a_visible_role_is_excused_the_reach_rule(self):
        far = self.obj2
        far.move_to(self.room1, quiet=True)       # another room entirely
        ctx = C.context({"direct": far}, self.char1, self.root, "look")
        self.assertTrue(
            C.evaluate({"subject": "direct", "reachable_by": "actor"}, ctx))

    def test_while_a_touchable_one_is_not(self):
        actions.declare(self.root, "get",
                        [{"role": "direct", "access": "touchable"}])
        far = self.obj2
        far.move_to(self.room1, quiet=True)
        ctx = C.context({"direct": far}, self.char1, self.root, "get")
        self.assertFalse(
            C.evaluate({"subject": "direct", "reachable_by": "actor"}, ctx))

    def test_and_outside_an_attempt_reach_is_still_asked_for(self):
        """
        A quest or a goal tests conditions with no action in hand. Excusing
        reach there would make every goal about a distant thing look satisfied.
        """
        far = self.obj2
        far.move_to(self.room1, quiet=True)
        ctx = C.context({"direct": far}, self.char1, self.root)
        self.assertFalse(
            C.evaluate({"subject": "direct", "reachable_by": "actor"}, ctx))

    def test_what_is_here_is_visible(self):
        ctx = C.context({"direct": self.thing}, self.char1, self.root, "look")
        self.assertTrue(
            C.evaluate({"subject": "direct", "visible_to": "actor"}, ctx))

    def test_the_room_you_are_in_is_visible(self):
        ctx = C.context({"direct": self.room2}, self.char1, self.root, "look")
        self.assertTrue(
            C.evaluate({"subject": "direct", "visible_to": "actor"}, ctx))

    def test_what_is_elsewhere_is_not(self):
        far = self.obj2
        far.move_to(self.room1, quiet=True)
        ctx = C.context({"direct": far}, self.char1, self.root, "look")
        self.assertFalse(
            C.evaluate({"subject": "direct", "visible_to": "actor"}, ctx))


@tag("world")
class Darkness(Looking):
    """
    Light is a trait, and `gear` already sums what a room and what is lying in
    it are worth to whoever is standing there. So darkness needs no subsystem,
    no effect type and no new predicate of its own.
    """

    def dark(self):
        """Make this world one that has something to say about light."""
        traits.register(self.root, traits.LIGHT, name="Light",
                        means="how well lit it is here",
                        trait_type="counter", base=0, min=0)
        gear.recompute(self.char1)

    def test_a_world_that_never_mentions_light_has_no_darkness(self):
        """
        The inverted default. Only brightness is ever stated, so a world that
        states none is daylit rather than a cave from end to end.
        """
        self.assertFalse(traits.lights(self.root))
        self.assertIn("dented brass lantern", self.look("look lantern"))

    def test_once_it_does_the_unlit_room_refuses(self):
        self.dark()
        said = self.look("look lantern")
        self.assertIn("too dark", said)
        self.assertNotIn("dented brass lantern", said)

    def test_a_room_that_grants_light_is_lit(self):
        """`bonus_when: present` -- the room is a source in its own right."""
        self.dark()
        self.room2.db.trait_bonuses = {traits.LIGHT: 2}
        self.room2.db.bonus_when = "present"
        gear.recompute(self.char1)
        self.assertIn("dented brass lantern", self.look("look lantern"))

    def test_a_lit_lamp_lights_the_room_for_whoever_is_in_it(self):
        self.dark()
        self.thing.db.trait_bonuses = {traits.LIGHT: 1}
        self.thing.db.bonus_when = "present"
        self.thing.db.bonus_while = "lit"
        verbs.apply_states(self.thing, add=["lit"], world_root=self.root)
        gear.recompute(self.char1)
        self.assertIn("dented brass lantern", self.look("look lantern"))

    def test_but_an_unlit_one_lights_nobody(self):
        self.dark()
        self.thing.db.trait_bonuses = {traits.LIGHT: 1}
        self.thing.db.bonus_when = "present"
        self.thing.db.bonus_while = "lit"
        gear.recompute(self.char1)
        self.assertIn("too dark", self.look("look lantern"))

    def test_carrying_the_lamp_out_takes_the_light_with_it(self):
        """
        Derived, never accumulated. Nothing subtracts the lamp's worth on the
        way out; the sums are simply done again.
        """
        self.dark()
        self.thing.db.trait_bonuses = {traits.LIGHT: 1}
        self.thing.db.bonus_when = "carried"
        self.thing.db.bonus_while = "lit"
        verbs.apply_states(self.thing, add=["lit"], world_root=self.root)
        self.thing.move_to(self.char1, quiet=True)
        gear.recompute(self.char1)
        self.assertIn("dented brass lantern", self.look("look lantern"))

        self.thing.move_to(self.room2, quiet=True)
        gear.recompute(self.char1)
        self.assertIn("too dark", self.look("look lantern"))


@tag("world")
class TheVerbTheCommandSetStillAnswers(EvenniaTest):
    """
    The bounce, asserted in both directions.

    `_with_bindings` hands engine verbs to the command set, and a verb the
    command set does not know comes straight back as an unknown command, which
    reaches the pipeline, which hands it over again. "study scroll" did exactly
    that once: `study` folds to `look`, `look` was an engine verb, and `study`
    was not a command.

    Taking `look` over reverses the risk -- now the command calls the pipeline,
    so a pipeline that handed `look` back would loop the other way round. Hence
    one test per spelling rather than one test.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room2.db.world_root = self.root
        self.room2.db.is_ai_room = True
        # What `unknown_cmd` gates on. `x` and `examine` are not commands, so
        # they arrive as unrecognised input and reach the pipeline through the
        # no-match handler -- which declines outright outside a generated world.
        # That is the road the bounce used to happen on.
        self.room2.db.world_description = "A cellar under a ruined keep."
        self.char1.move_to(self.room2, quiet=True)
        self.room2.db.desc = "A low stone cellar."
        self.obj1.key = "Lantern"
        self.obj1.db.desc = "A dented brass lantern."
        self.obj1.move_to(self.room2, quiet=True)

    def typed(self, raw):
        """What the player is told, having typed this, answered exactly once."""
        said = []
        self.char1.msg = lambda text="", **kwargs: said.append(str(text))
        with immediately(), replying("{}"):
            self.char1.execute_cmd(raw)
        return said

    def test_every_spelling_of_looking_at_a_thing_is_answered_once(self):
        for raw in ("look lantern", "l lantern", "x lantern",
                    "examine lantern", "inspect lantern", "study lantern",
                    "view lantern"):
            said = self.typed(raw)
            joined = " ".join(said)
            self.assertIn("dented brass lantern", joined, raw)
            self.assertEqual(joined.count("dented brass lantern"), 1, raw)

    def test_and_bare_looking_describes_the_room_once(self):
        for raw in ("look", "l"):
            joined = " ".join(self.typed(raw))
            self.assertIn("low stone cellar", joined, raw)
            self.assertEqual(joined.count("low stone cellar"), 1, raw)

    def test_the_pipeline_does_not_hand_looking_back(self):
        """The guard itself, rather than its symptom."""
        self.assertIn("look", verbs.command_verbs(),
                      "there is still a command, and a player still types it")
        self.assertIn("look", verbs.PIPELINE_VERBS,
                      "but the pipeline owns what it means")


@tag("world")
class OutsideAGeneratedWorld(EvenniaTest):
    """
    No world root, no rulebooks, and nothing to consult them with.

    A look that stopped working in Limbo would be a far worse bug than anything
    rules could fix, so the original behaviour stands there untouched.
    """

    def setUp(self):
        super().setUp()
        self.obj1.key = "Lantern"
        self.obj1.db.desc = "A dented brass lantern."
        self.obj1.move_to(self.room1, quiet=True)
        self.room1.db.desc = "A featureless white room."

    def typed(self, raw):
        said = []
        self.char1.msg = lambda text="", **kwargs: said.append(str(text))
        self.char1.execute_cmd(raw)
        return " ".join(said)

    def test_looking_at_a_thing_still_works(self):
        self.assertIn("dented brass lantern", self.typed("look lantern"))

    def test_and_so_does_looking_about_you(self):
        self.assertIn("featureless white room", self.typed("look"))

    def test_and_no_rules_were_seeded_to_do_it(self):
        self.typed("look")
        self.assertEqual(R.all_rules(self.room1), [])


@tag("world")
class ArrivingInTheDark(Looking):
    """
    Walking into a cellar is not an action, so no check rule runs for it.

    Evennia describes the room you have arrived in from a movement hook. A world
    that refused to let you examine anything in the dark and still handed you
    the room description on the way in would be telling you two different
    things, so the appearance itself asks.
    """

    def dark(self):
        traits.register(self.root, traits.LIGHT, name="Light",
                        means="how well lit it is here",
                        trait_type="counter", base=0, min=0)
        gear.recompute(self.char1)

    def test_a_lit_world_describes_the_room_as_ever(self):
        self.room2.db.desc = "A low stone cellar."
        self.assertIn("low stone cellar",
                      self.room2.return_appearance(self.char1))

    def test_a_dark_one_does_not(self):
        self.room2.db.desc = "A low stone cellar."
        self.dark()
        said = self.room2.return_appearance(self.char1)
        self.assertIn("too dark", said)
        self.assertNotIn("low stone cellar", said)

    def test_and_the_contents_are_not_listed_either(self):
        """Which is the whole point: a listing is a way of seeing."""
        self.dark()
        self.assertNotIn("Lantern", self.room2.return_appearance(self.char1))

    def test_a_lamp_brings_the_room_back(self):
        self.room2.db.desc = "A low stone cellar."
        self.dark()
        self.thing.db.trait_bonuses = {traits.LIGHT: 1}
        self.thing.db.bonus_when = "present"
        self.thing.db.bonus_while = "lit"
        verbs.apply_states(self.thing, add=["lit"], world_root=self.root)
        gear.recompute(self.char1)
        self.assertIn("low stone cellar",
                      self.room2.return_appearance(self.char1))

    def test_a_room_outside_a_generated_world_never_asks(self):
        """No root, no rules, and no trait register to consult."""
        self.room1.db.world_root = None
        self.room1.db.desc = "A featureless white room."
        self.assertIn("featureless white room",
                      self.room1.return_appearance(self.char1))


@tag("world")
class WhatGenerationCanNowSay(EvenniaTest):
    """
    The capability was built; nothing asked for it. A room could always have
    been worth something to whoever stood in it -- `gear` says so in as many
    words -- and no generator had ever been offered the field.
    """

    def test_a_room_can_be_created_lit(self):
        from world import worldgen

        room = worldgen._create_room(
            "Sunlit Clearing", "Grass, and a gap in the canopy.", [],
            "a forest", None, None, bonuses={traits.LIGHT: 2})
        self.assertEqual(dict(room.db.trait_bonuses), {traits.LIGHT: 2.0}
                         if isinstance(
                             next(iter(room.db.trait_bonuses.values())), float)
                         else {traits.LIGHT: 2})
        self.assertEqual(room.db.bonus_when, "present",
                         "a room works on whoever is present, by definition")

    def test_and_a_dark_one_is_simply_a_room_with_nothing_said(self):
        """The inverted default, asserted: darkness is the absence of a claim."""
        from world import worldgen

        room = worldgen._create_room(
            "Cellar", "Damp brick, and no window.", [], "a keep", None, None)
        self.assertFalse(room.db.trait_bonuses)

    def test_the_room_prompt_asks_for_light_by_name(self):
        from world import worldgen

        prompt = worldgen._DESC_SYSTEM_PROMPT
        self.assertIn("trait_bonuses", prompt)
        self.assertIn("light", prompt)
        self.assertIn("NOTHING AT ALL", prompt,
                      "a dark room must be told to say nothing, not to say 0")

    def test_the_contents_prompt_offers_the_state_gate(self):
        """`gear._gate_open` has implemented this all along."""
        from world import worldgen

        self.assertIn("bonus_while", worldgen._CONTENTS_SYSTEM_PROMPT)

    def test_and_a_generated_item_keeps_it(self):
        from world import clothing

        item = clothing.create({"name": "Lantern", "description": "Brass.",
                                "trait_bonuses": {traits.LIGHT: 2},
                                "bonus_when": "present",
                                "bonus_while": "lit"},
                               location=self.room1)
        self.assertEqual(item.db.bonus_while, "lit")
        self.assertEqual(item.db.bonus_when, "present")


@tag("world")
class WhatFollowsFromLooking(Looking):
    """
    The planner reaches looking through its consequence, never through its
    description. That is the whole reason `describe` is allowed to be the one
    effect `achieves` cannot read.
    """

    def test_an_after_rule_fires_once_the_look_has_worked(self):
        traits.register(self.root, "knowledge", name="Knowledge",
                        means="what this character has worked out",
                        trait_type="counter", base=0, min=0)
        R.add(self.root, R.blank(
            action="look", phase=R.AFTER, scope={"world": True},
            about="direct", name="reading a thing teaches you something",
            effects=[{"type": "set_trait", "role": "actor",
                      "trait": "knowledge", "change": 1}]))
        self.look("look lantern")
        self.assertEqual(traits.value(self.char1, "knowledge"), 1)

    def test_and_it_does_not_fire_when_the_look_was_refused(self):
        traits.register(self.root, "knowledge", name="Knowledge",
                        means="what this character has worked out",
                        trait_type="counter", base=0, min=0)
        traits.register(self.root, traits.LIGHT, name="Light",
                        means="how well lit it is here",
                        trait_type="counter", base=0, min=0)
        gear.recompute(self.char1)
        R.add(self.root, R.blank(
            action="look", phase=R.AFTER, scope={"world": True},
            about="direct", name="reading a thing teaches you something",
            effects=[{"type": "set_trait", "role": "actor",
                      "trait": "knowledge", "change": 1}]))
        self.assertIn("too dark", self.look("look lantern"))
        self.assertIn(traits.value(self.char1, "knowledge"), (None, 0))

    def test_so_wanting_the_knowledge_makes_looking_a_step(self):
        """
        What an NPC that wants to look at the painting actually wants. The
        planner reads the `after` rule's effect, not the description.
        """
        wanted = {"subject": "actor", "trait": "knowledge", "min": 1}
        self.assertTrue(C.achieves(
            {"type": "set_trait", "role": "actor", "trait": "knowledge",
             "change": 1}, wanted))


@tag("world")
class CarryingALampAbout(Looking):
    """
    Nothing here calls `gear.recompute`, and that is the point.

    Every test above that moved a lamp recomputed by hand afterwards, which hid
    a gap: `gear.recompute` answers for one person, a room is not a person, and
    so a room receiving a lit lamp recomputed nobody. The carrier saw by it and
    everybody else stood in the dark.
    """

    def setUp(self):
        super().setUp()
        traits.register(self.root, traits.LIGHT, name="Light",
                        means="how well lit it is here",
                        trait_type="counter", base=0, min=0)
        self.thing.db.trait_bonuses = {traits.LIGHT: 2}
        self.thing.db.bonus_when = "present"
        self.thing.db.bonus_while = "lit"
        verbs.apply_states(self.thing, add=["lit"], world_root=self.root)
        # Somebody else standing in the same cellar, who recomputes nothing.
        self.other = self.char2
        self.other.move_to(self.room2, quiet=True)

    def sees(self, who):
        from world import conditions

        return conditions.sees(who, self.room2, self.root)

    def test_a_lamp_in_the_room_lights_everybody_in_it(self):
        self.thing.move_to(self.room1, quiet=True)
        self.assertFalse(self.sees(self.char1))
        self.assertFalse(self.sees(self.other))

        self.thing.move_to(self.room2, quiet=True)
        self.assertTrue(self.sees(self.char1))
        self.assertTrue(self.sees(self.other),
                        "not only whoever was carrying it")

    def test_and_taking_it_away_leaves_them_in_the_dark(self):
        self.assertTrue(self.sees(self.other))
        self.thing.move_to(self.room1, quiet=True)
        self.assertFalse(self.sees(self.other))

    def test_a_carried_lamp_lights_its_carrier_and_nobody_else(self):
        """
        The boundary, asserted rather than wished away. `bonus_when: present`
        means *lying* in the room -- `gear.applies` tests `obj.location is
        room` -- so a lamp in somebody's hand is not present, and `carried` or
        `wielded` lights the person holding it and only them.

        A lamp carried into a cellar therefore lights the carrier while their
        companions stand in the dark, which is wrong about lamps and right about
        what the three conditions mean. Widening `present` to reach into
        people's hands would change what every charm and burden does, so it
        waits for a world that actually wants it.
        """
        self.thing.db.bonus_when = "carried"
        self.thing.move_to(self.room1, quiet=True)
        self.assertFalse(self.sees(self.char1))
        self.assertFalse(self.sees(self.other))

        self.thing.move_to(self.char1, quiet=True)
        self.assertTrue(self.sees(self.char1))
        self.assertFalse(self.sees(self.other),
                         "a lamp in a hand is not lying in the room")

    def test_putting_it_out_darkens_the_room_without_moving_it(self):
        self.assertTrue(self.sees(self.other))
        from world import effects

        effects.apply(self.char1, self.room2,
                      [{"type": "set_state", "name": "Lantern",
                        "remove": ["lit"]}],
                      bound={"direct": self.thing}, world_root=self.root)
        self.assertFalse(self.sees(self.other))


@tag("world")
class LookingAsksNobodysPermission(Looking):
    """
    Found in play, on the first world built with this engine.

    Every generated room has kinds, and `_admitted` asks a model once per kind
    per verb whether that sort of thing admits the verb -- so the first look in
    every room bought a call asking whether a cellar can be looked at. While it
    was in flight the room was held, so a second look was answered "someone else
    is already doing that", which is what a slow world looks like when it is
    also lying about who is slow.
    """

    def setUp(self):
        super().setUp()
        # What worldgen has given every room since phase 2.
        self.room2.db.kinds = ["cellar.n.01"]
        self.room2.db.desc = "A low stone cellar."

    def test_the_first_look_in_a_room_with_kinds_costs_nothing(self):
        said = self.look("look")
        self.assertEqual(self.asked, 0,
                         "no sort of thing has to be granted the right to be "
                         "looked at")
        self.assertIn("low stone cellar", said)

    def test_and_neither_does_looking_at_a_thing_with_kinds(self):
        self.thing.db.kinds = ["lantern.n.01"]
        self.look("look lantern")
        self.assertEqual(self.asked, 0)

    def test_nothing_is_written_down_about_whether_it_may_be_looked_at(self):
        """
        The other half of why this is wrong. An admission is permanent and
        first-answer-wins, so one model saying a ghost cannot be looked at
        would freeze that for every ghost the world ever holds. Sight belongs
        to `visible_to` and a check rule, which is per-object and reversible.
        """
        from world import kinds

        self.look("look")
        self.assertIsNone(kinds.admits(self.root, ["cellar.n.01"], "look"))

    def test_a_verb_that_does_something_is_still_asked_about(self):
        """The exemption is for looking, not a hole in the admission question."""
        from world import actions

        self.assertEqual(set(actions.ALWAYS_ADMITTED), {"look"})


@tag("world")
class BeingToldWhoIsBusy(Looking):
    """
    "Someone else is already doing that" is true of another player and a lie to
    the person who typed it twice because the world had not answered yet.
    """

    def test_your_own_attempt_says_so(self):
        attempt_mod._hold(self.thing, "power", self.char1)
        self.assertIn("You are already doing that",
                      attempt_mod._still_waiting(self.thing, "power",
                                                 self.char1))

    def test_somebody_elses_still_says_someone_else(self):
        attempt_mod._hold(self.thing, "power", self.char2)
        self.assertIn("Someone else",
                      attempt_mod._still_waiting(self.thing, "power",
                                                 self.char1))

    def test_a_hold_is_dropped_when_the_attempt_ends(self):
        self.look("look lantern")
        self.assertFalse(attempt_mod._busy(self.thing, "look"))

    def test_and_a_held_verb_is_refused_rather_than_run_twice(self):
        attempt_mod._hold(self.thing, "look", self.char2)
        said = self.look("look lantern")
        self.assertIn("already doing that", said)
        self.assertNotIn("dented brass lantern", said)

