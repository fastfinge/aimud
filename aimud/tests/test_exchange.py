"""
Worlds that travel: reading one out, refusing a bad one, and building one.

The round trip is the test that matters and it is two halves. `RoundTrip`
exports a world, imports the document, exports the result, and asserts the two
documents are the same text -- which catches anything the *writer* drops.
`SameWorld` compares the two worlds instead, which catches anything the
*reader* never wrote down in the first place: a field no section carries is
missing from both documents and a document-only test would call that a pass.

`AttributesAreAccountedFor` is the third kind, and the one that matters over
time. It walks every attribute this codebase writes and fails when one is in
neither `exchange.CARRIED` nor `exchange.LEFT`, so adding an attribute is a
decision about whether a world carries it rather than a silence found months
later by somebody whose imported world came back missing something.

See docs/archived/import-and-export.md 13.
"""

import ast
import json
import os
import pathlib
import tempfile

from django.test import override_settings

from tests.base import GameTest, NoWorldTest


HERE = pathlib.Path(__file__).resolve().parent
GAME_DIR = HERE.parent


class WorldTest(GameTest):
    """A hand-built world to export, built without a single model call."""

    def world(self, title="The School", rulesets=("default",)):
        from world import worldgen
        from world.sponsor import Sponsor

        made = {}
        worldgen.first_room_by_hand(
            Sponsor(actor=self.char1),
            {"title": title, "description": "A haunted school.",
             "rulesets": list(rulesets)},
            lambda room: made.setdefault("root", room),
            lambda err: made.setdefault("err", err))
        self.assertIsNotNone(made.get("root"), made.get("err"))
        return made["root"]

    def furnish(self, root):
        """
        One of everything a document has a section for.

        Written out rather than generated, because the point of the round trip
        is that every section is populated: a test world with no errands in it
        proves nothing about errands.
        """
        from evennia import create_object
        from typeclasses.exits import AIExit
        from world import (clothing, kinds, ownership, pronouns, quests,
                           relations, rulebooks, token_lists, traits, verbs,
                           worldgen)

        root.db.desc = "A tall door and a smell of {smell}."
        token_lists.register_many(root, [{
            "name": "smell", "means": "what a place smells of",
            "entries": ["chalk", "floor polish"], "scope": "room"}])
        gym = worldgen._create_room(
            "The Gym", "A high hall.", [], "A haunted school.",
            root, "north", world_root=root, room_type="gymnasium",
            category="destination", zone="gym block")
        worldgen._make_exit(AIExit, "north", root, gym, pending=False)
        worldgen._make_ai_exit(gym, root,
                               {"name": "east",
                                "destination_hint": "changing rooms"})
        verbs.register_state(root, "scorched", means="burnt on the outside")
        traits.register(root, "dread", name="Dread", means="how frightened")
        kinds.remember(root, "lamp", {"get": True})
        kinds.remember(root, "table", {"get": False}, accepts=["on"])

        table = clothing.create(
            {"name": "an oak table", "description": "Scarred.",
             "kind": "table", "takeable": False}, location=gym)
        lamp = clothing.create(
            {"name": "a brass lamp", "description": "Dented.",
             "kind": "lamp", "states": ["scorched"], "takeable": True},
            location=gym)
        relations.place(lamp, table, "on")

        pronouns.register(root, {
            "subject": "ze", "object": "hir", "possessive": "hir",
            "possessive_pronoun": "hirs", "reflexive": "hirself",
            "means": "for somebody who goes by ze"})
        npc = create_object("typeclasses.npcs.NPC", key="Mrs Hallow",
                            location=gym)
        npc.db.is_npc = True
        npc.db.world_root = root
        npc.db.desc = "Grey and unhurried."
        npc.db.manner = "Never raises her voice."
        npc.db.pronoun_set = "ze"
        kinds.ensure_person(npc)
        traits.ensure(npc, "dread", world_root=root)
        traits.adjust(npc, "dread", set_to=4, world_root=root, announce=False)
        coat = clothing.create(
            {"name": "a grey coat", "description": "Long.", "kind": "coat",
             "clothing_type": "outerwear"}, location=npc, worn_on=npc)
        self.assertIsNotNone(coat)
        ownership.set_owner(lamp, npc, cascade=False)

        quests.save_spec(root, {
            "title": "Find the lamp", "description": "It is in the gym.",
            "givers": [{"npc": npc.id, "description": "Have you seen it?"}]})
        rulebooks.add(root, {
            "name": "the lamp is warm", "phase": "check", "action": "rub",
            "scope": {"object": lamp.id}, "conditions": [], "effects": []})
        rulebooks.add(root, {
            "name": "the gym is cold", "phase": "check", "action": "wait",
            "scope": {"room": gym.id}, "conditions": [], "effects": []})
        # What it has already worked out, both halves: the counts, and the
        # cache from before the rulebooks that `verb_gen` still writes.
        root.db.attempt_counts = {"rub": {"worked": 2}}
        root.db.verb_rules = {"rub:lamp.n.01": {"needs": [], "does": []}}
        # And a decision about a rule the world did not write: one of the
        # default ruleset's, suspended.
        suspended = next(rule for rule in rulebooks.all_rules(root)
                         if rule.get("source") == "standard")
        rulebooks.set_listed(root, suspended["id"], False)
        return {"gym": gym, "npc": npc, "lamp": lamp, "table": table,
                "coat": coat, "suspended": suspended["name"]}

    def built(self, root):
        """`root` exported and built again, as (document, new root)."""
        from world import exchange

        doc = exchange.document(root)
        self.assertEqual(exchange.problems(doc), [])
        return doc, exchange.build(doc, None, self.char1)


