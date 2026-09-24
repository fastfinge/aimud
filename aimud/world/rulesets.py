"""
Which rules a world was built with, and who chose them.

`standard_rules.py` seeds a fixed list into every world there has ever been,
and the things it seeds are not all of one kind. "You must be able to reach
what you act on" is true of every world that could exist. `life_status`, with
`dead` and `prevents_acting`, is seeded into a world about a dinner party.
`clothing.VERBS` takes `wear` and `cover` before any rule is consulted, in a
world with no clothes in it. Every one of those is a decision about what sort
of game this is, made once for everybody.

A **ruleset** is that decision, named and chosen. It bundles everything one
idea needs -- the rules, the actions they are about, the kinds and states and
figures they mention -- and a world is built with the ones its creator picked.

**A ruleset is data, never code.** `docs/basic-principles.md` is explicit: no
player, character, model or rule writes Python, and Python arrives only by
somebody with access to the machine putting a file on it. A ruleset is lighter
than a plugin and must not become a way around that, so it is a validated JSON
document with no executable part. Everything a ruleset can say, a world could
have said for itself with `create rule`.

**Seeding, retiring and versioning are `standard_rules`' own, generalised.**
That module had already solved this for one ruleset: a version on the file, a
version on the world, the old edition's rules deleted by their `source` mark
and the new one seeded in, and -- the part that is easy to miss -- whatever the
world had decided with `rules suspend` carried across by name, so a new edition
does not quietly undo somebody's decision. All of that is here, once, for any
number of rulesets.

**Nothing is applied by halves.** A document that fails validation is logged
and skipped entire. A rule that names a kind, trait, state or action which
neither its own ruleset nor anything it requires declares is a rule that will
never gather -- which fails by doing nothing, the worst way there is -- so it
is refused at load rather than found later by nobody.
"""

import json
import os

from evennia.utils import logger

#: Where a world records what it holds: {name: version}.
ATTR = "rulesets"

#: What marks a rule as a ruleset's rather than a world's own. A world's own
#: rules are never touched by anything here.
SOURCE = "ruleset:"

#: The mark the default ruleset's rules carried before rulesets existed, and
#: still carry. Kept rather than renamed: every world in play holds rules
#: marked this way, `rules` lists them by it, and `standard_rules.is_standard`
#: is what several tests and the rules listing ask. A rename would have bought
#: tidiness and cost a migration on live worlds.
STANDARD = "standard"

#: The ruleset every world gets, and the one whose rules carry STANDARD.
DEFAULT = "default"

#: The sections a document may have, each the vocabulary one store keeps.
#: Every one is optional; a ruleset says only what it needs.
#:
#: Every one is also read by `_apply` or by `world.mechanics`, and a document
#: naming anything else is refused. That check is not tidiness: `affordances`
#: was in this list and read by nothing, so `"affordances": ["combine"]` sat
#: in a shipped ruleset doing precisely nothing, and the only symptom was a
#: soak world where combining refused everything. A section nobody reads is a
#: promise nobody keeps.
SECTIONS = ("actions", "verbs", "kinds", "attributes",
            "conditions", "rules", "mechanics")

#: What a document may have besides its sections.
HEADER = ("name", "title", "version", "means", "requires", "conflicts",
          "default", "path")

#: Where the rulesets that ship with the game live.
BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "rulesets")

#: The setting naming directories a server administrator keeps their own in.
#: A file there needs access to the machine to put it there, which is the bar
#: `basic-principles.md` sets for extending the game.
SETTING = "RULESET_DIRS"

#: Read once. A ruleset changes when somebody edits a file, which on a running
#: server means a reload, and a reload clears this with the module.
_LOADED = None


# ---------------------------------------------------------------------------
# Reading them off the disk
# ---------------------------------------------------------------------------

def directories():
    """Every directory rulesets are read from, the built-in one first."""
    found = [BUILTIN_DIR]
    try:
        from django.conf import settings

        extra = getattr(settings, SETTING, None) or []
    except Exception:
        extra = []
    if isinstance(extra, str):
        extra = [extra]
    found.extend(str(path) for path in extra)
    return found


