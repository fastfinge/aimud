"""
A world as a document, and a document as a world.

A world lives in the database as a few hundred rows and a dozen registers, and
there is no way to look at it, carry it anywhere, or put it back as it was. So
`export world` writes one down and `import world` builds one, and between them
sits exactly one description of what a world *is*.

**The document is data and never code.** The same bar `world.rulesets` holds,
and for the same reason: `docs/basic-principles.md` says nothing inside the
game writes Python, and a world somebody else made is the first thing in this
game that arrives from outside it. Nothing in a document is a path, a module
name, a lock string or a dbref. Everything it says goes in through the writer
the generators already call -- `kinds.remember`, `rulebooks.add`,
`clothing.create`, `worldgen._create_room` -- so a world somebody imported and
a world a model wrote are the same world, for the same reason a world somebody
typed already is.

**Nothing in it is a dbref.** A dbref is this server's row number; on another
server it means nothing, or -- far worse -- it means some other object. Every
room, thing and person carries an `id` that is a slug of its name, and every
reference names one of those. That is also what makes the round trip in
`tests/test_exchange.py` an equality assertion: export, import, export again,
and the two documents are the same text.

**What travels is the world as it stands**, not the world as it was authored.
A door left open exports open, a lamp carried upstairs exports upstairs. That
is what makes a restore point mean a place rather than a recipe, and it is why
`token_choices` is carried (§3.4 of the plan): the seed a word list chooses
from includes the world's dbref, so a re-settled description would smell
different on the far side.

**What does not travel** is listed in `LEFT`, with the reason on each line, and
a test holds that list and `CARRIED` between them level with every attribute
this codebase writes. Export is complete on the day it is written and quietly
incomplete forever after unless something says so; `tests/test_exchange.py`
`AttributesAreAccountedFor` is that something.

See docs/archived/import-and-export.md.
"""

import json
import os
import re
from datetime import date

from evennia.utils import logger

#: The document version. A document from a later version than this server
#: knows is refused by number, rather than by the first field that fails to
#: parse.
VERSION = 1

#: What a document says it is. There is one kind today and the field exists so
#: that a second -- a zone, a character -- is refused rather than half-read.
KIND = "world"

#: Where a world keeps the document it should come back to. Set by an import
#: and by an export, read by `reset world`. The document itself and not a path
#: to one: a path can be deleted, moved, or replaced with a different world by
#: anybody with write access to the shared folder, and a reset that silently
#: rebuilt somebody else's world would be the worst bug this feature could
#: have.
RESTORE_ATTR = "restore"

#: The setting naming directories world documents are read from. The first is
#: also the one `export world` writes to. Exactly `RULESET_DIRS`' arrangement,
#: and for the same reason: a server administrator adds a directory, and
#: nothing inside the game chooses a path.
SETTING = "WORLD_DIRS"

#: Caps. Each is larger than a world anybody plays and smaller than a denial of
#: service. The file size is checked before the file is read, because a
#: document is parsed whole into memory.
MOST_BYTES = 8 * 1024 * 1024
MOST_ROOMS = 2000
MOST_THINGS = 20000
MOST_PEOPLE = 2000
MOST_RULES = 5000
MOST_ERRANDS = 2000
LONGEST_TEXT = 8000
LONGEST_ID = 64

_ID = re.compile(r"[a-z0-9_]{1,%d}" % LONGEST_ID)

#: The registers that are neither vocabulary nor contents: what a world has
#: already worked out, and the counters that name what it has already filed.
#: Carried, and the reason is money -- see `_learned`.
LEARNED = ("attempt_counts", "verbs_without_rules",
           "verbs_that_cannot_be_said", "declined_suggestions",
           "rule_failures", "standard_rules_version", "rule_counter",
           "quest_spec_counter", "verb_rules")


# ---------------------------------------------------------------------------
# What a world is made of, and what is deliberately left behind
# ---------------------------------------------------------------------------
#
# These two lists are the whole of export's honesty. `tests/test_exchange.py`
# walks every `.db.<name> =` written anywhere in `world/`, `typeclasses/` and
# `commands/` and fails when it finds one in neither, naming the file and the
# line. Adding an attribute is then a decision about whether a world carries
# it, made by whoever added it, rather than a silence found by a player whose
# imported world came back missing something.

#: Attributes a document carries, by the section that carries them. The value
#: is a note, read by nobody but the person reading this list.
CARRIED = {
    # -- the world root ---------------------------------------------------
    "world_title": "setup",
    "world_description": "setup",
    "world_guidance": "setup",
    "clock": "setup",
    "rulesets": "setup, as requires",
    "generation": "setup -- what the world may grow for itself",
    "is_world_root": "implied: the document's first room",
    "world_plan": "map",
    "zones": "map, with room ids rewritten",
    "room_coords": "map, as each room's `at`",
    # -- the registers ----------------------------------------------------
    "kind_specs": "vocabulary.kinds",
    "trait_vocabulary": "vocabulary.attributes",
    "state_vocabulary": "vocabulary.conditions",
    "state_groups": "vocabulary.conditions",
    "state_styles": "carried on the thing that wears the style",
    "action_specs": "vocabulary.actions",
    "verb_synonyms": "vocabulary.verbs",
    "noun_folds": "vocabulary.verbs, with noun set",
    "token_lists": "vocabulary.token_lists",
    "pronoun_sets": "vocabulary.pronouns",
    "rules": "vocabulary.rules -- the world's own; a ruleset's come back "
             "with the ruleset",
    "rule_counter": "learned -- ids a suspension may already name",
    "verb_rules": "learned -- the cache from before the rulebooks, still "
                  "written and still worth what it cost",
    "quest_specs": "errands",
    "quest_spec_counter": "learned",
    # -- what it has worked out -------------------------------------------
    "attempt_counts": "learned -- what was tried, so it is not paid for twice",
    "verbs_without_rules": "learned",
    "verbs_that_cannot_be_said": "learned",
    "declined_suggestions": "learned -- somebody's decision",
    "rule_failures": "learned",
    "standard_rules_version": "learned",
    # -- rooms -------------------------------------------------------------
    "desc": "the room, thing or person it is on",
    "room_title": "map.rooms",
    "room_type": "map.rooms",
    "room_category": "map.rooms",
    "is_ai_room": "implied: every room in the map",
    "world_root": "implied: every room, thing and person in the document",
    "world_parent": "implied by the map's ways",
    "zone": "map.rooms",
    "coord": "map.rooms, as `at`",
    "trait_bonuses": "rooms and things",
    "bonus_when": "rooms and things",
    "bonus_while": "things",
    # -- ways --------------------------------------------------------------
    "is_ai_exit": "implied: every way in the map",
    "pending_generation": "map.ways, as `pending`",
    "destination_hint": "map.ways, as `hint`",
    # -- things ------------------------------------------------------------
    "is_ai_item": "implied: every thing",
    "kind": "things",
    "kinds": "rooms, things and people",
    "qualifiers": "things",
    "affordances": "things",
    "ai_takeable": "things, as `takeable`",
    "states": "rooms, things and people",
    "clothing_type": "things",
    "relation": "things, as `relation.how`",
    "relation_to": "things, as `relation.to`",
    "owner": "things -- the name, never the dbref",
    "token_choices": "rooms, things and people, as `choices`",
    # -- people ------------------------------------------------------------
    "is_npc": "implied: every person",
    "pronoun_set": "people",
    "manner": "people",
    "goal": "people",
    "following": "people",
}