class RoundTrip(WorldTest):
    """Export, import, export: the two documents are the same text."""

    def test_a_furnished_world_survives_the_trip(self):
        from world import exchange

        root = self.world()
        self.furnish(root)
        first, new_root = self.built(root)
        second = exchange.document(new_root)
        for doc in (first, second):
            doc.pop("exported", None)
        self.assertEqual(json.dumps(first, indent=1, sort_keys=True),
                         json.dumps(second, indent=1, sort_keys=True))

    def test_a_bare_world_survives_the_trip(self):
        from world import exchange

        root = self.world()
        first, new_root = self.built(root)
        second = exchange.document(new_root)
        for doc in (first, second):
            doc.pop("exported", None)
        self.assertEqual(first, second)

    #: Every field in a document that names something else in it. A number
    #: here would be a dbref, which means nothing on another server or --
    #: worse -- means some other object on it.
    REFERENCES = ("id", "at", "to", "from", "npc", "of", "following",
                  "object", "room", "zone", "rooms")

    def test_every_reference_names_something_rather_than_numbering_it(self):
        from world import exchange

        root = self.world()
        self.furnish(root)
        doc = exchange.document(root)
        numbered = []

        def walk(node, where):
            if isinstance(node, dict):
                for key, value in node.items():
                    # A condition tree speaks its own language, in which
                    # `from` and `to` are hours of the clock. Nothing in one
                    # names an object -- a rule reaches a particular thing
                    # through its scope, which is walked.
                    if key in ("when", "conditions", "effects"):
                        continue
                    if key in self.REFERENCES and not isinstance(value, (dict,
                                                                         list)):
                        if not isinstance(value, str):
                            numbered.append((f"{where}.{key}", value))
                        continue
                    walk(value, f"{where}.{key}")
            elif isinstance(node, list):
                for position, value in enumerate(node):
                    walk(value, f"{where}[{position}]")

        # `map.rooms[].at` is a coordinate and the one list of numbers that
        # is not a reference, so the map's rooms are walked without it.
        for section in ("map", "things", "people", "errands", "vocabulary"):
            walk(doc[section], section)
        self.assertEqual([spot for spot, _value in numbered
                          if not spot.endswith("rooms.at")], [])

    def test_the_two_worlds_have_different_dbrefs(self):
        """
        The round trip is worth nothing unless the second world is a new one.

        A document that happened to describe the same rows would round-trip
        whatever it carried, so this is the assumption the equality assertion
        above rests on, checked rather than assumed.
        """
        from world import exchange

        root = self.world()
        self.furnish(root)
        _doc, new = self.built(root)
        self.assertNotEqual(root.id, new.id)
        self.assertEqual(
            {room.id for room in exchange.rooms_of(root)}
            & {room.id for room in exchange.rooms_of(new)}, set())


