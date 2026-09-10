"""
Which rule wins, and why.

This is the phase where a mistake costs most and a test costs least. Nothing
here runs a rule; it decides which rules are about an attempt and in what
order, and if that order is wrong then `power datapad` powers the ship you
happen to be standing in and no amount of careful rule-writing saves it.

Inform's hardest bug class is rule ordering. Its answer is `RULES ON` -- make
the order visible -- and ours is the same, plus this: the sort key is one
printable tuple and every tie in it is broken, so two runs of the same world
cannot disagree.
"""

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from world import rulebooks as R
from world import zones


@tag("unit")
class MakingARule(SimpleTestCase):

    def test_a_blank_rule_has_every_slot(self):
        rule = R.blank()
        for slot in ("id", "name", "phase", "action", "scope", "about",
                     "when", "conditions", "effects", "contest", "outcome",
                     "listed", "source", "born"):
            self.assertIn(slot, rule, slot)

    def test_a_rule_about_no_action_in_particular_is_allowed(self):
        """"Nothing works while you are dead", said once instead of per verb."""
        self.assertIsNone(R.blank(action=None)["action"])

    def test_an_unknown_phase_falls_back_to_check(self):
        """The safe phase: a check can only ever refuse, never change meaning."""
        self.assertEqual(R.blank(phase="whenever")["phase"], R.CHECK)

    def test_a_scope_keeps_only_one_closed_key(self):
        """A rule is filed in one place. Two would be two rules."""
        self.assertEqual(R._clean_scope({"kind": "x", "room": 4}),
                         {"kind": "x"})
        self.assertEqual(R._clean_scope({"nonsense": 1}), {"world": True})
        self.assertEqual(R._clean_scope(None), {"world": True})