#: Attributes a document deliberately does not carry, and why. Not a denylist
#: to be filled in quietly: each line is an answer, and §4 of
#: docs/archived/import-and-export.md is this list in prose.
LEFT = {
    # -- the player's own, never the world's --------------------------------
    "created_worlds": "an account's, and the importer's own",
    "world_last_locations": "where a player last stood, which is theirs",
    "world_names": "what a player called themselves there",
    "world_descs": "what a player looked like there",
    "quests": "a quest in progress belongs to whoever accepted it",
    "quests_done": "the same, one step later",
    "world_creator": "the importer becomes the creator",
    "restore": "the document a world comes back to. Never inside a document: "
               "a world carrying its own restore point would carry a copy of "
               "itself, and each export would carry the last one",
    "openrouter_api_key": "an account's key, and the one thing in this game "
                          "that must never be written to a file",
    "api_base_url": "where an account's key is spent",
    "ai_models": "which model an account pays for, per job",
    "ai_params": "how an account has tuned its models",
    "ai_fallbacks": "which models an account falls back to",
    "exported_worlds": "which exports an account wrote, so it may remove "
                       "them; per account, and never in the file",
    "world_mode": "how hard a world thinks is what its owner spends, and the "
                  "importer is the one paying",
    "spend_totals": "the ledger, per account",
    "spend_recent": "the ledger, per account",
    "loop_totals": "the ledger, per account",
    # -- what happened, rather than what is ---------------------------------
    "action_history": "what a character has been through, which is memory",
    "last_near_player": "true of a moment, not of a world",
    "goal_stalls": "how a plan is going, not what the plan is",
    "goal_waiting": "the same",
    "goal_from_quest": "a quest in progress, which does not travel",
    "becomes_seen": "an edge already crossed; the rules that watch for it do "
                    "travel",
    "becomes_overflow": "the same",
    "referents": "what `it` last meant, which is one conversation",
    "world_condition": "a crossing in progress",
    "busy_interval": "how often to say somebody is waiting; a preference",
    "pronouns": "a player's own, set with `pronouns`",
    "verb_specifics": "a cache of what one attempt settled",
    # -- settings and preferences -------------------------------------------
    "menu_view_mode": "a player's preference",
    "menu_show_command": "a player's preference",
    "menu_page_size": "a player's preference",
    "confirmations": "a player's preference",
    "ai_commands": "what a session is allowed to type",
}


# ---------------------------------------------------------------------------
# Plain values, and local ids
# ---------------------------------------------------------------------------

def plain(value):
    """
    An Attribute's contents as plain JSON-able Python.

    Evennia hands back `_SaverDict` and `_SaverList` proxies that json refuses,
    and a dbref where an object was stored. The dbref case is why the fallback
    is `None` rather than `str(value)`: a document that quietly contained
    `"<Room: The Gym>"` where an id belonged would import as a world with a
    piece of English in a field a rule reads.
    """
    from evennia.utils.dbserialize import deserialize

    value = deserialize(value)
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def slug(text, fallback="thing"):
    """A local id from a name: lowercase, words joined with underscores."""
    made = re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")
    made = re.sub(r"_+", "_", made)[:LONGEST_ID].strip("_")
    return made or fallback


class Names:
    """
    Local ids for the things in a world, and the objects behind them.

    One namespace for rooms, things and people together, because a thing's
    `at` may name any of the three and a reference that has to be read twice
    to know what it points at is a reference that will one day be read wrongly.
    A collision takes a number: `the_gym`, `the_gym_2`.
    """

    def __init__(self):
        self.by_object = {}
        self.by_id = {}

    def name(self, obj, fallback="thing"):
        """The id for this object, assigning one the first time."""
        if obj is None:
            return ""
        known = self.by_object.get(obj.id)
        if known:
            return known
        wanted = slug(getattr(obj, "key", "") or fallback, fallback)
        made, number = wanted, 1
        while made in self.by_id:
            number += 1
            made = f"{wanted[:LONGEST_ID - 3]}_{number}"
        self.by_object[obj.id] = made
        self.by_id[made] = obj
        return made

    def of(self, obj):
        """The id already assigned to this object, or "" -- never a new one."""
        return self.by_object.get(getattr(obj, "id", None), "") if obj else ""

    def put(self, made, obj):
        """Record an object under an id an import is building from."""
        self.by_id[str(made)] = obj
        if obj is not None:
            self.by_object[obj.id] = str(made)

    def object(self, made):
        """The object an id names, or None."""
        return self.by_id.get(str(made or ""))


# ---------------------------------------------------------------------------
# Walking a world
# ---------------------------------------------------------------------------

def rooms_of(root):
    """Every room of a world, its first room first and the rest by age."""
    from evennia import search_tag

    if root is None:
        return []
    found = list(search_tag(str(root.id), category="ai_world"))
    found.sort(key=lambda room: (room.id != root.id, room.id))
    return found


def _is_person(obj):
    return bool(getattr(obj.db, "is_npc", False))


def _is_player(obj):
    from evennia.objects.objects import DefaultCharacter

    return isinstance(obj, DefaultCharacter) and not _is_person(obj)


def _is_way(obj):
    return getattr(obj, "destination", None) is not None


def contents_of(root):
    """
    (people, things) everywhere in this world, each with where it belongs.

    Returned as `[(obj, holder)]`, holder being the room, person or thing it
    is in. Walked from the rooms rather than searched by attribute, because
    `clothing.create` writes no `world_root` onto an item and never needed to:
    a thing is in this world because it is in a room of it.

    **A player character is not part of a world, and what they are holding
    is.** Their things come back loose in the room they were standing in. A
    world missing its crowbar is broken; a world with a crowbar on the floor
    is not. See docs/archived/import-and-export.md 4.1.
    """
    people, things = [], []

    def walk(holder, into):
        for obj in list(getattr(holder, "contents", None) or []):
            if _is_way(obj):
                continue
            if _is_player(obj):
                # Their pockets are the world's; they are not.
                walk(obj, into)
                continue
            if _is_person(obj):
                people.append((obj, into))
                walk(obj, obj)
            else:
                things.append((obj, into))
                walk(obj, obj)

    for room in rooms_of(root):
        walk(room, room)
    return people, things


# ---------------------------------------------------------------------------
# Reading a world out
# ---------------------------------------------------------------------------

def document(root):
    """
    Everything this world is, as one JSON-able dict.

    The sections come out in the order an import needs them, so a document
    read straight down is a world built straight down: what it was set up
    with, the vocabulary its rules are written in, the map, what is standing
    in it, and what it has already worked out.
    """
    from world import lore

    if root is None:
        return {}
    names = Names()
    rooms = rooms_of(root)
    people, things = contents_of(root)
    # Named before anything refers to anything: a rule may be scoped to a
    # thing, and an errand given by somebody, and both are read after this.
    for room in rooms:
        names.name(room, "room")
    for person, _where in people:
        names.name(person, "person")
    for thing, _where in things:
        names.name(thing, "thing")

    return {
        "aimud": VERSION,
        "kind": KIND,
        "title": lore.title(root),
        "exported": date.today().isoformat(),
        # At the top so that a listing can say how big a world is without
        # parsing the document whole.
        "rooms": len(rooms),
        "requires": _requires(root),
        "setup": _setup(root),
        "vocabulary": _vocabulary(root, names),
        "map": _map(root, rooms, names),
        # Sorted by id rather than left in the order the world was walked.
        # The walk follows creation order, and an imported world creates
        # people before things and things holder-first, so the same world
        # exported twice would list the same objects in two orders and the
        # round-trip test in tests/test_exchange.py would be comparing
        # arrangements rather than worlds. A sorted document also diffs.
        "things": sorted((_thing(obj, where, names) for obj, where in things),
                         key=lambda record: record["id"]),
        "people": sorted((_person(obj, where, names) for obj, where in people),
                         key=lambda record: record["id"]),
        "errands": _errands(root, names),
        "learned": _learned(root),
    }