class SameWorld(WorldTest):
    """The world that comes back is the world that went in."""

    def test_the_map_is_the_same_map(self):
        from world import coords, exchange

        root = self.world()
        self.furnish(root)
        _doc, new = self.built(root)

        was = {room.db.room_title: coords.get_coord(room)
               for room in exchange.rooms_of(root)}
        now = {room.db.room_title: coords.get_coord(room)
               for room in exchange.rooms_of(new)}
        self.assertEqual(was, now)

    def test_the_ways_lead_the_same_places(self):
        from world import exchange

        root = self.world()
        self.furnish(root)
        _doc, new = self.built(root)

        def ways(world):
            found = set()
            for room in exchange.rooms_of(world):
                for obj in room.contents:
                    if getattr(obj, "destination", None) is None:
                        continue
                    there = (obj.destination.db.room_title
                             if obj.destination else None)
                    found.add((room.db.room_title, obj.key, there,
                               bool(obj.db.pending_generation)))
            return found

        self.assertEqual(ways(root), ways(new))

    def test_the_same_things_are_in_the_same_places(self):
        from world import exchange, relations

        root = self.world()
        self.furnish(root)
        _doc, new = self.built(root)

        def contents(world):
            _people, things = exchange.contents_of(world)
            return {(obj.key, holder.key, relations.preposition_of(obj)
                     if relations.host_of(obj) is not None else "")
                    for obj, holder in things}

        self.assertEqual(contents(root), contents(new))

    def test_the_registers_come_back(self):
        from world import actions, kinds, rulebooks, traits, verbs

        root = self.world()
        self.furnish(root)
        _doc, new = self.built(root)

        self.assertEqual(kinds.vocabulary(root), kinds.vocabulary(new))
        self.assertEqual(sorted(traits.vocabulary(root)),
                         sorted(traits.vocabulary(new)))
        self.assertEqual(verbs.vocabulary(root), verbs.vocabulary(new))
        self.assertEqual(actions.vocabulary(root), actions.vocabulary(new))
        self.assertEqual(
            sorted(rule["name"] for rule in rulebooks.all_rules(root)),
            sorted(rule["name"] for rule in rulebooks.all_rules(new)))

    def test_a_rule_about_one_thing_is_about_that_thing_again(self):
        from world import exchange, rulebooks

        root = self.world()
        self.furnish(root)
        _doc, new = self.built(root)

        _people, things = exchange.contents_of(new)
        lamp = next(obj for obj, _where in things if obj.key == "a brass lamp")
        scoped = [rule for rule in rulebooks.all_rules(new)
                  if rule["name"] == "the lamp is warm"]
        self.assertEqual(len(scoped), 1)
        self.assertEqual(scoped[0]["scope"], {"object": lamp.id})

    def test_an_errand_is_given_by_the_same_person(self):
        from world import exchange, quests

        root = self.world()
        self.furnish(root)
        _doc, new = self.built(root)

        people, _things = exchange.contents_of(new)
        hallow = next(obj for obj, _where in people if obj.key == "Mrs Hallow")
        specs = list(quests.specs(new).values())
        self.assertEqual(len(specs), 1)
        self.assertEqual([giver["npc"] for giver in specs[0]["givers"]],
                         [hallow.id])

    def test_what_the_world_had_worked_out_comes_with_it(self):
        root = self.world()
        self.furnish(root)
        _doc, new = self.built(root)
        self.assertEqual(dict(new.db.attempt_counts or {}),
                         {"rub": {"worked": 2}})
        # The cache from before the rulebooks is still written and is still
        # worth what it cost.
        self.assertIn("rub:lamp.n.01", dict(new.db.verb_rules or {}))

    def test_a_suspended_rule_is_still_suspended(self):
        """
        A world's decision about a ruleset's rule outlives the journey.

        The rule itself comes back with the ruleset -- it is not in the
        document -- so what has to travel is the decision, and nothing else
        would have put it back.
        """
        from world import rulebooks

        root = self.world()
        made = self.furnish(root)
        _doc, new = self.built(root)

        there = [rule for rule in rulebooks.all_rules(new)
                 if rule["name"] == made["suspended"]]
        self.assertEqual(len(there), 1)
        self.assertFalse(there[0]["listed"])

    def test_a_character_wants_what_they_wanted(self):
        from world import exchange, goals

        root = self.world()
        made = self.furnish(root)
        made["npc"].db.goal = goals.sanitise(
            [{"type": "holds", "what": "a brass lamp"}], owner=made["npc"])
        self.assertTrue(made["npc"].db.goal)
        _doc, new = self.built(root)

        people, _things = exchange.contents_of(new)
        hallow = next(obj for obj, _w in people if obj.key == "Mrs Hallow")
        self.assertEqual(list(hallow.db.goal or []),
                         list(made["npc"].db.goal or []))

    def test_a_thing_a_player_owned_comes_back_as_nobodys(self):
        """
        Owned by somebody who is gone -- a shape `ownership` already had.

        A player character is not part of a world, so their name survives the
        journey and their dbref does not. `claimable` reads the result as
        free, which is the right answer: there is nobody here to ask.
        """
        from world import exchange, ownership

        root = self.world()
        made = self.furnish(root)
        ownership.set_owner(made["table"], self.char1, cascade=False)
        _doc, new = self.built(root)

        _people, things = exchange.contents_of(new)
        table = next(obj for obj, _w in things if obj.key == "an oak table")
        self.assertEqual(ownership.owner_name(table), self.char1.key)
        self.assertIsNone(ownership.owner_of(table))
        self.assertTrue(ownership.claimable(table))

    def test_a_thing_an_npc_owned_is_still_theirs(self):
        from world import exchange, ownership

        root = self.world()
        self.furnish(root)
        _doc, new = self.built(root)

        people, things = exchange.contents_of(new)
        hallow = next(obj for obj, _w in people if obj.key == "Mrs Hallow")
        lamp = next(obj for obj, _w in things if obj.key == "a brass lamp")
        self.assertEqual(ownership.owner_of(lamp), hallow)

    def test_the_zones_hold_the_same_rooms(self):
        from world import exchange, zones

        root = self.world()
        self.furnish(root)
        _doc, new = self.built(root)

        def held(world):
            names = {room.id: room.db.room_title
                     for room in exchange.rooms_of(world)}
            return {zone: sorted(names.get(dbref, "?")
                                 for dbref in (record.get("rooms") or []))
                    for zone, record in (world.db.zones or {}).items()}

        self.assertEqual(held(root), held(new))

    def test_the_importer_owns_it_and_nobody_else_does(self):
        from world import exchange

        root = self.world()
        self.furnish(root)
        doc = exchange.document(root)
        # Nothing in the document names an account at all.
        self.assertNotIn("world_creator", json.dumps(doc))

    def test_a_player_is_not_part_of_a_world(self):
        """What somebody was carrying is; the somebody is not."""
        from world import clothing, exchange

        root = self.world()
        made = self.furnish(root)
        self.char1.move_to(made["gym"], quiet=True)
        crowbar = clothing.create(
            {"name": "a crowbar", "description": "Cold.", "kind": "lamp"},
            location=self.char1)
        self.assertIsNotNone(crowbar)

        doc = exchange.document(root)
        self.assertNotIn(self.char1.key,
                         [person["name"] for person in doc["people"]])
        carried = next(thing for thing in doc["things"]
                       if thing["name"] == "a crowbar")
        # On the floor of the room they were standing in, not in their hands.
        self.assertEqual(carried["at"],
                         next(room["id"] for room in doc["map"]["rooms"]
                              if room["title"] == "The Gym"))


