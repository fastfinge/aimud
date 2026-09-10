"""
A place can be a sort of place, and can be in a condition.

Phase 2, and the reason it comes before the rulebooks: none of
`{"enclosure": "spacecraft.n.01"}` is sayable until a room or a zone can be a
spacecraft. `launch` cannot name the thing it launches, because that thing is
the room -- and a room had no kind and no condition to its name.

The walk is the piece worth testing hardest. A one-room ship is a room of that
kind; a ship with a bridge and an engine room is a zone of it; a bridge inside
a ship inside a station is three levels deep. All three have to answer the same
question, and a caller must not have to know which case it got.
"""

from unittest import mock

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from world import kinds, verbs, zones


@tag("unit")
class OneKindBeingAnother(SimpleTestCase):

    def test_a_kind_is_itself(self):
        self.assertTrue(kinds.is_a(None, "sword.n.01", "sword.n.01"))

    def test_a_kind_is_what_it_descends_from(self):
        self.assertTrue(kinds.is_a(None, "sword.n.01", "weapon.n.01"))
        self.assertTrue(kinds.is_a(None, "spacecraft.n.01", "vehicle.n.01"))

    def test_but_not_the_other_way_round(self):
        self.assertFalse(kinds.is_a(None, "weapon.n.01", "sword.n.01"))

    def test_unrelated_kinds_are_unrelated(self):
        self.assertFalse(kinds.is_a(None, "sword.n.01", "publication.n.01"))

    def test_a_spacecraft_is_not_a_machine_however_much_one_might_want_it(self):
        """
        Recorded because the spec's worked example first assumed otherwise.

        WordNet puts a spacecraft under `vehicle`, not under `device` or
        `machine`, so taxonomic reuse is thinner than it looks and the ship
        needs its own rule. Better to have this asserted than rediscovered.
        """
        self.assertFalse(kinds.is_a(None, "spacecraft.n.01", "machine.n.01"))
        self.assertFalse(kinds.is_a(None, "spacecraft.n.01", "device.n.01"))

    def test_nothing_is_nothing(self):
        self.assertFalse(kinds.is_a(None, "", "weapon.n.01"))
        self.assertFalse(kinds.is_a(None, "sword.n.01", ""))

    def test_any_of_several_kinds_may_match(self):
        """The sword with runes: a weapon by one kind, writing by the other."""
        both = ["sword.n.01", "inscription.n.01"]
        self.assertTrue(kinds.any_is_a(None, both, "weapon.n.01"))
        self.assertTrue(kinds.any_is_a(None, both, "written_communication.n.01"))
        self.assertFalse(kinds.any_is_a(None, both, "food.n.01"))

    def test_the_taxonomy_is_not_where_intuition_puts_it(self):
        """
        Three assumptions of mine were wrong today, so here they are as tests.

        An inscription is not a `publication` -- it is `written_communication`,
        which a book is not. A flyer grounds as `circular.n.01`, which is a
        publication, but an inscription carved on a blade is not published.
        Whatever a rule gets filed against, it should be a scope somebody has
        checked rather than one that reads plausibly.
        """
        self.assertFalse(kinds.is_a(None, "inscription.n.01",
                                    "publication.n.01"))
        self.assertTrue(kinds.is_a(None, "book.n.01", "publication.n.01"))
        self.assertFalse(kinds.is_a(None, "circular.n.01", "book.n.01"))


@tag("world")
class FindingTheEnclosingPlace(EvenniaTest):
    """The walk: the room, then the zones outward from it."""

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room2.db.world_root = self.root

    def test_a_one_room_ship_is_the_room_itself(self):
        self.room2.db.kinds = ["spacecraft.n.01"]
        self.char1.move_to(self.room2, quiet=True)
        what, where = kinds.enclosure(self.char1, "spacecraft.n.01",
                                      world_root=self.root)
        self.assertEqual(what, kinds.ROOM)
        self.assertEqual(where, self.room2)

    def test_a_room_answers_about_itself(self):
        self.room2.db.kinds = ["spacecraft.n.01"]
        what, where = kinds.enclosure(self.room2, "spacecraft.n.01",
                                      world_root=self.root)
        self.assertEqual((what, where), (kinds.ROOM, self.room2))

    def test_a_ship_of_several_rooms_is_the_zone(self):
        ship = zones.register(self.root, "Ship")
        zones.set_kind(self.root, ship, "spacecraft.n.01")
        zones.assign(self.root, self.room2, ship)
        self.char1.move_to(self.room2, quiet=True)

        what, where = kinds.enclosure(self.char1, "spacecraft.n.01",
                                      world_root=self.root)
        self.assertEqual(what, kinds.ZONE)
        self.assertEqual(where, ship)

    def test_the_walk_goes_outward_through_parent_zones(self):
        """The plan's done-when: a bridge, in a ship, at a station."""
        station = zones.register(self.root, "Station")
        ship = zones.register(self.root, "Ship", parent=station)
        bridge = zones.register(self.root, "Bridge", parent=ship)
        zones.set_kind(self.root, station, "structure.n.01")
        zones.set_kind(self.root, ship, "spacecraft.n.01")
        zones.assign(self.root, self.room2, bridge)
        self.char1.move_to(self.room2, quiet=True)

        self.assertEqual(
            kinds.enclosure(self.char1, "spacecraft.n.01",
                            world_root=self.root),
            (kinds.ZONE, ship))
        self.assertEqual(
            kinds.enclosure(self.char1, "structure.n.01",
                            world_root=self.root),
            (kinds.ZONE, station))

    def test_the_nearest_enclosure_wins(self):
        """A pod inside a ship: the deeper zone answers first."""
        ship = zones.register(self.root, "Ship")
        pod = zones.register(self.root, "Pod", parent=ship)
        zones.set_kind(self.root, ship, "vehicle.n.01")
        zones.set_kind(self.root, pod, "spacecraft.n.01")
        zones.assign(self.root, self.room2, pod)
        self.char1.move_to(self.room2, quiet=True)

        what, where = kinds.enclosure(self.char1, "vehicle.n.01",
                                      world_root=self.root)
        self.assertEqual((what, where), (kinds.ZONE, pod),
                         "a spacecraft is a vehicle, and it is nearer")

    def test_nothing_of_that_sort_anywhere_answers_nothing(self):
        self.char1.move_to(self.room2, quiet=True)
        self.assertEqual(
            kinds.enclosure(self.char1, "spacecraft.n.01",
                            world_root=self.root),
            (None, None))

    def test_a_thing_nowhere_at_all_does_not_raise(self):
        self.assertEqual(kinds.enclosure(None, "spacecraft.n.01"),
                         (None, None))