def available(reload=False):
    """
    Every ruleset this server can offer, by name.

    A local ruleset whose name matches a built-in one replaces it entire --
    which is how a server runs its own idea of death without patching the
    game. Later directories win, so the built-in one is read first.

    In two passes, and it has to be. A document is checked for naming things
    nothing declares, and what a ruleset's `requires` declares is in another
    document -- so the second half of validation cannot run until every
    document is parsed. Read first, judge afterwards, and drop what fails.
    """
    global _LOADED
    if _LOADED is not None and not reload:
        return _LOADED
    found = {}
    for directory in directories():
        if not os.path.isdir(directory):
            continue
        for entry in sorted(os.listdir(directory)):
            if not entry.endswith(".json"):
                continue
            path = os.path.join(directory, entry)
            doc = _read(path)
            if doc is None:
                continue
            name = doc.get("name") or ""
            was = found.get(name)
            if was is not None and was.get("path") != path:
                logger.log_info(
                    f"rulesets: {name!r} from {path} replaces "
                    f"{was.get('path')}")
            found[name] = doc

    for name, doc in list(found.items()):
        wrong = _undeclared(doc, found)
        if wrong:
            _refuse(doc, wrong)
            del found[name]
    _LOADED = found
    return found


def _refuse(doc, wrong):
    """
    Say why a document was not loaded. Skipped entire rather than in part: half
    a ruleset is a world whose rules mention states nothing registers, which is
    worse than a world without the ruleset at all.
    """
    logger.log_err(
        f"rulesets: {doc.get('path')} was not loaded: {'; '.join(wrong)}")


def _read(path):
    """One document off the disk, structurally checked, or None with a log."""
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.log_err(f"rulesets: could not read {path}: {exc}")
        return None
    if not hasattr(doc, "keys"):
        logger.log_err(f"rulesets: {path} is not a ruleset document")
        return None
    doc = dict(doc)
    doc["path"] = path
    wrong = problems(doc, known={})
    if wrong:
        _refuse(doc, wrong)
        return None
    return doc


def get(name):
    """One ruleset by name, or None."""
    return available().get(str(name or ""))


def defaults():
    """The rulesets a world gets when nobody has said otherwise."""
    return sorted(name for name, doc in available().items()
                  if doc.get("default"))


# ---------------------------------------------------------------------------
# Whether a document says anything this game can act on
# ---------------------------------------------------------------------------

def problems(doc, known=None):
    """
    What is wrong with this document, as short sentences; [] when nothing is.

    Held to the validators that already exist -- `rulebooks.add` cleans a
    scope, `actions.clean_roles` cleans roles, `conditions.normalise` refuses
    a condition too deep to store -- run here rather than at write time, and
    refusing the document rather than quietly repairing it.
    """
    from world import conditions, rulebooks

    wrong = []
    name = str(doc.get("name") or "").strip()
    if not name:
        wrong.append("it has no name")
    elif not name.replace("_", "").replace("-", "").isalnum():
        wrong.append(f"{name!r} is not a plain name")
    if not str(doc.get("means") or "").strip():
        wrong.append("it does not say what it is for")
    try:
        int(doc.get("version", 1))
    except (TypeError, ValueError):
        wrong.append("its version is not a number")

    for field in ("requires", "conflicts"):
        value = doc.get(field) or []
        if isinstance(value, str) or not hasattr(value, "__iter__"):
            wrong.append(f"{field} is not a list of names")

    for section in SECTIONS:
        value = doc.get(section)
        if value is None:
            continue
        if isinstance(value, str) or not hasattr(value, "__iter__"):
            wrong.append(f"{section} is not a list")

    unknown = sorted(set(doc) - set(SECTIONS) - set(HEADER))
    if unknown:
        wrong.append(
            f"nothing reads {', '.join(repr(name) for name in unknown)}; a "
            f"section nobody reads is a promise nobody keeps")

    for rule in doc.get("rules") or []:
        if not hasattr(rule, "keys"):
            wrong.append("a rule is not an object")
            continue
        if not str(rule.get("name") or "").strip():
            wrong.append("a rule has no name")
        phase = str(rule.get("phase") or "")
        if phase not in rulebooks.STORED_PHASES:
            wrong.append(f"a rule has no phase this game runs ({phase!r})")
        for field in ("when", "conditions"):
            for condition in rule.get(field) or []:
                if conditions.normalise(condition) is None:
                    wrong.append(
                        f"a condition in {rule.get('name')!r} is not one this "
                        f"game can test: {condition!r}")
        # A becomes rule's trigger is its `when`. `world.becoming` reads that
        # and nothing else, so one written with `conditions` instead is filed,
        # gathered, and then fires the moment anything at all happens to the
        # thing -- because it has no edge to wait for. Caught here because the
        # symptom is a rule that works in the wrong way rather than not at
        # all, which is the hardest sort to see. This is the mistake the
        # death ruleset was written with.
        if phase == rulebooks.BECOMES and rule.get("conditions"):
            wrong.append(
                f"{rule.get('name')!r} becomes true on a `when`, not on "
                f"`conditions`; `world.becoming` never reads those")

    # A ruleset names a mechanic; it never supplies one. Only what ships with
    # the game may be named, and a name that is not in the table is refused
    # here rather than silently doing nothing. See `world.mechanics`.
    from world import mechanics

    for named in doc.get("mechanics") or []:
        if not mechanics.known(named):
            wrong.append(f"there is no mechanic called {named!r}")

    wrong.extend(_undeclared(doc, known))
    return wrong