class Refusals(WorldTest):
    """
    A document that fails builds nothing at all.

    Every test here asserts the object count is unchanged as well as the
    complaint, because "refused" and "refused after making eleven rooms" are
    very different things and only one of them is what `problems` promises.
    """

    def setUp(self):
        super().setUp()
        root = self.world()
        self.furnish(root)
        from world import exchange

        self.doc = exchange.document(root)

    def _refused(self, doc, saying):
        from evennia.objects.models import ObjectDB
        from world import exchange

        before = ObjectDB.objects.count()
        wrong = exchange.problems(doc)
        self.assertTrue(wrong, "the document was not refused")
        self.assertTrue(
            any(saying in complaint for complaint in wrong),
            f"none of {wrong} says {saying!r}")
        with self.assertRaises(exchange.Refused):
            exchange.build(doc, None, self.char1)
        self.assertEqual(ObjectDB.objects.count(), before,
                         "a refused document built something")

    def test_a_document_from_a_later_aimud(self):
        self.doc["aimud"] = 99
        self._refused(self.doc, "this server reads")

    def test_something_that_is_not_a_world(self):
        self.doc["kind"] = "character"
        self._refused(self.doc, "it is not a world")

    def test_a_section_nobody_reads(self):
        self.doc["weather"] = []
        self._refused(self.doc, "a section nobody reads")

    def _a_way(self):
        """One that leads somewhere, rather than whichever is written first."""
        return next(way for way in self.doc["map"]["ways"]
                    if not way.get("pending"))

    def test_a_way_onto_a_room_that_is_not_here(self):
        self._a_way()["to"] = "the_boiler_room"
        self._refused(self.doc, "the_boiler_room")

    def test_a_way_that_goes_nowhere(self):
        self._a_way().pop("to")
        self._refused(self.doc, "goes nowhere")

    def test_a_way_that_is_pending_and_also_goes_somewhere(self):
        pending = next(way for way in self.doc["map"]["ways"]
                       if way.get("pending"))
        pending["to"] = self.doc["map"]["rooms"][0]["id"]
        self._refused(self.doc, "one or the other")

    def test_two_rooms_in_one_cell(self):
        self.doc["map"]["rooms"][1]["at"] = self.doc["map"]["rooms"][0]["at"]
        self._refused(self.doc, "both at")

    def test_a_document_with_no_rooms_in_it(self):
        self.doc["map"]["rooms"] = []
        self.doc["map"]["ways"] = []
        self.doc["things"] = []
        self.doc["people"] = []
        self._refused(self.doc, "there is no world in it")

    def test_a_thing_that_is_nowhere(self):
        self.doc["things"][0]["at"] = ""
        self._refused(self.doc, "is nowhere")

    def test_an_errand_from_nobody(self):
        self.doc["errands"][0]["givers"][0]["npc"] = "the_caretaker"
        self._refused(self.doc, "the_caretaker")

    def test_a_rule_about_something_that_is_not_here(self):
        rules = self.doc["vocabulary"]["rules"]
        rules[0]["scope"] = {"object": "a_thing_that_never_was"}
        self._refused(self.doc, "a_thing_that_never_was")

    def test_a_rule_with_no_phase_this_game_runs(self):
        self.doc["vocabulary"]["rules"][0]["phase"] = "whenever"
        self._refused(self.doc, "phase")

    def test_a_ruleset_this_server_has_not_got(self):
        self.doc["requires"]["rulesets"]["moons"] = 1
        self._refused(self.doc, "does not have")

    def test_a_ruleset_newer_than_this_server_has(self):
        self.doc["requires"]["rulesets"]["default"] = 99
        self._refused(self.doc, "version 99")

    def test_a_plugin_this_server_could_not_have(self):
        self.doc["requires"]["plugins"] = ["weather"]
        self._refused(self.doc, "no plugins at all")

    def test_more_rooms_than_this_server_will_build(self):
        from world import exchange

        one = self.doc["map"]["rooms"][0]
        self.doc["map"]["rooms"] = [one] * (exchange.MOST_ROOMS + 1)
        self._refused(self.doc, "as many as this server will build")

    def test_a_description_longer_than_a_description(self):
        from world import exchange

        self.doc["map"]["rooms"][0]["description"] = (
            "x" * (exchange.LONGEST_TEXT + 1))
        self._refused(self.doc, "the most one may be")

    def test_a_build_that_fails_late_takes_its_world_with_it(self):
        """
        Nobody is left owning half a world.

        `problems` has judged the document by the time building starts, so
        this is the fault-in-the-building case rather than the
        fault-in-the-document one -- and the failure that must not happen
        quietly is somebody holding a world with no first room.
        """
        from unittest import mock

        from evennia.objects.models import ObjectDB
        from world import exchange

        before = ObjectDB.objects.count()
        with mock.patch.object(exchange, "_build_people",
                               side_effect=RuntimeError("no")):
            with self.assertRaises(exchange.Refused) as caught:
                exchange.build(self.doc, None, self.char1)
        self.assertIn("it could not be built", str(caught.exception))
        self.assertEqual(ObjectDB.objects.count(), before)

    def test_something_that_is_not_a_document_at_all(self):
        from world import exchange

        self.assertEqual(exchange.problems("a world"),
                         ["that is not a world document"])
        self.assertEqual(exchange.problems(None),
                         ["that is not a world document"])