def _requires(root):
    """
    What a server must already have before this world can be built.

    Asked of what the world holds, and of what it *chose* when it holds
    nothing -- a world built by hand is seeded on its way past rather than at
    its creation, and a document that named no rulesets would import as a
    world where reaching what you act on is not a rule.
    """
    from world import rulesets

    held = rulesets.held(root)
    wanted = sorted(held) or rulesets.chosen(root) or rulesets.defaults()
    versions = {}
    for name in wanted:
        version = held.get(name)
        if version is None:
            doc = rulesets.get(name) or {}
            version = doc.get("version", 1)
        versions[name] = int(version)
    return {
        "rulesets": versions,
        # Empty, and refused if it is not. `future-plans.md` says worlds must
        # say which plugins they need; plugins do not exist yet, and a field
        # that is always empty is a promise nobody keeps. So a document
        # written after they do is refused clearly by a server from before
        # them, rather than imported wrongly. See docs/archived/import-and-export.md 14.
        "plugins": [],
    }


def _setup(root):
    """
    The wizard's own spec, less the two fields that are the player's.

    `player_name` and `player_description` are what *you* looked like there.
    `lore.spec_of` carries them because `reset world` rebuilds the world you
    were in; a document describes a place, and the people who visited it are
    not part of it.
    """
    from world import lore

    spec = lore.spec_of(root)
    spec.pop("player_name", None)
    spec.pop("player_description", None)
    return plain(spec)


def _vocabulary(root, names):
    """
    Everything this world invented, as a ruleset document.

    Section for section, so that `rulesets.problems` validates it and
    `rulesets._apply` writes it -- which buys the check that matters most,
    `_undeclared`, refusing a rule that names a state nothing declares. That
    failure is silence, and an imported world is exactly where it would
    otherwise land. See docs/archived/import-and-export.md 3.3.

    Only what the world invented. A rule a ruleset seeded comes back with the
    ruleset, named in `requires`; what is kept of it is the world's decision
    about it, which `decided` carries.
    """
    from world import folds, kinds, lore, rulebooks, rulesets

    title = lore.title(root)
    mine = [rule for rule in rulebooks.all_rules(root)
            if not rulesets.from_ruleset(rule)]
    doc = {
        "name": slug(title, "world"),
        "title": title,
        "version": 1,
        "means": (root.db.world_description or title or "A world.")[:400],
        "requires": sorted(rulesets.held(root)),
        # `accepts` and not `holds`, because `accepts` is what
        # `kinds.remember` takes and `holds` is what it answers: the declared
        # placements plus whatever the taxonomy already knew. Writing the
        # answer back in as the question is exact rather than lossy -- the
        # floor is re-added on the way in, so a second pass changes nothing.
        "kinds": [
            {"kind": kind,
             "affordances": plain((kinds.spec(root, kind) or {})
                                  .get("affordances") or {}),
             "accepts": plain((kinds.spec(root, kind) or {})
                              .get("holds") or []),
             "under": str((kinds.spec(root, kind) or {}).get("under") or "")}
            for kind in kinds.vocabulary(root)
        ],
        "attributes": [
            dict(plain(entry), slug=name)
            for name, entry in sorted((root.db.trait_vocabulary or {}).items())
        ],
        "conditions": _conditions(root),
        "actions": [
            plain(entry)
            for _name, entry in sorted((root.db.action_specs or {}).items())
        ],
        "verbs": (
            [{"word": word, "means": means}
             for word, means in sorted(folds.verbs_of(root).items())]
            + [{"word": word, "means": means, "noun": True}
               for word, means in sorted(folds.nouns_of(root).items())]
        ),
        "token_lists": [
            dict(plain(entry), name=name)
            for name, entry in sorted((root.db.token_lists or {}).items())
        ],
        "pronouns": [
            dict(plain(entry), slug=name)
            for name, entry in sorted((root.db.pronoun_sets or {}).items())
        ],
        "rules": [record for record in (_rule(rule, names) for rule in mine)
                  if record is not None],
        # What this world decided about the rules its rulesets gave it.
        # Suspensions are a person's answer and a fresh seeding would undo
        # them, which is the arrangement `rulesets._decisions` already keeps
        # across an edition.
        "decided": {
            str(rule.get("name") or ""): bool(rule.get("listed", True))
            for rule in rulebooks.all_rules(root)
            if rulesets.from_ruleset(rule)
            and not rule.get("listed", True)
        },
    }
    return doc


def _conditions(root):
    """
    The world's own groups, and then every condition it knows, in full.

    Groups first, because a state names the group it belongs to and
    `register_group` has to have run for the group to behave as declared.

    Each state is written out whole rather than as a name inside its group.
    A name alone is what a ruleset writes, and it is enough there because a
    ruleset is introducing the word; here the word already has a meaning, a
    set of conflicts and possibly a definition -- `when` makes it a condition
    worked out rather than set -- and a document that carried only the spelling
    would import a world where `starving` meant nothing.
    """
    found = []
    for group, rules in sorted((root.db.state_groups or {}).items()):
        found.append(dict(plain(rules) or {}, group=group))
    for name, said in sorted((root.db.state_vocabulary or {}).items()):
        found.append(dict(plain(said) or {}, state=name))
    return found


def _rule(rule, names):
    """
    One rule, with a scope that names a thing rather than a row.

    A rule scoped to something that is not in this world any more is dropped,
    loudly. Not kept with its scope stripped: that would turn "while the ship
    is powered" into "always", which is a rule doing something rather than a
    rule doing nothing. It has been doing nothing for as long as the thing has
    been gone.
    """
    from world import rulebooks

    record = plain(rule) or {}
    record.pop("id", None)
    record.pop("born", None)
    scope = dict(record.get("scope") or {})
    for key in (rulebooks.OBJECT, rulebooks.ROOM):
        if key not in scope:
            continue
        named = names.by_object.get(scope[key])
        if not named:
            logger.log_info(
                f"exchange: {record.get('name')!r} is about something no "
                f"longer in this world and was not exported")
            return None
        scope[key] = named
    record["scope"] = scope
    return record


def _map(root, rooms, names):
    """The rooms, where each one sits, the ways between them, and the zones."""
    return {
        "plan": plain(root.db.world_plan or {}),
        "zones": _zones(root, names),
        "rooms": [_room(room, names) for room in rooms],
        "ways": _ways(rooms, names),
    }


def _zones(root, names):
    """The zone registry, with the rooms in each named rather than numbered."""
    from evennia.objects.models import ObjectDB

    found = {}
    for zone_id, record in sorted((root.db.zones or {}).items()):
        entry = plain(record) or {}
        held = []
        for dbref in entry.get("rooms") or []:
            room = ObjectDB.objects.filter(id=dbref).first()
            named = names.of(room) if room is not None else ""
            if named:
                held.append(named)
        entry["rooms"] = held
        found[zone_id] = entry
    return found


def _room(room, names):
    from world import coords, token_lists, verbs

    coord = coords.get_coord(room)
    return {
        "id": names.of(room),
        "title": room.db.room_title or room.key,
        "description": room.db.desc or "",
        "choices": plain(getattr(room.db, token_lists.CHOICES, None) or {}),
        "at": list(coord) if coord else None,
        "zone": str(room.db.zone or ""),
        "type": str(room.db.room_type or ""),
        "category": str(room.db.room_category or ""),
        "kinds": plain(room.db.kinds or []),
        "states": plain(room.db.states or []),
        "styles": verbs.styles(room),
        "trait_bonuses": plain(room.db.trait_bonuses or {}),
        "bonus_when": str(room.db.bonus_when or ""),
    }


def _ways(rooms, names):
    """
    Every way out of every room, in both directions.

    Both, and nothing inferred: `_create_room` makes a back-exit for a room it
    is building, and an import is not building a world by walking it. A way
    whose destination is outside this world -- which nothing makes, but a
    stray `@open` would -- is left out rather than exported pointing nowhere.
    """
    found = []
    for room in rooms:
        for obj in room.contents:
            if not _is_way(obj):
                continue
            record = {
                "name": obj.key,
                "from": names.of(room),
                "aliases": sorted(str(a) for a in obj.aliases.all()),
            }
            if obj.db.pending_generation:
                record["pending"] = True
                record["hint"] = str(obj.db.destination_hint or "")
            else:
                to = names.of(obj.destination)
                if not to:
                    continue
                record["to"] = to
            found.append(record)
    # By where they lead from and what they are called, for the reason the
    # things and people are sorted: a room's contents come back in creation
    # order, which an import does not reproduce and does not need to.
    found.sort(key=lambda record: (record["from"], record["name"]))
    return found