@tag("world")
class APlaceInACondition(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room2.db.world_root = self.root

    def test_a_room_holds_a_state_like_anything_else(self):
        verbs.apply_states(self.room2, add=["depressurised"],
                           world_root=self.root)
        self.assertIn("depressurised", verbs.states(self.room2))

    def test_and_the_word_enters_the_world_vocabulary(self):
        """
        Which is the point of going through `register_state`: a place's
        condition gets a meaning, a group and a help entry for nothing.
        """
        verbs.apply_states(self.room2, add=["depressurised"],
                           world_root=self.root)
        self.assertIn("depressurised", verbs.vocabulary(self.root))

    def test_a_zone_holds_a_state(self):
        planet = zones.register(self.root, "Kepler Nine")
        zones.apply_states(self.root, planet, add=["port_closed"])
        self.assertEqual(zones.states(self.root, planet), {"port_closed"})
        self.assertIn("port_closed", verbs.vocabulary(self.root))

    def test_a_zone_state_can_be_taken_away_again(self):
        planet = zones.register(self.root, "Kepler Nine")
        zones.apply_states(self.root, planet, add=["port_closed"])
        zones.apply_states(self.root, planet, remove=["port_closed"])
        self.assertEqual(zones.states(self.root, planet), set())

    def test_an_exclusive_group_cancels_the_other_member_on_a_zone_too(self):
        """The same guarantee a bottle gets: one answer per question."""
        planet = zones.register(self.root, "Kepler Nine")
        verbs.register_state(self.root, "lit", group="light_level")
        verbs.register_state(self.root, "unlit", group="light_level")
        zones.apply_states(self.root, planet, add=["lit"])
        zones.apply_states(self.root, planet, add=["unlit"])
        self.assertEqual(zones.states(self.root, planet), {"unlit"})

    def test_an_unknown_zone_is_answered_and_not_raised(self):
        self.assertEqual(zones.states(self.root, "nowhere"), set())
        self.assertEqual(zones.apply_states(self.root, "nowhere",
                                            add=["lit"]), set())


@tag("world")
class WhatSortOfPlaceAZoneIs(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True

    def test_a_new_zone_has_no_kind_until_somebody_says(self):
        """
        Deriving one from the name was tried and removed. A zone's name is as
        often a proper noun as a common one -- "Kepler Nine", "The Wandering
        Albatross" -- and those ground as a number and a seabird. A wrong kind
        is worse than none: every rule filed against it would be about the
        wrong sort of thing.
        """
        albatross = zones.register(self.root, "The Wandering Albatross")
        self.assertEqual(zones.kind_of(self.root, albatross), "")

    def test_a_kind_may_be_settled_explicitly(self):
        ship = zones.register(self.root, "The Wandering Albatross")
        zones.set_kind(self.root, ship, "spacecraft.n.01")
        self.assertEqual(zones.kind_of(self.root, ship), "spacecraft.n.01")

    def test_the_first_answer_stands(self):
        """As for a kind, and for the same reason."""
        ship = zones.register(self.root, "Ship")
        zones.set_kind(self.root, ship, "spacecraft.n.01")
        zones.set_kind(self.root, ship, "publication.n.01")
        self.assertEqual(zones.kind_of(self.root, ship), "spacecraft.n.01")

    def test_an_unknown_zone_has_no_kind_and_does_not_raise(self):
        self.assertEqual(zones.kind_of(self.root, "nowhere"), "")


@tag("unit")
class WhenARoomTypeIsUseless(SimpleTestCase):
    """The plan's third test: degrade, never raise."""

    def test_a_room_with_no_type_gets_no_kind_rather_than_an_error(self):
        self.assertEqual(kinds.canonical(""), "")
        self.assertEqual(kinds.canonical(None), "")

    def test_a_planner_slug_still_yields_its_head_noun(self):
        for slug, expected in (("carousel_boutique_showroom", "showroom"),
                               ("spore_hollow", "hollow"),
                               ("south_orchard_fence_line", "line")):
            settled = kinds.canonical(slug)
            self.assertTrue(settled.startswith(expected), f"{slug} -> {settled}")

    def test_and_reading_kinds_off_something_that_has_none_is_empty(self):
        self.assertEqual(kinds.of(None), [])
        self.assertEqual(kinds.of(mock.Mock(db=mock.Mock(kinds=None))), [])
