"""
Effects that reach past this room: `set_exit`, and `move_object` elsewhere.

A launching ship needs both. Its airlock opened onto a landing pad a moment ago
and opens onto a dock now, and nothing in the vocabulary could say so -- exits
were built by `worldgen` and never touched again, and `move_object` reached the
actor, this room, or a role, but never another place.

Also here: the gap that turned up while looking for them. `relations.SHUT` has
named the shutting states since containers learned to close, and an exit in one
admitted everybody anyway -- so the `locked` state that 121 `lacks` clauses in
the corpus talk about had nothing behind it.

Every effect below is asserted readable by `conditions.achieves`, or asserted
not to be with the reason recorded. §11.1: an effect nobody can read backwards
is not a cheap effect, it is a hole in the planner.
"""

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from world import conditions as C
from world import coords, effects, verbs


@tag("world")
class TwoRooms(EvenniaTest):
    """A world of two rooms with a way between them."""

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room1.db.room_title = "Landing Pad"
        self.room2.db.world_root = self.root
        self.room2.db.room_title = "Orbital Dock"
        self.char1.move_to(self.room1, quiet=True)

        from evennia import create_object
        from typeclasses.exits import AIExit

        self.way = create_object(AIExit, key="airlock", location=self.room1,
                                 destination=self.room2)

        from typeclasses.rooms import Room

        self.third = create_object(Room, key="Engine Room")
        self.third.db.world_root = self.root
        self.third.db.room_title = "Engine Room"

    def apply(self, *given):
        return effects.apply(self.char1, self.char1.location, list(given),
                             bound={"direct": self.obj1},
                             world_root=self.root)


@tag("world")
class FindingARoomByName(TwoRooms):
    """
    A dbref means nothing to whoever writes a rule and is wrong the moment a
    world is rebuilt, so a name is the only thing an effect may use.
    """

    def test_a_room_is_found_by_its_title(self):
        self.assertIs(coords.room_named(self.root, "Orbital Dock"), self.room2)

    def test_case_and_space_do_not_matter(self):
        self.assertIs(coords.room_named(self.root, "  orbital dock "),
                      self.room2)

    def test_a_room_is_found_by_its_key_too(self):
        self.room2.db.room_title = ""
        self.assertIs(coords.room_named(self.root, self.room2.key), self.room2)

    def test_a_name_nothing_answers_to_is_no_room(self):
        self.assertIsNone(coords.room_named(self.root, "Cargo Hold"))

    def test_and_an_empty_name_is_not_a_lucky_guess(self):
        self.assertIsNone(coords.room_named(self.root, ""))
        self.assertIsNone(coords.room_named(self.root, None))

    def test_rooms_of_another_world_are_not_found(self):
        other = self.obj2
        other.db.room_title = "Orbital Dock"
        self.assertIs(coords.room_named(self.root, "Orbital Dock"), self.room2)


@tag("world")
class ChangingWhereAWayLeads(TwoRooms):

    def test_an_exit_can_be_retargeted(self):
        """The launching ship: its airlock opens somewhere else now."""
        self.assertIs(self.way.destination, self.room2)
        said = self.apply({"type": "set_exit", "exit": "airlock",
                           "to": "Engine Room"})
        self.assertIs(self.way.destination, self.third)
        self.assertTrue(said)

    def test_a_way_waiting_to_be_built_stops_waiting(self):
        """Generating a room behind it now would strand the one it points at."""
        self.way.db.pending_generation = True
        self.apply({"type": "set_exit", "exit": "airlock",
                    "to": "Engine Room"})
        self.assertFalse(self.way.db.pending_generation)

    def test_a_room_this_world_does_not_have_changes_nothing(self):
        self.apply({"type": "set_exit", "exit": "airlock", "to": "Cargo Hold"})
        self.assertIs(self.way.destination, self.room2)

    def test_an_exit_this_room_does_not_have_changes_nothing(self):
        self.assertEqual(
            self.apply({"type": "set_exit", "exit": "hatch",
                        "to": "Engine Room"}), [])

    def test_retargeting_it_where_it_already_goes_says_nothing(self):
        self.assertEqual(
            self.apply({"type": "set_exit", "exit": "airlock",
                        "to": "Orbital Dock"}), [])

    def test_an_exit_is_never_pointed_at_the_room_it_leaves_from(self):
        """A way from the landing pad to the landing pad is a way to nowhere."""
        self.assertEqual(
            self.apply({"type": "set_exit", "exit": "airlock",
                        "to": "Landing Pad"}), [])
        self.assertIs(self.way.destination, self.room2)