def _undeclared(doc, known=None):
    """
    Names a rule uses that nothing declares. See the module docstring.

    Only what this ruleset and its `requires` are responsible for. A rule may
    name a state or a figure a *world* invents -- that is most of what rules
    do -- so this asks only about the vocabulary the document itself is
    introducing, and lets anything it never mentions alone.
    """
    from world import conditions

    declared_traits = {str(entry.get("slug") or "")
                       for entry in doc.get("attributes") or []
                       if hasattr(entry, "keys")}
    declared_actions = {str(entry.get("action") or "")
                        for entry in doc.get("actions") or []
                        if hasattr(entry, "keys")}
    known = available() if known is None else known
    required = set(doc.get("requires") or [])
    for other in required:
        upstream = known.get(other)
        if upstream is None:
            continue
        declared_traits |= {str(e.get("slug") or "")
                            for e in upstream.get("attributes") or []
                            if hasattr(e, "keys")}
        declared_actions |= {str(e.get("action") or "")
                             for e in upstream.get("actions") or []
                             if hasattr(e, "keys")}

    wrong = []
    for rule in doc.get("rules") or []:
        if not hasattr(rule, "keys"):
            continue
        action = rule.get("action")
        # A rule about an action nobody declares is fine when the action is
        # one the world will learn for itself; it is wrong only when this
        # document is plainly the thing that should have declared it. So the
        # test is narrow on purpose: an action this ruleset names in a rule
        # AND lists in `verbs` without declaring.
        folded = {str(v) for v in doc.get("verbs") or []}
        if action and action in folded and action not in declared_actions:
            wrong.append(f"{rule.get('name')!r} is about {action!r}, which "
                         f"this ruleset folds but never declares")
        for field in ("when", "conditions"):
            for condition in rule.get(field) or []:
                for leaf, _optional in conditions.leaves(condition):
                    predicate, value = conditions.predicate_of(leaf)
                    if predicate != "trait":
                        continue
                    slug = str(value or "")
                    if slug and declared_traits and slug not in declared_traits:
                        wrong.append(
                            f"{rule.get('name')!r} asks about the figure "
                            f"{slug!r}, which this ruleset does not register")
    return wrong


# ---------------------------------------------------------------------------
# Which ones go together
# ---------------------------------------------------------------------------

def resolve(names):
    """
    (the rulesets to seed, in the order to seed them; what is wrong).

    `requires` is pulled in whether it was asked for or not -- a world that
    chose permadeath chose death, whatever the menu said -- and `conflicts` is
    refused rather than resolved, because two rulesets that say they cannot
    live together are two answers to one question and nothing here can pick.
    """
    wanted, wrong, seen = [], [], set()

    def walk(name, chain):
        if name in seen:
            return
        if name in chain:
            wrong.append(f"{name!r} requires itself")
            return
        doc = get(name)
        if doc is None:
            wrong.append(f"there is no ruleset called {name!r}")
            return
        for needed in doc.get("requires") or []:
            walk(str(needed), chain + [name])
        seen.add(name)
        wanted.append(name)

    for name in names or []:
        walk(str(name), [])

    for name in wanted:
        for against in (get(name) or {}).get("conflicts") or []:
            if str(against) in wanted:
                wrong.append(f"{name!r} and {against!r} cannot both be used")
    return wanted, wrong


# ---------------------------------------------------------------------------
# What a world holds
# ---------------------------------------------------------------------------

def held(world_root):
    """{name: version} for what this world has been given."""
    if world_root is None:
        return {}
    from evennia.utils.dbserialize import deserialize

    return dict(deserialize(getattr(world_root.db, ATTR, None)) or {})


def chosen(world_root):
    """The names this world holds, sorted."""
    return sorted(held(world_root))