class TheRestorePoint(WorldTest):
    """`reset world` goes back to the import rather than generating again."""

    def test_importing_sets_it(self):
        from world import exchange

        root = self.world()
        self.furnish(root)
        doc, new = self.built(root)
        stored = exchange.restore_point(new)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["title"], doc["title"])

    def test_a_document_never_carries_a_document(self):
        """
        A world's restore point is not part of the world.

        If it were, exporting a world that had been imported would write a
        copy of the last document inside this one, and the one after that
        would carry both. The document is built from named fields for exactly
        this reason: nothing here sweeps up whatever a root happens to hold.
        """
        from world import exchange

        root = self.world()
        self.furnish(root)
        _doc, new = self.built(root)
        self.assertIsNotNone(exchange.restore_point(new))
        self.assertNotIn(exchange.RESTORE_ATTR,
                         json.dumps(exchange.document(new)))

    def test_a_world_that_was_never_imported_has_none(self):
        from world import exchange

        self.assertIsNone(exchange.restore_point(self.world()))

    def test_a_reset_puts_back_what_was_imported(self):
        from world import exchange

        root = self.world()
        self.furnish(root)
        _doc, new = self.built(root)
        # Somebody plays: a room is renamed and a thing is destroyed.
        _people, things = exchange.contents_of(new)
        lamp = next(obj for obj, _where in things if obj.key == "a brass lamp")
        lamp.delete()
        exchange.rooms_of(new)[1].db.room_title = "The Ruined Gym"

        put_back = exchange.build(exchange.restore_point(new), None,
                                  self.char1)
        _people, things = exchange.contents_of(put_back)
        self.assertIn("a brass lamp", [obj.key for obj, _w in things])
        self.assertIn("The Gym",
                      [room.db.room_title for room in exchange.rooms_of(put_back)])

    def test_forgetting_it_means_generating_again(self):
        from world import exchange

        root = self.world()
        _doc, new = self.built(root)
        exchange.forget_restore(new)
        self.assertIsNone(exchange.restore_point(new))