def _thing(obj, where, names):
    """One thing, as the spec that would have made it."""
    from world import ownership, relations, token_lists, verbs

    record = {
        "id": names.of(obj),
        "name": obj.key,
        "description": obj.db.desc or "",
        "choices": plain(getattr(obj.db, token_lists.CHOICES, None) or {}),
        "kind": str(obj.db.kind or ""),
        "kinds": plain(obj.db.kinds or []),
        "qualifiers": plain(obj.db.qualifiers or []),
        "affordances": plain(obj.db.affordances or {}),
        "states": plain(obj.db.states or []),
        # How it is in each of them: "tied loosely around her waist". Carried
        # whole rather than as the one `wearstyle` `clothing.create` takes,
        # because a style is not only about being worn.
        "styles": verbs.styles(obj),
        "takeable": bool(obj.db.ai_takeable
                         if obj.db.ai_takeable is not None else True),
        "at": names.of(where),
        "trait_bonuses": plain(obj.db.trait_bonuses or {}),
        "bonus_when": str(obj.db.bonus_when or ""),
        "bonus_while": str(obj.db.bonus_while or ""),
        "clothing_type": str(obj.db.clothing_type or ""),
    }
    # `relation_of` and not the `relation_to` attribute, which only the
    # pointer relations -- under, behind -- ever set. A lamp *on* a table is
    # inside it as far as the database is concerned, and its preposition lives
    # on `db.relation` with nothing pointing anywhere; reading the attribute
    # alone exported the lamp as merely being in the table, and it came back
    # in it.
    preposition, host = relations.relation_of(obj)
    if host is not None and names.of(host):
        record["relation"] = {"to": names.of(host), "how": preposition}
    owner = ownership.record(obj)
    if owner:
        # The name, never the dbref. A thing whose owner does not come with it
        # arrives as something somebody who is gone once owned, which is a
        # state `ownership.orphaned` already has a name for.
        record["owner"] = {"name": str(owner.get("name") or ""),
                           "of": names.of(ownership.owner_of(obj))}
    return record


def _person(obj, where, names):
    """One character, as the fields the hand-built NPC form writes."""
    from world import token_lists, traits, verbs

    return {
        "id": names.of(obj),
        "name": obj.key,
        "description": obj.db.desc or "",
        "choices": plain(getattr(obj.db, token_lists.CHOICES, None) or {}),
        "manner": str(obj.db.manner or ""),
        "pronouns": str(obj.db.pronoun_set or ""),
        "kinds": plain(obj.db.kinds or []),
        "states": plain(obj.db.states or []),
        "styles": verbs.styles(obj),
        # The figure as it is stored, not as it is felt: `traits.value` adds
        # what a coat or a sword is lending, and importing a sum as a base
        # would make the coat count twice.
        "traits": [{"trait": name, "value": plain(getattr(figure, "value", None))}
                   for name, figure in traits.all_of(obj)],
        "goal": plain(obj.db.goal or []),
        "at": names.of(where),
        "following": names.of(obj.db.following),
    }


def _errands(root, names):
    """Every errand this world holds, with its givers named."""
    from evennia.objects.models import ObjectDB
    from world import quests

    found = []
    for spec_id, spec in sorted(quests.specs(root).items()):
        record = plain(spec) or {}
        record.pop("id", None)
        givers = []
        for giver in record.get("givers") or []:
            npc = ObjectDB.objects.filter(id=giver.get("npc")).first()
            named = names.of(npc) if npc is not None else ""
            if named:
                givers.append(dict(giver, npc=named))
        record["givers"] = givers
        record["key"] = spec_id
        found.append(record)
    return found


def _learned(root):
    """
    What this world has already worked out, and what it has been told.

    Carried rather than left, and the reason is money. `attempt_counts` is
    what has been tried and how it went; `verbs_without_rules` is the list a
    model was already asked about and had nothing to say; and a declined
    suggestion is a decision somebody made. An import that dropped them would
    re-ask every one of those questions on somebody else's key.

    The counters are carried for a duller reason: `rulebooks.add` names rules
    from `rule_counter`, and a world whose counter restarted would issue an id
    that a suspension or a suggestion's `overrides` already names.
    """
    return {name: plain(getattr(root.db, name, None))
            for name in LEARNED
            if getattr(root.db, name, None) is not None}


# ---------------------------------------------------------------------------
# Refusing a document
# ---------------------------------------------------------------------------
#
# Nothing is imported by halves, for the reason `rulesets._refuse` gives: half
# a ruleset is a world whose rules mention states nothing registers, which is
# worse than not having it. Half a world is worse still. So everything below
# runs to completion, before a single object is made, and a document with any
# complaint at all builds nothing.

#: The sections a world document may have. Anything else is refused, the way
#: `rulesets.problems` refuses an unknown section: a section nobody reads is a
#: promise nobody keeps.
SECTIONS = ("aimud", "kind", "title", "exported", "rooms", "requires",
            "setup", "vocabulary", "map", "things", "people", "errands",
            "learned")


def problems(doc, known=None):
    """
    What is wrong with this document, as short sentences; [] when nothing is.

    A complaint names the section and the id, because "a way goes nowhere" in
    a world of two hundred rooms is not something anybody can act on.

    `known` is the rulesets this server has, for a test that wants to pretend
    it has different ones.
    """
    if not hasattr(doc, "keys"):
        return ["that is not a world document"]

    wrong = []
    version = doc.get("aimud")
    if not isinstance(version, int) or isinstance(version, bool):
        wrong.append("it does not say which version of aimud wrote it")
    elif version > VERSION:
        wrong.append(f"it was written by aimud {version}, and this server "
                     f"reads {VERSION}")
    if str(doc.get("kind") or "") != KIND:
        wrong.append(f"it is not a world; it says it is a {doc.get('kind')!r}")
    if wrong:
        # No point reading the rest of a document whose first two fields say
        # it is not one of ours: every complaint after this would be about a
        # shape nobody promised.
        return wrong

    unknown = sorted(set(doc) - set(SECTIONS))
    if unknown:
        wrong.append(
            f"nothing reads {', '.join(repr(name) for name in unknown)}; a "
            f"section nobody reads is a promise nobody keeps")

    wrong.extend(_shapes(doc))
    if wrong:
        return wrong

    wrong.extend(_caps(doc))
    wrong.extend(_required(doc, known))
    wrong.extend(_vocabulary_problems(doc, known))
    wrong.extend(_map_problems(doc))
    wrong.extend(_reference_problems(doc))
    return wrong


#: What each section must be before anything reads it. A document whose `map`
#: is a string has to be refused before `_map_problems` asks it for its rooms.
_SHAPES = {
    "requires": dict, "setup": dict, "vocabulary": dict, "map": dict,
    "learned": dict, "things": list, "people": list, "errands": list,
}


def _is_list(value):
    return not isinstance(value, str) and hasattr(value, "__iter__")


def _shapes(doc):
    wrong = []
    for section, wanted in _SHAPES.items():
        value = doc.get(section)
        if value is None:
            continue
        if wanted is dict and not hasattr(value, "keys"):
            wrong.append(f"{section} is not an object")
        elif wanted is list and not _is_list(value):
            wrong.append(f"{section} is not a list")
    for section in ("things", "people", "errands"):
        if not _is_list(doc.get(section) or []):
            continue
        for entry in doc.get(section) or []:
            if not hasattr(entry, "keys"):
                wrong.append(f"something in {section} is not an object")
                break
    world_map = doc.get("map") or {}
    if hasattr(world_map, "keys"):
        for section, wanted in (("rooms", list), ("ways", list),
                                ("zones", dict), ("plan", dict)):
            value = world_map.get(section)
            if value is None:
                continue
            if wanted is dict and not hasattr(value, "keys"):
                wrong.append(f"map.{section} is not an object")
            elif wanted is list and not _is_list(value):
                wrong.append(f"map.{section} is not a list")
            elif wanted is list:
                for entry in value:
                    if not hasattr(entry, "keys"):
                        wrong.append(
                            f"something in map.{section} is not an object")
                        break
    return wrong