def seed(world_root, names=None):
    """
    Give a world the rulesets it was built with. Cheap to call, safe to repeat.

    Returns what was added. Nothing after the first time, and everything again
    the first time after a ruleset is corrected -- which is what `version` is
    for, and is `standard_rules`' own argument: a world holding last week's
    copy of the engine's rules is holding a bug rather than a decision, while
    a world's *own* rules are nobody's business but its.
    """
    if world_root is None:
        return []
    wanted = list(names) if names is not None else chosen(world_root)
    if not wanted:
        wanted = defaults()
    ordered, wrong = resolve(wanted)
    for complaint in wrong:
        logger.log_err(f"rulesets: {world_root.key}: {complaint}")

    holding = held(world_root)
    added = []
    for name in ordered:
        doc = get(name)
        version = int(doc.get("version", 1))
        if holding.get(name) == version:
            continue
        # A world's own decisions are carried across an *edition* -- a new
        # version of a ruleset it already holds -- and not across a fresh
        # install. Adding a ruleset a world does not hold lands it at the
        # document's defaults, which is what `reset world` wants and what
        # putting back one that was taken away has to mean: `forget` unlists
        # everything it seeded, and reading that back as a decision would
        # bring the ruleset back switched off.
        decided = _decisions(world_root, name) if name in holding else {}
        _retire(world_root, name)
        added.extend(_apply(world_root, doc, decided))
        holding[name] = version
    setattr(world_root.db, ATTR, holding)
    return added


def _source_of(doc):
    """What a ruleset's rules are marked with."""
    name = str(doc.get("name") or "")
    return STANDARD if name == DEFAULT else f"{SOURCE}{name}"


def from_ruleset(rule, name=""):
    """
    Whether a rule came with the world rather than being learned in it.

    With a name, whether it came from that one. STANDARD is answered for
    `default` because that is the mark its rules have always carried.
    """
    try:
        source = str(rule.get("source") or "")
    except AttributeError:
        return False
    if not name:
        return source == STANDARD or source.startswith(SOURCE)
    return source == (STANDARD if name == DEFAULT else f"{SOURCE}{name}")


def _decisions(world_root, name):
    """
    {rule name: listed} for what this world holds of this ruleset now.

    `rules suspend` and `rules restore` are a world's own decisions about the
    engine's rules, and a new edition is not a reason to undo them. Matched by
    name, which is what a rule is to anybody reading `rules`; a rule renamed
    between editions is a new rule and gets its new default.
    """
    from world import rulebooks

    return {str(rule.get("name") or ""): bool(rule.get("listed", True))
            for rule in rulebooks.all_rules(world_root)
            if from_ruleset(rule, name)}


def _retire(world_root, name):
    """
    Drop what the last edition of this ruleset seeded, so the new one can land.

    Deleted rather than unlisted, because an unlisted rule is a proposal
    somebody may accept and these are not proposals -- they are a superseded
    copy of what the file says. Nothing but this ruleset's own mark is
    touched: what a world wrote for itself is its own, and so is what another
    ruleset seeded.

    Declarations go with them, and have to. `actions.declare` is
    first-answer-wins on purpose -- an arity is what every rule about an
    action was written against -- so a world that guessed at an action before
    a ruleset declared it would keep the guess for ever.
    """
    from evennia.utils.dbserialize import deserialize

    from world import actions, rulebooks, verbs

    doc = get(name) or {}
    store = dict(deserialize(getattr(world_root.db, rulebooks.ATTR, None))
                 or {})
    keeping = {rule_id: rule for rule_id, rule in store.items()
               if not from_ruleset(rule, name)}
    if len(keeping) != len(store):
        setattr(world_root.db, rulebooks.ATTR, keeping)

    declared = dict(getattr(world_root.db, actions.ATTR, None) or {})
    ours = {verbs.canonical_verb(str(entry.get("action") or ""))
            for entry in doc.get("actions") or [] if hasattr(entry, "keys")}
    left = {key: entry for key, entry in declared.items() if key not in ours}
    if len(left) != len(declared):
        setattr(world_root.db, actions.ATTR, left)