class TheSharedFolder(WorldTest):
    """Reading and writing the folder, and the one rule about filenames."""

    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp(prefix="aimud-worlds-")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.folder, ignore_errors=True)
        super().tearDown()

    def test_a_world_is_written_and_read_back(self):
        from world import exchange

        root = self.world()
        self.furnish(root)
        doc = exchange.document(root)
        with override_settings(WORLD_DIRS=[self.folder]):
            name = exchange.write(doc)
            self.assertEqual(name, "the_school")
            self.assertEqual(exchange.read(name)["title"], "The School")
            listed = exchange.available()
        self.assertEqual(listed[name]["rooms"], doc["rooms"])
        self.assertEqual(listed[name]["missing"], [])

    def test_two_worlds_of_one_name_are_two_files(self):
        from world import exchange

        doc = exchange.document(self.world())
        with override_settings(WORLD_DIRS=[self.folder]):
            self.assertEqual(exchange.write(doc), "the_school")
            self.assertEqual(exchange.write(doc), "the_school_2")

    def test_a_name_never_becomes_a_path(self):
        """
        The whole of the path-traversal defence, asserted.

        A title is slugged before it is joined to a directory, so nothing a
        player can type reaches outside the folder -- and nothing they type
        becomes a filename at all: they name a world.
        """
        from world import exchange

        doc = dict(exchange.document(self.world()),
                   title="../../etc/passwd")
        with override_settings(WORLD_DIRS=[self.folder]):
            name = exchange.write(doc)
            self.assertEqual(name, "etc_passwd")
            self.assertEqual(sorted(os.listdir(self.folder)),
                             ["etc_passwd.json"])
            # Asked for by the same string, it is the same slug: the file in
            # the folder, and never a file outside it.
            self.assertEqual(exchange.read("../../etc/passwd")["title"],
                             "../../etc/passwd")
            with self.assertRaises(exchange.Refused):
                exchange.read("../../etc/shadow")

    def test_a_file_that_is_not_a_world_is_not_listed(self):
        from world import exchange

        pathlib.Path(self.folder, "notes.json").write_text(
            '{"kind": "shopping list"}', encoding="utf-8")
        pathlib.Path(self.folder, "broken.json").write_text(
            "{not json", encoding="utf-8")
        with override_settings(WORLD_DIRS=[self.folder]):
            self.assertEqual(exchange.available(), {})

    def test_a_file_too_big_to_read_is_refused_before_it_is_read(self):
        from world import exchange

        big = pathlib.Path(self.folder, "huge.json")
        big.write_text("x" * (exchange.MOST_BYTES + 1), encoding="utf-8")
        with override_settings(WORLD_DIRS=[self.folder]):
            with self.assertRaises(exchange.Refused) as caught:
                exchange.read("huge")
            self.assertIn("the most a world may be", str(caught.exception))

    def test_removing_one(self):
        from world import exchange

        doc = exchange.document(self.world())
        with override_settings(WORLD_DIRS=[self.folder]):
            name = exchange.write(doc)
            self.assertTrue(exchange.remove(name))
            self.assertFalse(exchange.remove(name))

    def test_a_server_with_nowhere_to_put_them(self):
        from world import exchange

        with override_settings(WORLD_DIRS=[]):
            with self.assertRaises(exchange.Refused):
                exchange.write(exchange.document(self.world()))


