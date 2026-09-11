"""
A world writing its own rules, and the spaceship example running.

The last test here is the one the whole design was argued from. `power`
aboard a ship powers the ship; `power datapad` powers the datapad; `launch`
names the thing it launches even though nobody typed it. None of those was
expressible when this started.

The rest is the discipline that makes it safe: a scope must come from the
menu it was offered, a predicate must be one the game can evaluate, an
effect must be one it can apply, and a model that cannot say a thing is
allowed to say so.
"""

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from tests.support import FakeAccount, as_json, immediately, replying
from world import attempt as attempt_mod
from world import actions, kinds, rule_gen, verbs, zones
from world import rulebooks as R


@tag("unit")
class TheScopeCeiling(SimpleTestCase):
    """
    A rule filed near the root of the taxonomy is a rule about everything,
    and a model offered one will sometimes take it.
    """

    def test_the_scopes_that_would_cover_the_world_are_refused(self):
        for kind in ("physical_entity.n.01", "object.n.01", "artifact.n.01",
                     "instrumentality.n.03"):
            self.assertTrue(rule_gen.too_general({"kind": kind}), kind)

    def test_the_ones_worth_having_a_rule_about_are_not(self):
        for kind in ("device.n.01", "container.n.01", "publication.n.01",
                     "sword.n.01", "spacecraft.n.01"):
            self.assertFalse(rule_gen.too_general({"kind": kind}), kind)

    def test_a_zone_or_the_world_is_never_too_general(self):
        """They are as general as they are, and both are legitimate."""
        self.assertFalse(rule_gen.too_general({"world": True}))
        self.assertFalse(rule_gen.too_general({"zone": "kepler-9"}))


@tag("world")
class TheMenu(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room2.db.world_root = self.root
        self.char1.move_to(self.room2, quiet=True)

    def tokens(self, bound=None):
        return [t for t, _s, _sc in rule_gen.menu(self.root, bound,
                                                  self.char1)]

    def test_the_world_is_always_offered(self):
        self.assertIn("world", self.tokens())

    def test_a_named_things_kind_is_offered_with_its_ancestors(self):
        self.obj1.db.kinds = ["sword.n.01"]
        found = self.tokens({"direct": self.obj1})
        self.assertIn("sword.n.01", found)
        self.assertIn("weapon.n.01", found)

    def test_but_never_one_above_the_ceiling(self):
        self.obj1.db.kinds = ["sword.n.01"]
        for token in self.tokens({"direct": self.obj1}):
            self.assertFalse(rule_gen.too_general({"kind": token}), token)

    def test_the_sort_of_place_you_are_in_is_offered(self):
        self.room2.db.kinds = ["spacecraft.n.01"]
        self.assertIn("spacecraft.n.01", self.tokens())

    def test_and_so_is_the_area(self):
        planet = zones.register(self.root, "Kepler Nine")
        zones.assign(self.root, self.room2, planet)
        self.assertIn(planet, self.tokens())

    def test_the_menu_is_most_specific_first(self):
        self.obj1.db.kinds = ["sword.n.01"]
        self.room2.db.kinds = ["spacecraft.n.01"]
        found = self.tokens({"direct": self.obj1})
        self.assertLess(found.index("sword.n.01"),
                        found.index("spacecraft.n.01"))
        self.assertEqual(found[-1], "world")


@tag("unit")
class ReadingWhatCameBack(SimpleTestCase):

    def setUp(self):
        self.offered = [("sword.n.01", "a sword", {"kind": "sword.n.01"}),
                        ("world", "everywhere", {"world": True})]

    def keep(self, *rules):
        return rule_gen.validate({"rules": list(rules)}, self.offered, "cut")

    def test_a_good_rule_is_kept(self):
        kept, complaints = self.keep(
            {"phase": "check", "scope": "sword.n.01", "about": "direct",
             "name": "a blunt sword will not cut",
             "conditions": [{"subject": "direct", "lacks": ["blunt"]}]})
        self.assertEqual(complaints, [])
        self.assertEqual(kept[0]["scope"], {"kind": "sword.n.01"})
        self.assertEqual(kept[0]["action"], "cut")

    def test_a_scope_that_was_not_offered_is_refused(self):
        kept, complaints = self.keep(
            {"phase": "check", "scope": "artifact.n.01",
             "conditions": [{"subject": "direct", "is": ["x"]}]})
        self.assertEqual(kept, [])
        self.assertIn("not one of the scopes offered", complaints[0])

    def test_an_invented_phase_is_refused(self):
        kept, complaints = self.keep({"phase": "sometimes", "scope": "world"})
        self.assertEqual(kept, [])
        self.assertIn("unknown phase", complaints[0])

    def test_a_predicate_nothing_can_evaluate_is_dropped(self):
        kept, complaints = self.keep(
            {"phase": "check", "scope": "world",
             "conditions": [{"subject": "direct", "smells_nice": True}]})
        self.assertEqual(kept, [])
        self.assertTrue(any("asking nothing" in c for c in complaints))

    def test_an_effect_nothing_can_apply_is_dropped(self):
        kept, complaints = self.keep(
            {"phase": "carry_out", "scope": "world",
             "effects": [{"type": "summon_dragon"}]})
        self.assertEqual(kept, [])
        self.assertTrue(any("no such effect" in c for c in complaints))

    def test_a_check_that_checks_nothing_is_refused(self):
        kept, complaints = self.keep({"phase": "check", "scope": "world"})
        self.assertEqual(kept, [])
        self.assertIn("checks nothing", complaints[0])

    def test_a_carry_out_that_does_nothing_is_refused(self):
        kept, complaints = self.keep({"phase": "carry_out", "scope": "world"})
        self.assertEqual(kept, [])
        self.assertIn("changes nothing", complaints[0])

    def test_the_good_rules_survive_the_bad_ones(self):
        kept, complaints = self.keep(
            {"phase": "nonsense", "scope": "world"},
            {"phase": "carry_out", "scope": "world",
             "effects": [{"type": "set_state", "role": "direct",
                          "add": ["cut"]}]})
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(complaints), 1)

    def test_a_reply_that_is_not_a_reply(self):
        kept, complaints = rule_gen.validate("nonsense", self.offered, "cut")
        self.assertEqual(kept, [])
        self.assertTrue(complaints)