def _caps(doc):
    """Bigger than a world anybody plays. See MOST_ROOMS and the rest."""
    wrong = []
    world_map = doc.get("map") or {}
    vocabulary = doc.get("vocabulary") or {}
    for section, most, said in (
            (world_map.get("rooms"), MOST_ROOMS, "rooms"),
            (doc.get("things"), MOST_THINGS, "things"),
            (doc.get("people"), MOST_PEOPLE, "people"),
            (doc.get("errands"), MOST_ERRANDS, "errands"),
            (vocabulary.get("rules"), MOST_RULES, "rules")):
        if section is not None and len(section) > most:
            wrong.append(f"it has {len(section)} {said}, and {most} is as "
                         f"many as this server will build")

    for section in ("rooms", "ways"):
        for entry in world_map.get(section) or []:
            wrong.extend(_text_caps(entry, f"map.{section}"))
    for section in ("things", "people"):
        for entry in doc.get(section) or []:
            wrong.extend(_text_caps(entry, section))
    return wrong[:20]


def _text_caps(entry, said):
    wrong = []
    for field in ("description", "name", "title", "manner", "hint"):
        text = entry.get(field)
        if isinstance(text, str) and len(text) > LONGEST_TEXT:
            wrong.append(f"the {field} of {entry.get('id') or said!r} is "
                         f"{len(text)} characters, and {LONGEST_TEXT} is the "
                         f"most one may be")
    return wrong


def _required(doc, known=None):
    """
    Whether this server has what the document was built on.

    A missing ruleset is refused rather than skipped, because what it would
    have given the world is what the world's rules were written against: a
    world imported without `clothing` has rules about wearing things and
    nothing that knows what wearing is. A *higher* version here is fine --
    `rulesets._retire` already replaces an edition and carries a world's
    decisions across it, which is exactly what an older world arriving wants.
    """
    from world import rulesets

    wrong = []
    requires = doc.get("requires") or {}
    if not hasattr(requires, "keys"):
        return ["requires is not an object"]

    plugins = requires.get("plugins") or []
    if not _is_list(plugins):
        wrong.append("requires.plugins is not a list")
    elif plugins:
        # Named rather than ignored. Plugins do not exist yet; a document
        # written after they do must be refused clearly by a server from
        # before them rather than imported wrongly. See
        # docs/archived/import-and-export.md 14.
        wrong.append(
            f"it needs the plugin {', '.join(repr(str(p)) for p in plugins)}, "
            f"and this server has no plugins at all")

    wanted = requires.get("rulesets") or {}
    if not hasattr(wanted, "keys"):
        return wrong + ["requires.rulesets is not an object"]
    available = rulesets.available() if known is None else known
    for name, version in sorted(wanted.items()):
        theirs = available.get(str(name))
        if theirs is None:
            wrong.append(f"it was built with the ruleset {name!r}, which this "
                         f"server does not have")
            continue
        try:
            here, there = int(theirs.get("version", 1)), int(version)
        except (TypeError, ValueError):
            wrong.append(f"the version it wants of {name!r} is not a number")
            continue
        if here < there:
            wrong.append(f"it was built with {name!r} version {there}, and "
                         f"this server has version {here}")
    return wrong


def _vocabulary_problems(doc, known=None):
    """
    The vocabulary half, judged as the ruleset it is.

    This is where the format earns its constraint. `rulesets.problems` already
    refuses a rule with no phase this game runs, a condition too deep to
    store, a `becomes` rule written with `conditions` instead of `when`, an
    action requiring something `actions.MUSTS` does not name, and -- through
    `_undeclared` -- a rule asking about a figure the document never
    registers. Every one of those fails by doing nothing, which is the worst
    way there is, and an imported world is the one place they could arrive
    already separated from the vocabulary that made sense of them.
    """
    from world import rulesets

    vocabulary = doc.get("vocabulary")
    if vocabulary is None:
        return []
    if not hasattr(vocabulary, "keys"):
        return ["vocabulary is not an object"]
    # `decided` is this document's own: which of a ruleset's rules the world
    # had switched off. `rulesets.problems` refuses a section it does not
    # read, and rightly, so it is taken out before the document is judged as
    # a ruleset.
    asked = {name: value for name, value in vocabulary.items()
             if name != "decided"}
    return [f"vocabulary: {complaint}"
            for complaint in rulesets.problems(asked, known=known)]


def _map_problems(doc):
    """A map that is a map: one room to a cell, every zone accounted for."""
    world_map = doc.get("map") or {}
    rooms = world_map.get("rooms") or []
    wrong, seen_ids, seen_cells = [], set(), {}

    # A world is somewhere before it is anything else, and the first room in
    # the list is the one the world root becomes. A document with none would
    # build a world with an unnamed room in it and say nothing.
    if not rooms:
        return ["it has no rooms, so there is no world in it"]

    for room in rooms:
        made = str(room.get("id") or "")
        if not _ID.fullmatch(made):
            wrong.append(f"a room's id, {made!r}, is not a plain name")
            continue
        if made in seen_ids:
            wrong.append(f"there are two rooms called {made!r}")
        seen_ids.add(made)
        at = room.get("at")
        if at is None:
            # A room behind a portal or a labelled exit is never placed, which
            # `zones._admit` already allows for. It is not a fault.
            continue
        try:
            cell = (int(at[0]), int(at[1]), int(at[2]))
        except (TypeError, ValueError, IndexError, KeyError):
            wrong.append(f"{made!r} is not anywhere a room can be: {at!r}")
            continue
        if cell in seen_cells:
            wrong.append(f"{made!r} and {seen_cells[cell]!r} are both at "
                         f"{list(cell)}, and two rooms never share a cell")
        seen_cells[cell] = made

    zones = world_map.get("zones") or {}
    for room in rooms:
        zone = str(room.get("zone") or "")
        if zone and zones and zone not in zones:
            wrong.append(f"{room.get('id')!r} is in the zone {zone!r}, which "
                         f"this document does not describe")
    return wrong[:20]


def _reference_problems(doc):
    """
    Every id named anywhere exists. This is what local ids are for.

    A door onto a room that is not in the document is a fault and never a
    pending way: `pending` is a way that promises a room nobody has *built*,
    and it says so itself.
    """
    from world import rulebooks

    world_map = doc.get("map") or {}
    rooms = {str(room.get("id") or "") for room in world_map.get("rooms") or []}
    people = {str(entry.get("id") or "") for entry in doc.get("people") or []}
    things = {str(entry.get("id") or "") for entry in doc.get("things") or []}
    anywhere = rooms | people | things

    wrong = []

    def check(named, among, said, whose):
        named = str(named or "")
        if named and named not in among:
            wrong.append(
                f"{whose} names {named!r}, which is not {said} in this "
                f"document")

    for way in world_map.get("ways") or []:
        whose = f"the way {way.get('name')!r} out of {way.get('from')!r}"
        check(way.get("from"), rooms, "a room", whose)
        if not way.get("from"):
            wrong.append(f"{whose} is not anywhere")
        if way.get("pending"):
            if way.get("to"):
                wrong.append(f"{whose} is pending and also goes somewhere; it "
                             f"is one or the other")
        elif not way.get("to"):
            wrong.append(f"{whose} goes nowhere and is not pending")
        else:
            check(way.get("to"), rooms, "a room", whose)

    for entry in doc.get("things") or []:
        whose = f"the thing {entry.get('id')!r}"
        if not entry.get("at"):
            wrong.append(f"{whose} is nowhere")
        check(entry.get("at"), anywhere, "here", whose)
        relation = entry.get("relation") or {}
        if relation:
            check(relation.get("to"), things, "a thing", whose)
        owner = entry.get("owner") or {}
        if owner.get("of"):
            check(owner.get("of"), people, "somebody", whose)

    for entry in doc.get("people") or []:
        whose = f"the person {entry.get('id')!r}"
        check(entry.get("at"), rooms, "a room", whose)
        check(entry.get("following"), people, "somebody", whose)

    for entry in doc.get("errands") or []:
        whose = f"the errand {entry.get('key') or entry.get('title')!r}"
        for giver in entry.get("givers") or []:
            check(giver.get("npc"), people, "somebody", whose)

    for rule in (doc.get("vocabulary") or {}).get("rules") or []:
        if not hasattr(rule, "keys"):
            continue
        scope = rule.get("scope") or {}
        whose = f"the rule {rule.get('name')!r}"
        if hasattr(scope, "keys"):
            check(scope.get(rulebooks.OBJECT), anywhere, "here", whose)
            check(scope.get(rulebooks.ROOM), rooms, "a room", whose)
    return wrong[:20]