@tag("world")
class WhereAWayLeads(TwoRooms):
    """The condition that reads `set_exit` backwards."""

    def ctx(self):
        return C.context({"direct": self.obj1}, self.char1, self.root, "look")

    def test_a_way_that_leads_there_is_found(self):
        self.assertTrue(C.evaluate(
            {"subject": "here", "leads_to": "Orbital Dock"}, self.ctx()))

    def test_one_that_does_not_is_not(self):
        self.assertFalse(C.evaluate(
            {"subject": "here", "leads_to": "Engine Room"}, self.ctx()))

    def test_it_asks_about_one_step_and_not_about_the_whole_world(self):
        """
        A search would answer yes for somewhere twenty rooms away, which is not
        what a rule about an airlock means -- and one step is what the planner
        can act on. The engine room exists in this world and nothing here leads
        to it.
        """
        self.assertIsNotNone(coords.room_named(self.root, "Engine Room"))
        self.assertFalse(C.evaluate(
            {"subject": "here", "leads_to": "Engine Room"}, self.ctx()))

    def test_the_refusal_names_the_place(self):
        said = C.describe({"subject": "here", "leads_to": "Cargo Hold"},
                          self.ctx(), mood=C.UNMET)
        self.assertIn("Cargo Hold", said)

    def test_and_it_reads_as_a_want_too(self):
        said = C.describe({"subject": "here", "leads_to": "Cargo Hold"},
                          self.ctx(), mood=C.WANT)
        self.assertIn("Cargo Hold", said)


@tag("unit")
class ReadingTheNewEffectsBackwards(SimpleTestCase):
    """§11.1, asserted per effect."""

    def test_set_exit_achieves_a_way_leading_there(self):
        self.assertTrue(C.achieves(
            {"type": "set_exit", "exit": "airlock", "to": "Orbital Dock"},
            {"subject": "here", "leads_to": "Orbital Dock"}))

    def test_but_not_a_way_leading_somewhere_else(self):
        self.assertFalse(C.achieves(
            {"type": "set_exit", "exit": "airlock", "to": "Landing Pad"},
            {"subject": "here", "leads_to": "Orbital Dock"}))

    def test_move_actor_is_read_optimistically_and_set_exit_exactly(self):
        """
        The contrast worth knowing. `move_actor` names an exit, so whether it
        reaches the dock is a fact about the world rather than about the effect,
        and `achieves` answers "that would help" and lets the step be checked
        when it is taken. `set_exit` names its room, so it can be read exactly
        -- and is, which is why the wrong room above answers no.
        """
        self.assertTrue(C.achieves(
            {"type": "move_actor", "exit": "north"},
            {"subject": "actor", "in_room": "Orbital Dock"}))
        self.assertTrue(C.achieves(
            {"type": "move_actor", "exit": "south"},
            {"subject": "actor", "in_room": "Orbital Dock"}),
            "it cannot tell the two doors apart, and does not pretend to")


@tag("world")
class SendingAThingSomewhereElse(TwoRooms):

    def setUp(self):
        super().setUp()
        self.obj1.key = "Crate"
        self.obj1.move_to(self.room1, quiet=True)

    def test_a_thing_can_be_sent_to_another_room(self):
        self.apply({"type": "move_object", "name_role": "direct",
                    "to": "Orbital Dock"})
        self.assertIs(self.obj1.location, self.room2)

    def test_a_room_this_world_does_not_have_changes_nothing(self):
        self.apply({"type": "move_object", "name_role": "direct",
                    "to": "Cargo Hold"})
        self.assertIs(self.obj1.location, self.room1)

    def test_the_old_meanings_still_work(self):
        self.apply({"type": "move_object", "name_role": "direct",
                    "to": "actor"})
        self.assertIs(self.obj1.location, self.char1)
        self.apply({"type": "move_object", "name_role": "direct",
                    "to": "room"})
        self.assertIs(self.obj1.location, self.room1)


@tag("world")
class AShutWayStopsYou(TwoRooms):
    """
    `relations.SHUT` has named these states since containers learned to close,
    and an exit in one admitted everybody anyway.
    """

    def walk(self):
        said = []
        self.char1.msg = lambda text="", **kwargs: said.append(str(text))
        self.way.at_traverse(self.char1, self.way.destination)
        return " ".join(said)

    def test_an_open_way_lets_you_through(self):
        self.walk()
        self.assertIs(self.char1.location, self.room2)

    def test_a_locked_one_does_not(self):
        verbs.apply_states(self.way, add=["locked"], world_root=self.root)
        said = self.walk()
        self.assertIs(self.char1.location, self.room1)
        self.assertIn("locked", said.lower())

    def test_every_shutting_word_counts(self):
        for state in sorted(effects_shut_states()):
            self.char1.move_to(self.room1, quiet=True)
            verbs.apply_states(self.way, add=[state], world_root=self.root)
            self.walk()
            self.assertIs(self.char1.location, self.room1, state)
            verbs.apply_states(self.way, remove=[state], world_root=self.root)

    def test_and_unlocking_it_opens_the_way_again(self):
        verbs.apply_states(self.way, add=["locked"], world_root=self.root)
        self.walk()
        self.assertIs(self.char1.location, self.room1)
        verbs.apply_states(self.way, remove=["locked"], world_root=self.root)
        self.walk()
        self.assertIs(self.char1.location, self.room2)

    def test_so_locking_a_door_is_a_rule_anybody_could_write(self):
        """No new effect and no new condition: `set_state` and `is`, as ever."""
        self.apply({"type": "set_state", "name": "airlock", "add": ["locked"]})
        self.assertIn("locked", verbs.states(self.way))
        self.assertTrue(C.achieves(
            {"type": "set_state", "role": "direct", "add": ["locked"]},
            {"subject": "direct", "is": ["locked"]}))


def effects_shut_states():
    from world import relations

    return relations.SHUT