@tag("world")
class TheSpaceshipExample(EvenniaTest):
    """
    The four lines the whole design was argued from, run end to end.

    Not one of them was expressible when this began: `power` resolved to a
    single rule per world, and `launch` could not name the thing it launches
    because that thing is the room.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room2.db.world_root = self.root
        self.room2.db.is_ai_room = True
        self.room2.db.kinds = ["spacecraft.n.01"]
        self.char1.move_to(self.room2, quiet=True)

        self.pad = self.obj1
        self.pad.key = "Datapad"
        self.pad.db.kinds = ["datapad"]
        self.pad.db.affordances = {"power": True}
        self.pad.move_to(self.room2, quiet=True)
        for verb in ("power", "launch"):
            kinds.admit(self.root, ["datapad"], verb, True)
            kinds.admit(self.root, ["spacecraft.n.01"], verb, True)

        # What a world would have been asked for and answered, written down
        # directly: this is about the engine running them, not about a model.
        R.add(self.root, R.blank(
            action="power", phase=R.CARRY_OUT, scope={"kind": "datapad"},
            about="direct", name="powering a datapad wakes it",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["powered"]}]))
        R.add(self.root, R.blank(
            action="power", phase=R.INSTEAD,
            scope={"kind": "spacecraft.n.01"}, about=R.ENCLOSURE,
            name="powering aboard a ship means powering the ship",
            when=[{"subject": "direct", "unbound": True}],
            effects=[{"type": "try", "action": "power",
                      "roles": {"direct": {"enclosure": "spacecraft.n.01"}}}]))
        R.add(self.root, R.blank(
            action="launch", phase=R.INSTEAD,
            scope={"kind": "spacecraft.n.01"}, about=R.ENCLOSURE,
            name="launching aboard a ship means launching the ship",
            when=[{"subject": "direct", "unbound": True}],
            effects=[{"type": "try", "action": "launch",
                      "roles": {"direct": {"enclosure": "spacecraft.n.01"}}}]))
        R.add(self.root, R.blank(
            action="power", phase=R.CARRY_OUT,
            scope={"kind": "spacecraft.n.01"}, about="direct",
            name="powering a ship wakes its reactor",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["powered"]}]))
        R.add(self.root, R.blank(
            action="launch", phase=R.CHECK,
            scope={"kind": "spacecraft.n.01"}, about="direct",
            name="a ship only launches under power",
            conditions=[{"subject": "direct", "is": ["powered"]}]))
        R.add(self.root, R.blank(
            action="launch", phase=R.CARRY_OUT,
            scope={"kind": "spacecraft.n.01"}, about="direct",
            name="launching takes the ship up",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["in_flight"]}]))
        actions.declare(self.root, "power",
                        [{"role": "direct", "optional": True}])
        actions.declare(self.root, "launch",
                        [{"role": "direct", "optional": True}])

    def try_it(self, raw):
        said = []
        with immediately(), replying(
                as_json({"actor": "Done.", "room": "{actor} does it."})):
            attempt_mod.attempt(
                self.char1, raw, FakeAccount(),
                on_message=lambda a, r=None: said.append(a or ""))
        return " ".join(s for s in said if s)

    def test_power_datapad_powers_the_datapad(self):
        self.try_it("power datapad")
        self.assertIn("powered", verbs.states(self.pad))
        self.assertNotIn("powered", verbs.states(self.room2),
                         "the ship should be untouched")

    def test_power_aboard_a_ship_powers_the_ship(self):
        """Typed bare, with nothing named. The redirect supplies the ship."""
        self.try_it("power")
        self.assertIn("powered", verbs.states(self.room2))
        self.assertNotIn("powered", verbs.states(self.pad))

    def test_launch_is_refused_while_the_ship_is_cold(self):
        said = self.try_it("launch")
        self.assertIn("not powered", said)
        self.assertNotIn("in_flight", verbs.states(self.room2))

    def test_and_works_once_the_ship_has_power(self):
        verbs.apply_states(self.room2, add=["powered"], world_root=self.root)
        self.try_it("launch")
        self.assertIn("in_flight", verbs.states(self.room2))


@tag("world")
class WordsARuleCoined(EvenniaTest):
    """
    A rule may set a state the world has never heard of, and the string lands
    on the object whether or not anybody registered it. What would be lost is
    its meaning and its group -- and the group is what makes powering a thing
    on take it out of being off, with no rule saying so.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room2.db.world_root = self.root
        self.char1.move_to(self.room2, quiet=True)

    def written(self, reply):
        kept = []
        with immediately(), replying(as_json(reply)):
            rule_gen.learn(FakeAccount(), self.root, "power",
                           {"direct": self.obj1}, self.char1,
                           on_success=kept.extend,
                           on_error=lambda err: self.fail(err))
        return kept

    def test_a_state_a_rule_used_joins_the_vocabulary(self):
        self.written({
            "rules": [{"phase": "carry_out", "scope": "world",
                       "name": "powering wakes it",
                       "effects": [{"type": "set_state", "role": "direct",
                                    "add": ["powered"]}]}],
            "new_states": [{"slug": "powered", "means": "under its own power",
                            "group": "power"}]})
        self.assertIn("powered", verbs.vocabulary(self.root))
        self.assertEqual(verbs.group_of(self.root, "powered"), "power")

    def test_a_trait_a_rule_used_joins_the_register(self):
        from world import traits

        self.written({
            "rules": [{"phase": "check", "scope": "world",
                       "name": "you need the knack",
                       "conditions": [{"subject": "actor",
                                       "trait": "piloting", "min": 5}]}],
            "new_traits": [{"slug": "piloting", "name": "Piloting",
                            "means": "flying a ship", "trait_type": "counter"}]})
        self.assertIn("piloting", traits.vocabulary(self.root))

    def test_a_reply_declaring_nothing_is_still_fine(self):
        kept = self.written({
            "rules": [{"phase": "carry_out", "scope": "world",
                       "effects": [{"type": "set_state", "role": "direct",
                                    "add": ["powered"]}]}]})
        self.assertEqual(len(kept), 1)

    def test_what_a_model_could_not_say_is_kept_rather_than_guessed(self):
        kept = self.written({"rules": [],
                             "cannot_say": "nothing here can open an airlock"})
        self.assertEqual(kept, [])
        self.assertEqual([r for r in R.all_rules(self.root)
                          if r["source"] == "generated"], [],
                         "a world with nothing to say writes nothing")