# ---------------------------------------------------------------------------
# Building a world from a document
# ---------------------------------------------------------------------------
#
# Three passes, and the order is the order the sections come in. The world
# first, because everything needs a root to belong to; then the vocabulary,
# because a description may name a word list and a thing may name a condition;
# then the map and what is standing in it; and only then the references and
# the rules, because a rule may be about one particular lamp.
#
# Nothing here calls a model. An import is free, and works on a server with no
# API key at all -- which is what makes a world somebody shares playable by
# somebody who has not paid for anything.


class Refused(Exception):
    """A document that cannot be built, with everything wrong with it."""

    def __init__(self, complaints):
        self.complaints = list(complaints)
        super().__init__("; ".join(self.complaints))


def build(doc, account, character=None, known=None):
    """
    Build a world from a document, and answer with its first room.

    Raises `Refused` before making anything at all when the document is not
    one this server can build. Nothing is made by halves: validation runs to
    completion first, so a refusal leaves no room, no object and no world root
    behind.

    `account` becomes the world's creator, its owner and whoever pays for it.
    There is nowhere in a document for an account on another server, and this
    is the one write.
    """
    from world import rulesets, sponsor as sponsor_mod, worldgen

    wrong = problems(doc, known=known)
    if wrong:
        raise Refused(wrong)

    names = Names()
    made = {}
    worldgen.first_room_by_hand(
        sponsor_mod.of_account(account) if account is not None
        else sponsor_mod.Sponsor(actor=character),
        dict(doc.get("setup") or {}),
        lambda room: made.setdefault("root", room),
        lambda err: made.setdefault("error", err),
        creator_character=character)
    root = made.get("root")
    if root is None:
        raise Refused([made.get("error") or "the first room could not be made"])

    vocabulary = dict(doc.get("vocabulary") or {})
    try:
        _decided(root, vocabulary.get("decided") or {})
        # Rules last of all, because a rule may be scoped to a thing that does
        # not exist until the map is built. Everything else a rule could name
        # -- kinds, conditions, actions, figures -- goes in now.
        rulesets._apply(root, dict(vocabulary, rules=[]), {})

        _build_map(root, doc.get("map") or {}, names)
        _build_people(root, doc.get("people") or [], names)
        _build_things(root, doc.get("things") or [], names)
        _place_things(doc.get("things") or [], names)
        _build_errands(root, doc.get("errands") or [], names)
        _build_rules(root, vocabulary.get("rules") or [], names)
        _build_learned(root, doc.get("learned") or {})
    except Exception as exc:
        # `problems` has judged this document already, so arriving here means
        # a fault in the building rather than in the document -- and the one
        # thing that must not happen is somebody being left owning half a
        # world with no way to say so. Torn down, and the reason kept.
        logger.log_trace(f"exchange: building {doc.get('title')!r} failed")
        _abandon(root, account)
        raise Refused([f"it could not be built: {exc}"]) from exc

    # What it comes back to. An import is the one moment a world has a state
    # somebody chose rather than one it drifted into.
    remember(root, doc)
    return root


def _abandon(root, account):
    """
    Take away a world that was half built, and everything in it.

    `clear_world` is the one that knows how -- characters out first, then
    everything else destroyed, then the world forgotten by the account that
    was about to own it. Imported here rather than at the top because
    `commands` imports `world` and not the other way about.
    """
    from commands.world_subject import clear_world

    try:
        clear_world(root, account, message=(
            "|rThat world could not be built, and has been taken away.|n"))
    except Exception:
        logger.log_trace("exchange: the half-built world could not be "
                         "cleared either")


def _decided(root, decided):
    """
    Put back what this world had switched off among its rulesets' rules.

    Written before the vocabulary rather than after, because `lore.store` has
    already seeded the rulesets by the time `first_room_by_hand` returns, so
    the rules these name are already filed.
    """
    from world import rulebooks

    if not decided:
        return
    for rule in rulebooks.all_rules(root):
        name = str(rule.get("name") or "")
        if name in decided:
            rulebooks.set_listed(root, rule.get("id"), bool(decided[name]))


def _build_map(root, world_map, names):
    """
    The rooms, where each one sits, and the ways between them.

    **Placed by coordinate, never by walking.** `_create_room` places a room
    either at the origin or one step from where the player came, because that
    is how a world grows. An import is not growing a world, it is laying one
    out, and a world that closes back on itself would not survive being
    rebuilt by walking it: the second room to reach a cell would find it taken
    and be wired to what was already there.
    """
    from world import worldgen

    if root.db.world_plan is None or not root.db.world_plan:
        root.db.world_plan = dict(world_map.get("plan") or {})

    rooms = list(world_map.get("rooms") or [])
    for position, record in enumerate(rooms):
        if position == 0:
            # The world root is the document's first room: made already, by
            # `first_room_by_hand`, which is what gave the world its setup.
            room = root
        else:
            room = worldgen._create_room(
                str(record.get("title") or record.get("id") or "Somewhere"),
                "", [], root.db.world_description or "", None, None,
                world_root=root,
                room_type=str(record.get("type") or ""),
                category=str(record.get("category") or ""),
                zone=str(record.get("zone") or ""))
        names.put(str(record.get("id") or ""), room)
        _write_room(room, record)
        _place(root, room, record.get("at"))

    # After the rooms, and verbatim: `zones.attach` rebuilt a tree while the
    # rooms were being made, and what the document says is what the world
    # actually had. Room ids become dbrefs on the way in.
    zones = {}
    for zone_id, record in (world_map.get("zones") or {}).items():
        entry = dict(record or {})
        entry["rooms"] = [names.object(named).id
                          for named in entry.get("rooms") or []
                          if names.object(named) is not None]
        zones[str(zone_id)] = entry
    if zones:
        root.db.zones = zones

    _build_ways(world_map.get("ways") or [], names)


def _place(root, room, at):
    """
    Put a room where the document says it is, moving it if it is elsewhere.

    `_create_room` places every room it makes at the origin, because that is
    what it does for a room with nowhere to have come from. Every room but the
    first therefore has no coordinate at all -- the origin is taken and
    `coords.place` guards against a double-placement -- and the first has the
    origin, which is where it belongs. The `forget` is for the third case: a
    document whose first room is not at the origin, which nothing writes and a
    hand-edited file may say.
    """
    from world import coords

    if at is None:
        coords.forget(root, room)
        try:
            room.attributes.remove("coord")
        except AttributeError:
            pass
        return
    wanted = (int(at[0]), int(at[1]), int(at[2]))
    if coords.get_coord(room) not in (None, wanted):
        coords.forget(root, room)
    coords.place(root, room, wanted)