@tag("world")
class StoringRules(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True

    def test_a_rule_gets_an_id_and_comes_back(self):
        rule = R.add(self.root, R.blank(action="power", name="first"))
        self.assertEqual(rule["id"], "r1")
        self.assertEqual(R.get(self.root, "r1")["name"], "first")

    def test_ids_run_in_order_so_the_tie_break_is_readable(self):
        first = R.add(self.root, R.blank(action="power"))
        second = R.add(self.root, R.blank(action="power"))
        self.assertEqual((first["id"], second["id"]), ("r1", "r2"))

    def test_an_action_is_folded_to_its_canonical_verb(self):
        rule = R.add(self.root, R.blank(action="examine"))
        self.assertEqual(rule["action"], "look")

    def test_a_rule_can_be_unlisted_and_put_back(self):
        rule = R.add(self.root, R.blank(action="power"))
        R.set_listed(self.root, rule["id"], False)
        self.assertFalse(R.get(self.root, rule["id"])["listed"])
        R.set_listed(self.root, rule["id"], True)
        self.assertTrue(R.get(self.root, rule["id"])["listed"])

    def test_an_unlisted_rule_is_not_gathered(self):
        rule = R.add(self.root, R.blank(action="power"))
        self.assertEqual(len(R.gather(self.root, "power", actor=self.char1)), 1)
        R.set_listed(self.root, rule["id"], False)
        self.assertEqual(R.gather(self.root, "power", actor=self.char1), [])


@tag("world")
class WhichRulesApply(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room2.db.world_root = self.root
        self.char1.move_to(self.room2, quiet=True)

    def gather(self, **kwargs):
        return R.gather(self.root, kwargs.pop("action", "power"),
                        bound=kwargs.pop("bound", {}), actor=self.char1,
                        **kwargs)

    def test_a_world_rule_always_applies(self):
        R.add(self.root, R.blank(action="power", scope={"world": True}))
        self.assertEqual(len(self.gather()), 1)

    def test_a_rule_for_another_action_does_not(self):
        R.add(self.root, R.blank(action="launch"))
        self.assertEqual(self.gather(action="power"), [])

    def test_a_rule_for_any_action_applies_to_every_one(self):
        R.add(self.root, R.blank(action=None))
        self.assertEqual(len(self.gather(action="power")), 1)
        self.assertEqual(len(self.gather(action="launch")), 1)

    def test_a_rule_about_this_room(self):
        R.add(self.root, R.blank(action="power",
                                 scope={"room": self.room2.id}))
        self.assertEqual(len(self.gather()), 1)

    def test_but_not_about_another_room(self):
        R.add(self.root, R.blank(action="power",
                                 scope={"room": self.room1.id}))
        self.assertEqual(self.gather(), [])

    def test_a_rule_about_a_zone_in_the_chain(self):
        station = zones.register(self.root, "Station")
        ship = zones.register(self.root, "Ship", parent=station)
        zones.assign(self.root, self.room2, ship)
        R.add(self.root, R.blank(action="power", scope={"zone": station}))
        self.assertEqual(len(self.gather()), 1, "a parent zone still encloses")

    def test_but_not_about_a_zone_somewhere_else(self):
        zones.register(self.root, "Elsewhere")
        R.add(self.root, R.blank(action="power",
                                 scope={"zone": "elsewhere"}))
        self.assertEqual(self.gather(), [])

    def test_a_rule_about_one_particular_thing(self):
        R.add(self.root, R.blank(action="power",
                                 scope={"object": self.obj1.id}))
        self.assertEqual(self.gather(bound={"direct": self.obj1}).__len__(), 1)
        self.assertEqual(self.gather(bound={"direct": self.obj2}), [])

    def test_a_rule_about_a_sort_of_thing(self):
        self.obj1.db.kinds = ["sword.n.01"]
        R.add(self.root, R.blank(action="power",
                                 scope={"kind": "weapon.n.01"}))
        self.assertEqual(len(self.gather(bound={"direct": self.obj1})), 1,
                         "a sword is a weapon")
        self.assertEqual(self.gather(bound={"direct": self.obj2}), [])

    def test_a_guard_that_does_not_hold_keeps_a_rule_out(self):
        R.add(self.root, R.blank(
            action="power", scope={"world": True},
            when=[{"subject": "actor", "is": ["seated"]}]))
        self.assertEqual(self.gather(), [])

    def test_and_one_that_holds_lets_it_in(self):
        from world import verbs

        verbs.apply_states(self.char1, add=["seated"], world_root=self.root)
        R.add(self.root, R.blank(
            action="power", scope={"world": True},
            when=[{"subject": "actor", "is": ["seated"]}]))
        self.assertEqual(len(self.gather()), 1)

    def test_gathering_one_phase_at_a_time(self):
        R.add(self.root, R.blank(action="power", phase=R.CHECK))
        R.add(self.root, R.blank(action="power", phase=R.CARRY_OUT))
        self.assertEqual(len(self.gather(phase=R.CHECK)), 1)
        self.assertEqual(len(self.gather(phase=R.CARRY_OUT)), 1)
        self.assertEqual(len(self.gather()), 2)


@tag("world")
class TheEnclosureCase(EvenniaTest):
    """
    `power datapad` against `power`, which is the whole reason for `about`.

    A rule scoped to `spacecraft.n.01` might mean the ship you are standing in
    or a model spaceship on the shelf. Saying which is not decoration.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room2.db.world_root = self.root
        self.room2.db.kinds = ["spacecraft.n.01"]
        self.char1.move_to(self.room2, quiet=True)
        self.ship_rule = R.add(self.root, R.blank(
            action="power", scope={"kind": "spacecraft.n.01"},
            about=R.ENCLOSURE, name="powering aboard a ship powers the ship"))

    def test_a_rule_about_the_enclosure_applies_when_you_are_in_one(self):
        found = R.gather(self.root, "power", actor=self.char1)
        self.assertEqual([r["id"] for r in found], [self.ship_rule["id"]])

    def test_and_not_when_you_are_somewhere_else(self):
        self.char1.move_to(self.room1, quiet=True)
        self.assertEqual(R.gather(self.root, "power", actor=self.char1), [])

    def test_a_thing_you_named_beats_the_place_you_are_standing_in(self):
        """
        The example the whole design was argued from. Both rules apply; the
        datapad's wins, because a player who named a thing meant it.
        """
        self.obj1.db.kinds = ["datapad"]
        self.obj1.move_to(self.room2, quiet=True)
        pad_rule = R.add(self.root, R.blank(
            action="power", scope={"kind": "datapad"}, about="direct",
            name="powering a datapad wakes it"))

        found = R.gather(self.root, "power", bound={"direct": self.obj1},
                         actor=self.char1)
        self.assertEqual([r["id"] for r in found],
                         [pad_rule["id"], self.ship_rule["id"]])

    def test_a_model_ship_on_the_shelf_is_not_the_ship_you_are_in(self):
        """
        The reason `about` cannot be inferred. A rule meaning the enclosure
        must not fire because somebody is carrying a toy of the same kind.
        """
        self.char1.move_to(self.room1, quiet=True)
        self.obj1.db.kinds = ["spacecraft.n.01"]
        self.obj1.move_to(self.char1, quiet=True)
        self.assertEqual(
            R.gather(self.root, "power", bound={"direct": self.obj1},
                     actor=self.char1),
            [], "the rule was about the ship you are in")


@tag("world")
class MostSpecificFirst(EvenniaTest):
    """Every tier, and every tie-break, asserted."""

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room2.db.world_root = self.root
        self.room2.db.kinds = ["spacecraft.n.01"]
        self.char1.move_to(self.room2, quiet=True)
        self.obj1.db.kinds = ["sword.n.01"]
        self.obj1.move_to(self.room2, quiet=True)

    def order(self):
        found = R.gather(self.root, "power", bound={"direct": self.obj1},
                         actor=self.char1)
        return [r["name"] for r in found]

    def test_the_whole_ladder_at_once(self):
        station = zones.register(self.root, "Station")
        zones.assign(self.root, self.room2, station)
        R.add(self.root, R.blank(action="power", scope={"world": True},
                                 name="world"))
        R.add(self.root, R.blank(action="power", scope={"zone": station},
                                 name="zone"))
        R.add(self.root, R.blank(action="power",
                                 scope={"room": self.room2.id}, name="room"))
        R.add(self.root, R.blank(action="power",
                                 scope={"kind": "spacecraft.n.01"},
                                 about=R.ENCLOSURE, name="enclosure kind"))
        R.add(self.root, R.blank(action="power", scope={"kind": "sword.n.01"},
                                 about="direct", name="named kind"))
        R.add(self.root, R.blank(action="power",
                                 scope={"object": self.obj1.id},
                                 name="object"))
        self.assertEqual(self.order(),
                         ["object", "named kind", "enclosure kind", "room",
                          "zone", "world"])

    def test_a_named_action_beats_a_rule_about_any_action(self):
        R.add(self.root, R.blank(action=None, name="any"))
        R.add(self.root, R.blank(action="power", name="named"))
        self.assertEqual(self.order(), ["named", "any"])

    def test_deeper_in_the_taxonomy_comes_first(self):
        R.add(self.root, R.blank(action="power", scope={"kind": "weapon.n.01"},
                                 name="weapon"))
        R.add(self.root, R.blank(action="power", scope={"kind": "sword.n.01"},
                                 name="sword"))
        self.assertEqual(self.order(), ["sword", "weapon"])

    def test_deeper_in_the_zone_tree_comes_first(self):
        station = zones.register(self.root, "Station")
        bay = zones.register(self.root, "Bay", parent=station)
        zones.assign(self.root, self.room2, bay)
        R.add(self.root, R.blank(action="power", scope={"zone": station},
                                 name="station"))
        R.add(self.root, R.blank(action="power", scope={"zone": bay},
                                 name="bay"))
        self.assertEqual(self.order(), ["bay", "station"])

    def test_a_guarded_rule_beats_an_open_one(self):
        R.add(self.root, R.blank(action="power", name="open"))
        R.add(self.root, R.blank(
            action="power", name="guarded",
            when=[{"subject": "direct", "lacks": ["burning"]}]))
        self.assertEqual(self.order(), ["guarded", "open"])

    def test_more_guards_beat_fewer(self):
        R.add(self.root, R.blank(
            action="power", name="one",
            when=[{"subject": "direct", "lacks": ["burning"]}]))
        R.add(self.root, R.blank(
            action="power", name="two",
            when=[{"subject": "direct", "lacks": ["burning"]},
                  {"subject": "direct", "lacks": ["wet"]}]))
        self.assertEqual(self.order(), ["two", "one"])

    def test_the_older_rule_wins_a_tie(self):
        R.add(self.root, R.blank(action="power", name="first"))
        R.add(self.root, R.blank(action="power", name="second"))
        self.assertEqual(self.order(), ["first", "second"])

    def test_nothing_ever_actually_ties(self):
        """
        The id is last in the key, so two rules alike in every other way are
        still ordered -- and ordered the same way twice.
        """
        for _ in range(5):
            R.add(self.root, R.blank(action="power", name="same"))
        first = [r["id"] for r in R.gather(self.root, "power",
                                           actor=self.char1)]
        second = [r["id"] for r in R.gather(self.root, "power",
                                            actor=self.char1)]
        self.assertEqual(first, second)
        self.assertEqual(len(set(first)), 5)

    def test_the_key_can_be_read(self):
        """`rules` has to be able to print why one rule beat another."""
        rule = R.add(self.root, R.blank(action="power",
                                        scope={"kind": "sword.n.01"}))
        key = R.rank(rule, 1, self.root)
        self.assertIsInstance(key, tuple)
        self.assertEqual(key[0], 0, "a named action")
        self.assertEqual(key[1], 1, "matched at the named-kind tier")


@tag("world")
class RulesLeftBehind(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root

    def test_a_rule_about_a_thing_that_is_gone_is_an_orphan(self):
        R.add(self.root, R.blank(action="power",
                                 scope={"object": self.obj1.id}))
        self.assertEqual(R.orphans(self.root), [])
        self.obj1.delete()
        self.assertEqual(len(R.orphans(self.root)), 1)

    def test_and_is_not_gathered(self):
        R.add(self.root, R.blank(action="power",
                                 scope={"object": self.obj1.id}))
        self.obj1.delete()
        self.assertEqual(R.gather(self.root, "power", actor=self.char1), [])

    def test_a_scope_reads_as_a_place(self):
        self.assertEqual(R.said_scope({"world": True}), "everywhere")
        self.assertEqual(R.said_scope({"kind": "sword.n.01"}), "any sword")


@tag("unit")
class TheBridgeFromLearnedRules(SimpleTestCase):
    """
    A verb rule is preconditions plus effects for a whole world, which is
    exactly a stack of world-scope checks and one world-scope carry-out.
    """

    def phases(self, rule):
        return [(r["phase"], r["name"])
                for r in R.from_verb_rule(rule, "power")]

    def test_a_learned_rule_becomes_checks_and_a_carry_out(self):
        found = self.phases({"valid": True,
                             "requires": {"direct": {"is": ["intact"]}},
                             "effects": [{"type": "set_state",
                                          "role": "direct",
                                          "add": ["powered"]}]})
        self.assertEqual([phase for phase, _n in found],
                         [R.CHECK, R.CARRY_OUT])

    def test_a_rule_that_does_nothing_still_settles_the_verb(self):
        """`sing` has no effects, and deciding that was still a decision."""
        found = self.phases({"valid": True, "effects": []})
        self.assertEqual([phase for phase, _n in found], [R.CARRY_OUT])

    def test_but_no_rule_at_all_bridges_to_nothing(self):
        """
        The pipeline says "nothing learned" by handing over an empty rule.
        Bridging it would put a nameless do-nothing carry-out in every book,
        and a verb that silently succeeds is the failure this design is for.
        """
        self.assertEqual(R.from_verb_rule({}, "power"), [])
        self.assertEqual(R.from_verb_rule(None, "power"), [])

    def test_a_refusal_becomes_a_check_nothing_can_pass(self):
        found = R.from_verb_rule({"valid": False, "reason": "No such thing."},
                                 "power")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["phase"], R.CHECK)
        self.assertIn("never", found[0]["conditions"][0])

    def test_preconditions_of_a_shape_nobody_expected_ask_for_nothing(self):
        """
        A learned rule is stored model output, and `requires` has arrived as a
        list of conditions rather than a mapping of roles. Read as a mapping
        that is an AttributeError inside a gather, which takes down the whole
        attempt instead of refusing one rule.
        """
        found = self.phases({"valid": True,
                             "requires": [{"subject": "direct",
                                           "is": ["intact"]}],
                             "effects": [{"type": "set_state",
                                          "role": "direct",
                                          "add": ["powered"]}]})
        self.assertEqual([phase for phase, _n in found], [R.CARRY_OUT])