@tag("world")
class AFreshWorldLearningAVerb(EvenniaTest):
    """
    The whole of phase 8 in one road: nobody has written a rule, the player
    types a verb, the world is asked, the answer is filed against a scope, and
    the same attempt carries it out.

    `TheSpaceshipExample` writes its rules by hand on purpose -- it is about
    the engine running them. This is about the engine getting them.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room2.db.world_root = self.root
        self.room2.db.is_ai_room = True
        self.room2.db.kinds = ["spacecraft.n.01"]
        self.char1.move_to(self.room2, quiet=True)

        self.pad = self.obj1
        self.pad.key = "Datapad"
        self.pad.db.kinds = ["datapad"]
        self.pad.db.affordances = {"power": True}
        self.pad.move_to(self.room2, quiet=True)
        kinds.admit(self.root, ["datapad"], "power", True)
        actions.declare(self.root, "power",
                        [{"role": "direct", "optional": True}])

    #: What a model is asked for, and a plausible answer: one rule, filed
    #: against the kind rather than against this one datapad.
    ANSWER = {
        "rules": [{"phase": "carry_out", "scope": "datapad",
                   "about": "direct", "name": "powering a datapad wakes it",
                   "effects": [{"type": "set_state", "role": "direct",
                                "add": ["powered"]}]}],
        "new_states": [{"slug": "powered", "means": "under its own power",
                        "group": "power"}],
    }
    NARRATION = {"actor": "The screen lights up.",
                 "room": "{actor} powers the datapad."}

    def try_it(self, raw, *replies):
        """One attempt. Answers with what was said, and how often it asked."""
        said = []
        with immediately(), replying(*replies) as script:
            attempt_mod.attempt(
                self.char1, raw, FakeAccount(),
                on_message=lambda a, r=None: said.append(a or ""))
            asked = script.count
        return " ".join(s for s in said if s), asked

    def test_it_asks_once_files_a_rule_and_carries_it_out(self):
        said, asked = self.try_it("power datapad", as_json(self.ANSWER),
                                  as_json(self.NARRATION))
        self.assertEqual(asked, 2, "one rule call and one narration, no more")

        filed = [r for r in R.all_rules(self.root) if r["source"] == "generated"]
        self.assertEqual(len(filed), 1)
        self.assertEqual(filed[0]["scope"], {"kind": "datapad"})
        self.assertEqual(filed[0]["phase"], R.CARRY_OUT)

        self.assertIn("powered", verbs.states(self.pad))
        self.assertIn("lights up", said)

    def test_and_does_not_ask_again_next_time(self):
        """
        What the old design could not do. A rule filed against the kind is a
        rule about every datapad, so the second one costs a narration and
        nothing else.
        """
        self.try_it("power datapad", as_json(self.ANSWER),
                    as_json(self.NARRATION))
        before = len([r for r in R.all_rules(self.root)
                      if r["source"] == "generated"])

        second = self.obj2
        second.key = "Slate"
        second.db.kinds = ["datapad"]
        second.db.affordances = {"power": True}
        second.move_to(self.room2, quiet=True)

        self.try_it("power slate", as_json(self.NARRATION))
        self.assertIn("powered", verbs.states(second))
        self.assertEqual(len([r for r in R.all_rules(self.root)
                              if r["source"] == "generated"]), before,
                         "the second datapad should buy no new rule")

    def test_a_rule_filed_too_generally_is_refused_rather_than_stored(self):
        self.try_it("power datapad",
                    as_json({"rules": [dict(self.ANSWER["rules"][0],
                                            scope="physical_entity.n.01")]}),
                    as_json(self.NARRATION))
        self.assertEqual([r for r in R.all_rules(self.root)
                          if r["source"] == "generated"], [])
        self.assertNotIn("powered", verbs.states(self.pad))