def _write_room(room, record):
    """Everything about a room that is not its existence."""
    room.key = str(record.get("title") or room.key)
    room.db.room_title = str(record.get("title") or room.key)
    room.db.desc = str(record.get("description") or "")
    room.db.room_type = str(record.get("type") or "")
    room.db.room_category = str(record.get("category") or "")
    room.db.zone = str(record.get("zone") or "")
    room.db.kinds = [str(kind) for kind in record.get("kinds") or []]
    if record.get("states"):
        room.db.states = sorted({str(word).lower()
                                 for word in record["states"]})
    if record.get("trait_bonuses"):
        room.db.trait_bonuses = dict(record["trait_bonuses"])
        room.db.bonus_when = str(record.get("bonus_when") or "present")
    _write_choices(room, record)
    _write_styles(room, record)


def _write_choices(obj, record):
    """
    What this thing's word lists already chose, put back -- and nothing more.

    The seed `token_lists.choose` uses includes the world's dbref, so a
    re-settled description would choose differently on a new server: the same
    room would smell of tar instead of brine. Carrying the choices is what
    makes "the world as it stands" true of a world's prose.

    Written even when it is empty, which is the half that is easy to miss.
    `clothing.create` settles a thing's text on the way past, so a thing whose
    description had a token and whose choices nobody had made yet would arrive
    with a choice the world it came from had not made. An import puts back
    what the document says and never anything else; the choice is made the
    first time somebody looks, exactly as it would have been at home.
    """
    from world import token_lists

    setattr(obj.db, token_lists.CHOICES, dict(record.get("choices") or {}))


def _write_styles(obj, record):
    """How this thing is in each of its conditions."""
    from world import verbs

    styles = record.get("styles") or {}
    if not styles:
        return
    kept = {str(slug): str(text)[:verbs.STYLE_MAXLENGTH]
            for slug, text in styles.items() if text}
    if kept:
        setattr(obj.db, verbs.STYLES_ATTR, kept)


def _build_ways(ways, names):
    """
    Every way, in both directions, exactly as the document says.

    Nothing is inferred and no back-exit is added: `_create_room` makes one
    for a room it is building from somewhere, and an import builds every room
    from nowhere. Both halves of every door are in the document, because
    `_ways` wrote both.
    """
    from typeclasses.exits import AIExit
    from world import worldgen

    for record in ways:
        here = names.object(record.get("from"))
        if here is None:
            continue
        pending = bool(record.get("pending"))
        there = names.object(record.get("to")) if not pending else None
        if not pending and there is None:
            continue
        way = worldgen._make_exit(
            AIExit, str(record.get("name") or "out"), here, there,
            pending=pending, hint=str(record.get("hint") or ""))
        for alias in record.get("aliases") or []:
            way.aliases.add(str(alias))


def _build_people(root, people, names):
    """
    Everybody who lives here, written the way the hand-built form writes them.

    Before the things, because a thing may be in somebody's hands.
    """
    from evennia import create_object
    from world import kinds, traits

    for record in people:
        room = names.object(record.get("at"))
        if room is None:
            continue
        npc = create_object("typeclasses.npcs.NPC",
                            key=str(record.get("name") or "Somebody"),
                            location=room)
        names.put(str(record.get("id") or ""), npc)
        npc.db.desc = str(record.get("description") or "")
        npc.db.is_npc = True
        npc.db.world_root = root
        npc.db.world_description = root.db.world_description or ""
        if record.get("manner"):
            npc.db.manner = str(record["manner"])
        if record.get("pronouns"):
            npc.db.pronoun_set = str(record["pronouns"])
        kinds.ensure_person(npc)
        if record.get("kinds"):
            npc.db.kinds = [str(kind) for kind in record["kinds"]]
        for entry in record.get("traits") or []:
            slug = str(entry.get("trait") or "")
            if not slug:
                continue
            traits.ensure(npc, slug, world_root=root)
            traits.adjust(npc, slug, set_to=entry.get("value"),
                          world_root=root, announce=False)
        if record.get("states"):
            npc.db.states = sorted({str(word).lower()
                                    for word in record["states"]})
        if record.get("goal"):
            npc.db.goal = list(record["goal"])
        _write_choices(npc, record)
        _write_styles(npc, record)

    # Following is a second pass: somebody may follow somebody made later.
    for record in people:
        npc = names.object(record.get("id"))
        leader = names.object(record.get("following"))
        if npc is not None and leader is not None:
            npc.db.following = leader


def _build_things(root, things, names):
    """
    Everything in the world, each through `clothing.create`.

    In dependency order, because a coin in a chest cannot be made before the
    chest. A thing whose holder never arrives is left out rather than dropped
    on the floor: `problems` has already refused a document where that could
    happen, so reaching it means the document changed underneath us.
    """
    from world import clothing

    waiting = {str(record.get("id") or ""): record for record in things}
    order = _in_dependency_order(things)
    for made in order:
        record = waiting[made]
        where = names.object(record.get("at"))
        if where is None:
            logger.log_info(f"exchange: {made!r} had nowhere to go")
            continue
        spec = {
            "name": str(record.get("name") or made),
            "description": str(record.get("description") or ""),
            "kind": str(record.get("kind") or ""),
            "kinds": [str(kind) for kind in record.get("kinds") or []],
            "qualifiers": [str(word) for word in record.get("qualifiers") or []],
            "affordances": dict(record.get("affordances") or {}),
            "states": [str(word) for word in record.get("states") or []],
            "takeable": bool(record.get("takeable", True)),
            "clothing_type": str(record.get("clothing_type") or ""),
            "trait_bonuses": dict(record.get("trait_bonuses") or {}),
            "bonus_when": str(record.get("bonus_when") or ""),
            "bonus_while": str(record.get("bonus_while") or ""),
        }
        styles = record.get("styles") or {}
        worn = clothing.WORN in spec["states"] and _is_person(where)
        obj = clothing.create(spec, location=where,
                              worn_on=where if worn else None)
        if obj is None:
            logger.log_info(f"exchange: {made!r} could not be made")
            continue
        names.put(made, obj)
        # After creation, and overriding what it worked out. `clothing.create`
        # reads a thing's affordances through its kind, so a coat made in a
        # world that has since decided coats can be picked up comes out
        # affording more than the coat in the document did. The document is
        # the world as it stands, and this is the line that means it: what was
        # written down is what is put back.
        _write_affordances(obj, record)
        _write_choices(obj, record)
        _write_styles(obj, record)
        owner = record.get("owner") or {}
        if owner:
            _write_owner(obj, owner, names)


def _write_affordances(obj, record):
    """
    What this thing itself affords, as the document has it.

    Through `affordances.normalise`, so a hand-edited document saying
    `["get", "not burnable"]` is read the way every other declaration is and a
    document saying nonsense writes nonsense nowhere.
    """
    from world import affordances

    declared = record.get("affordances")
    if declared is not None:
        obj.db.affordances = affordances.normalise(declared)


def _in_dependency_order(things):
    """
    The ids of `things`, holders before what they hold.

    A thing's `at` may name another thing. Anything in a cycle -- which
    nothing makes and a hand-edited document could -- comes last, in the order
    it was written, so a broken document still builds every thing it names.
    """
    records = {str(record.get("id") or ""): record for record in things}
    order, seen = [], set()

    def place(made, chain):
        if made in seen or made not in records:
            return
        if made in chain:
            return
        holder = str(records[made].get("at") or "")
        if holder in records:
            place(holder, chain | {made})
        if made not in seen:
            seen.add(made)
            order.append(made)

    for made in records:
        place(made, frozenset())
    return order


def _write_owner(obj, owner, names):
    """
    Who owns this, when they came with it.

    The record carries a name and, where the owner is somebody in this world,
    a local id. An owner who is not here -- a player character, who is not
    part of a world -- leaves a record with a name and no dbref, which is a
    thing somebody who is gone once owned. `ownership.orphaned` already knows
    that shape, and keeps the distinction from never-owned deliberately.
    """
    from world import ownership

    who = names.object(owner.get("of"))
    if who is not None:
        ownership.set_owner(obj, who, cascade=False)
        return
    name = str(owner.get("name") or "")
    if name:
        setattr(obj.db, ownership.ATTR, {"id": 0, "name": name, "since": 0})