class TheCommands(WorldTest):
    """export world, import world, view exports, delete export."""

    accounts = True

    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp(prefix="aimud-worlds-")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.folder, ignore_errors=True)
        super().tearDown()

    def _mine(self, root):
        """Make the world the account's, as the wizard would have."""
        from world import sponsor

        sponsor.claim(root, self.account)
        made = list(self.account.db.created_worlds or [])
        made.append(root.id)
        self.account.db.created_worlds = made

    def test_export_then_import_through_the_commands(self):
        from commands import exchange_subject, world_subject

        root = self.world()
        self.furnish(root)
        self._mine(root)
        with override_settings(WORLD_DIRS=[self.folder]):
            said = world_subject._export(self.char1, root)
            self.assertIn("is in the shared folder", said)
            self.assertIn("the_school", exchange_subject.exports())
            said = world_subject._import(self.char1, "the_school")
            self.assertIn("is yours", said)
        self.assertEqual(len(self.account.db.created_worlds), 2)

    def test_a_world_is_imported_by_its_title_too(self):
        """Nobody types `the_school` having read "The School" in the listing."""
        from commands import world_subject

        root = self.world()
        self._mine(root)
        with override_settings(WORLD_DIRS=[self.folder]):
            world_subject._export(self.char1, root)
            cmd = type("Cmd", (), {"caller": self.char1, "session": None})()
            world_subject.import_run(cmd, None, ["The", "School", "yes"])
        self.assertEqual(len(self.account.db.created_worlds), 2)

    def test_only_whoever_made_a_world_may_export_it(self):
        from commands import world_subject

        root = self.world()
        with override_settings(WORLD_DIRS=[self.folder]):
            self.assertIn("Only whoever made a world",
                          world_subject._export(self.char1, root))

    def test_exporting_sets_the_restore_point(self):
        from commands import world_subject
        from world import exchange

        root = self.world()
        self._mine(root)
        with override_settings(WORLD_DIRS=[self.folder]):
            world_subject._export(self.char1, root)
        self.assertIsNotNone(exchange.restore_point(root))

    def test_the_reset_question_says_which_reset_this_is(self):
        from commands import world_subject
        from world import exchange

        root = self.world()
        self._mine(root)
        self.assertIn("generate the world again",
                      world_subject._reset_question(root, 1))
        exchange.remember(root, exchange.document(root))
        self.assertIn("back as it was",
                      world_subject._reset_question(root, 1))

    def test_importing_something_that_is_not_there(self):
        from commands import world_subject

        with override_settings(WORLD_DIRS=[self.folder]):
            cmd = type("Cmd", (), {"caller": self.char1, "session": None})()
            world_subject.import_run(cmd, None, ["nowhere"])

    def test_only_whoever_wrote_an_export_may_remove_it(self):
        from commands import exchange_subject, world_subject

        root = self.world()
        self._mine(root)
        with override_settings(WORLD_DIRS=[self.folder]):
            world_subject._export(self.char1, root)
            # Not as a builder: a builder may remove any of them, which is the
            # branch this test is not about.
            for permission in list(self.account.permissions.all()):
                self.account.permissions.remove(permission)
            self.account.db.exported_worlds = []
            said = exchange_subject.remove(self.char1, "the_school")
            self.assertIn("was not put there by you", said)
            self.account.db.exported_worlds = ["the_school"]
            self.assertIn("no longer in the shared folder",
                          exchange_subject.remove(self.char1, "the_school"))

    def test_a_builder_may_remove_any_of_them(self):
        from commands import exchange_subject, world_subject

        root = self.world()
        self._mine(root)
        with override_settings(WORLD_DIRS=[self.folder]):
            world_subject._export(self.char1, root)
            self.account.db.exported_worlds = []
            self.assertIn("no longer in the shared folder",
                          exchange_subject.remove(self.char1, "the_school"))