def forget(world_root, name):
    """
    Take a ruleset out of a world, leaving what was built on it alone.

    Its rules are **unlisted rather than deleted**, which is the opposite of
    what `_retire` does and for the opposite reason. A retired rule is a stale
    copy of a file nobody wrote by hand. A rule being taken away is one a
    world may have built on -- written rules in front of, given things
    affordances for, sent characters after -- and deleting it would take that
    work with it silently. Unlisted, it stops applying and stays readable, and
    putting the ruleset back puts it back.
    """
    from evennia.utils.dbserialize import deserialize

    from world import rulebooks

    if world_root is None:
        return 0
    store = dict(deserialize(getattr(world_root.db, rulebooks.ATTR, None))
                 or {})
    changed = 0
    for rule_id, rule in store.items():
        if from_ruleset(rule, name) and rule.get("listed", True):
            store[rule_id] = dict(rule, listed=False)
            changed += 1
    if changed:
        setattr(world_root.db, rulebooks.ATTR, store)
    holding = held(world_root)
    holding.pop(name, None)
    setattr(world_root.db, ATTR, holding)
    return changed


# ---------------------------------------------------------------------------
# Applying one
# ---------------------------------------------------------------------------

def _apply(world_root, doc, decided):
    """Put one ruleset's vocabulary and rules into a world."""
    from world import actions, kinds, rulebooks, traits, verbs

    source = _source_of(doc)

    for entry in doc.get("attributes") or []:
        if not hasattr(entry, "keys"):
            continue
        entry = dict(entry)
        traits.register(world_root, entry.pop("slug", ""),
                        name=entry.pop("name", ""),
                        means=entry.pop("means", ""),
                        trait_type=entry.pop("trait_type", "counter"),
                        **entry)

    for entry in doc.get("conditions") or []:
        if not hasattr(entry, "keys"):
            continue
        entry = dict(entry)
        members = entry.pop("states", None) or []
        group = verbs.register_group(world_root, entry.pop("group", ""),
                                     **entry)
        # And the states that belong to it, by name.
        #
        # `apply_states` registers a slug it has never seen on the way in,
        # which is the right default and the wrong thing to rely on here: with
        # nobody having said which group `worn` is in, `register_state` folds
        # it onto whatever it finds similar, and may hand back a different
        # slug than the one asked for. A ruleset that means one particular
        # word says so, once, when it is seeded.
        for slug in members:
            verbs.register_state(world_root, str(slug), group=group)

    for entry in doc.get("kinds") or []:
        if not hasattr(entry, "keys"):
            continue
        kinds.remember(world_root, str(entry.get("kind") or ""),
                       entry.get("affordances") or {},
                       accepts=entry.get("accepts") or (),
                       under=str(entry.get("under") or ""))

    for entry in doc.get("verbs") or []:
        _fold(world_root, entry)

    for entry in doc.get("actions") or []:
        if not hasattr(entry, "keys"):
            continue
        actions.declare(world_root, str(entry.get("action") or ""),
                        applies_to=entry.get("applies_to") or (),
                        means=str(entry.get("means") or ""),
                        despite=entry.get("despite") or ())

    added = []
    for rule in doc.get("rules") or []:
        if not hasattr(rule, "keys"):
            continue
        stored = dict(rule, source=source,
                      listed=decided.get(str(rule.get("name") or ""),
                                         rule.get("listed", True)))
        added.append(rulebooks.add(world_root, stored))
    return [rule for rule in added if rule]


#: Where a world keeps the verb spellings its rulesets fold.
VERBS_ATTR = "verb_synonyms"


def _fold(world_root, entry):
    """
    Teach this world that one spelling means another.

    World-scoped rather than global, which is the whole point: a server runs
    many worlds and only some of them are about crafting, so `forge` meaning
    `make` is a fact about a world and not about the game. `VERB_SYNONYMS` in
    `world.verbs` stays what it is -- English that is true everywhere.
    """
    if not hasattr(entry, "keys"):
        return
    word = str(entry.get("word") or "").strip().lower()
    means = str(entry.get("means") or "").strip().lower()
    if not word or not means or word == means:
        return
    stored = dict(getattr(world_root.db, VERBS_ATTR, None) or {})
    if stored.get(word) == means:
        return
    stored[word] = means
    setattr(world_root.db, VERBS_ATTR, stored)


def synonyms(world_root):
    """The spellings this world's rulesets fold, as {word: canonical}."""
    if world_root is None:
        return {}
    return dict(getattr(world_root.db, VERBS_ATTR, None) or {})


def said(name):
    """One ruleset as a line somebody should read."""
    doc = get(name)
    if doc is None:
        return f"{name} -- no such ruleset"
    needs = ", ".join(doc.get("requires") or [])
    tail = f" (needs {needs})" if needs else ""
    return f"|w{doc.get('title') or name}|n -- {doc.get('means')}{tail}"