def _place_things(things, names):
    """
    What is in, on, under or behind what. After everything exists.

    Separate from making them because a thing may be beside one made later --
    a coin under a rug is in the room and points at the rug -- and because
    `relations.place` is the one door placement comes through, whoever is
    doing the placing. A thing already inside its host comes through it too:
    the move is a no-op and the preposition is the point, since "on" and "in"
    are the same containment with two different words for it.
    """
    from world import relations

    for record in things:
        obj = names.object(record.get("id"))
        relation = record.get("relation") or {}
        host = names.object(relation.get("to"))
        if obj is None or host is None:
            continue
        try:
            relations.place(obj, host, str(relation.get("how") or "in"))
        except Exception:
            logger.log_info(
                f"exchange: {record.get('id')!r} would not go "
                f"{relation.get('how')} {relation.get('to')}")


def _build_errands(root, errands, names):
    """Every errand the world holds, with its givers found again."""
    from world import quests

    for record in errands:
        spec = dict(record)
        spec["id"] = str(spec.pop("key", "") or "")
        givers = []
        for giver in spec.get("givers") or []:
            npc = names.object(giver.get("npc"))
            if npc is not None:
                givers.append(dict(giver, npc=npc.id))
        spec["givers"] = givers
        quests.save_spec(root, spec)


def _build_rules(root, rules, names):
    """
    The world's own rules, last, because one may be about one lamp.

    Through `rulebooks.add`, which cleans the scope, normalises every
    condition and holds each to its caps -- the same door a model's rule and a
    player's rule come through. A rule is never written straight into the
    register here.
    """
    from world import rulebooks

    for record in rules:
        rule = dict(record)
        scope = dict(rule.get("scope") or {})
        for key in (rulebooks.OBJECT, rulebooks.ROOM):
            if key not in scope:
                continue
            found = names.object(scope[key])
            if found is None:
                break
            scope[key] = found.id
        else:
            rule["scope"] = scope
            rulebooks.add(root, rule)
            continue
        logger.log_info(f"exchange: {rule.get('name')!r} is about something "
                        f"this document does not contain and was not filed")


def _build_learned(root, learned):
    """What the world had already worked out, put back as it was."""
    for name in LEARNED:
        if name in learned and learned[name] is not None:
            setattr(root.db, name, learned[name])


# ---------------------------------------------------------------------------
# The restore point
# ---------------------------------------------------------------------------

def remember(root, doc):
    """
    Make this document what `reset world` comes back to.

    Set by an import and by an export, so exporting a world is also saving the
    state to return to. The document itself rather than a path to one: a path
    can be deleted, moved, or replaced with somebody else's world, and a reset
    that silently rebuilt a different world would be the worst bug this
    feature could have.
    """
    if root is not None:
        setattr(root.db, RESTORE_ATTR, doc)


def restore_point(root):
    """The document this world comes back to, or None."""
    if root is None:
        return None
    stored = getattr(root.db, RESTORE_ATTR, None)
    return plain(stored) if stored else None


def forget_restore(root):
    """Drop the restore point, so a reset generates from the setup again."""
    if root is not None:
        try:
            root.attributes.remove(RESTORE_ATTR)
        except AttributeError:
            pass


# ---------------------------------------------------------------------------
# The shared folder
# ---------------------------------------------------------------------------
#
# `WORLD_DIRS` is `RULESET_DIRS`' arrangement exactly: a list of directories,
# the first written to and all of them read. A file goes there because
# somebody with access to the machine put it there, or because a player
# exported a world -- and in the second case the name comes from the world,
# never from the player. `slug()` is the whole of the path-traversal defence
# and it is worth being able to say that in one sentence.

def directories():
    """Every directory world documents are read from, the writable one first."""
    try:
        from django.conf import settings

        found = getattr(settings, SETTING, None) or []
    except Exception:
        found = []
    if isinstance(found, str):
        found = [found]
    return [str(path) for path in found]


def folder():
    """Where an export is written, made if it is not there. "" when unset."""
    found = directories()
    if not found:
        return ""
    try:
        os.makedirs(found[0], exist_ok=True)
    except OSError as exc:
        logger.log_err(f"exchange: {found[0]} cannot be written to: {exc}")
        return ""
    return found[0]


def _path_of(directory, name):
    """The file `name` names inside `directory`, and never outside it."""
    return os.path.join(directory, f"{slug(name, 'world')}.json")


def available():
    """
    Every document in the shared folder, as {name: heading}.

    Only the heading is read -- the title, the room count, what it requires --
    because a listing of thirty worlds must not parse thirty documents whole.
    A file that is not a world document at all is left out with a log rather
    than shown as a broken entry: the folder may hold anything somebody put
    there.
    """
    found = {}
    for directory in directories():
        if not os.path.isdir(directory):
            continue
        for entry in sorted(os.listdir(directory)):
            if not entry.endswith(".json"):
                continue
            path = os.path.join(directory, entry)
            heading = _heading(path)
            if heading is not None:
                found[entry[:-len(".json")]] = heading
    return found


def _heading(path):
    """What a listing shows for one file, or None when it is not one of ours."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if size > MOST_BYTES:
        logger.log_info(f"exchange: {path} is {size} bytes, past "
                        f"{MOST_BYTES}, and was not listed")
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.log_info(f"exchange: {path} could not be read: {exc}")
        return None
    if not hasattr(doc, "keys") or str(doc.get("kind") or "") != KIND:
        return None
    from world import rulesets

    wanted = ((doc.get("requires") or {}).get("rulesets") or {})
    here = rulesets.available()
    return {
        "path": path,
        "title": str(doc.get("title") or ""),
        "rooms": int(doc.get("rooms") or 0),
        "exported": str(doc.get("exported") or ""),
        "requires": sorted(str(name) for name in wanted),
        "missing": sorted(str(name) for name in wanted if name not in here),
        "bytes": size,
    }


def read(name):
    """
    One document off the disk by its name in the folder.

    Raises `Refused` rather than answering None, because every caller wants
    the reason: a file too big, a file that is not JSON, and a file that is
    not a world are three different things to be told.
    """
    for directory in directories():
        path = _path_of(directory, name)
        if not os.path.isfile(path):
            continue
        try:
            size = os.path.getsize(path)
        except OSError as exc:
            raise Refused([f"{name} cannot be read: {exc}"])
        if size > MOST_BYTES:
            # Before it is read, because a document is parsed whole into
            # memory and the size is the one thing knowable without doing so.
            raise Refused([f"{name} is {size // 1024} KiB, and "
                           f"{MOST_BYTES // 1024} KiB is the most a world may "
                           f"be"])
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError) as exc:
            raise Refused([f"{name} is not a document this can read: {exc}"])
    raise Refused([f"there is no world called {name!r} in the shared folder"])


def write(doc, name=""):
    """
    Write a document to the shared folder. Answers the name it went under.

    The name comes from the world's title and never from anything anybody
    typed, and a name already taken takes a number rather than overwriting:
    two players exporting "The School" have exported two worlds.
    """
    directory = folder()
    if not directory:
        raise Refused(["this server has nowhere to keep exported worlds; "
                       "WORLD_DIRS is not set"])
    wanted = slug(name or doc.get("title") or "world", "world")
    made, number = wanted, 1
    while os.path.exists(_path_of(directory, made)):
        number += 1
        made = f"{wanted[:LONGEST_ID - 3]}_{number}"
    path = _path_of(directory, made)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, indent=1, sort_keys=True)
            handle.write("\n")
    except OSError as exc:
        raise Refused([f"it could not be written: {exc}"])
    return made


def remove(name):
    """Take a document out of the folder. True when one went."""
    for directory in directories():
        path = _path_of(directory, name)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError as exc:
                raise Refused([f"{name} could not be removed: {exc}"])
            return True
    return False