class AttributesAreAccountedFor(NoWorldTest):
    """
    Every attribute this codebase writes is either carried or named as left.

    Export is complete on the day it is written and quietly incomplete
    forever after unless something says so. This is that something: an AST
    pass over the game's own modules collecting every `obj.db.<name> = ` and
    every `attributes.add("<name>")`, checked against `exchange.CARRIED` and
    `exchange.LEFT`.

    The same arrangement `effects.VOCABULARY` has with `_apply_one`, where
    adding an effect without an entry is caught by a test rather than found in
    a world where it does nothing.
    """

    #: The directories a world's attributes could be written from.
    WHERE = ("world", "typeclasses", "commands")

    #: Modules whose attributes are never a world's. `exchange` itself writes
    #: the restore point; the test fixtures write whatever they please.
    SKIP = ("world/exchange.py",)

    def attributes(self):
        """{name: [where it is written]} for the whole game."""
        found = {}

        def note(name, where):
            found.setdefault(str(name), []).append(where)

        for directory in self.WHERE:
            for path in sorted((GAME_DIR / directory).rglob("*.py")):
                relative = path.relative_to(GAME_DIR).as_posix()
                if relative in self.SKIP:
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    where = f"{relative}:{getattr(node, 'lineno', 0)}"
                    # obj.db.name = ... and obj.ndb is not a world's business.
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if (isinstance(target, ast.Attribute)
                                    and isinstance(target.value, ast.Attribute)
                                    and target.value.attr == "db"):
                                note(target.attr, where)
                    # setattr(obj.db, ATTR, ...) and attributes.add("name", ...)
                    elif isinstance(node, ast.Call):
                        name = _literal_attribute(node)
                        if name:
                            note(name, f"{relative}:{node.lineno}")
        return found

    def test_nothing_is_written_that_nobody_has_decided_about(self):
        from world import exchange

        known = set(exchange.CARRIED) | set(exchange.LEFT)
        unaccounted = {name: where
                       for name, where in self.attributes().items()
                       if name not in known}
        self.assertEqual(
            unaccounted, {},
            "these attributes are written and the world document neither "
            "carries them nor says they are left behind -- add each to "
            "world/exchange.py CARRIED or LEFT, with the reason")

    def test_nothing_is_both_carried_and_left(self):
        from world import exchange

        both = sorted(set(exchange.CARRIED) & set(exchange.LEFT))
        self.assertEqual(both, [])

    def test_every_reason_is_a_reason(self):
        from world import exchange

        for name, why in list(exchange.CARRIED.items()) + \
                list(exchange.LEFT.items()):
            self.assertTrue(str(why).strip(),
                            f"{name} says nothing about where it goes")


def _literal_attribute(node):
    """
    The attribute name a call writes, when it is written out in the call.

    `setattr(obj.db, "coord", ...)` and `obj.attributes.add("coord", ...)`.
    A call passing a constant from elsewhere -- `setattr(root.db, ATTR, ...)`
    -- names nothing here and is caught by the module that defines `ATTR`
    having written it plainly at least once, or by nothing: which is why this
    test is a floor and not a proof.
    """
    if isinstance(node.func, ast.Name) and node.func.id == "setattr":
        if (len(node.args) >= 2
                and isinstance(node.args[0], ast.Attribute)
                and node.args[0].attr == "db"
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)):
            return node.args[1].value
    if (isinstance(node.func, ast.Attribute) and node.func.attr == "add"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "attributes"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)):
        return node.args[0].value
    return None
