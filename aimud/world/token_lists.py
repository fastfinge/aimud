"""
Lists of words a world keeps, and what was chosen from them.

A description may say "This is a {color} ball." when the world keeps a list
called `color`. What that comes to is chosen once, kept, and read back every
time anybody looks -- so the ball is the same colour on every look, for every
viewer, and a model reading the description sees a colour rather than a
brace. See docs/tokens-and-phrases.md §5.

**A choice is a fact wherever the world has a word for it.** A list may name
a state group and give its entries states: picking "blue" then puts the ball
in state `blue`, and the text reads the state back rather than a remembered
word. So a rule can require a blue ball, an NPC can want one, and a rule that
paints it red changes what a look says with nothing else written. Caching the
sentence instead would lie the moment anything changed, which is the failure
`objects.get_display_desc` already documents for a bottle that has been drunk.

An entry with no facts is decoration, and is still kept -- in
`db.token_choices` on whatever holds its scope -- so it stays the same and can
be promoted to a fact later.

**Scope is where a choice lives:**

    render   nowhere: chosen again every time
    object   the thing the text belongs to        (the default)
    room     the room it is in
    world    the world root
    viewer   the thing, once per person looking at it

**One choice per list per holder, unless labelled.** "a {color} ball with
{color} stripes" is one colour -- a group forces that, and decoration follows
the same rule so the two never disagree -- and `$pick(color, as=stripes)` is a
second. A reference inside an entry is a new slot nested under the one being
expanded, so a list may refer to itself, and only the outermost slot writes
facts.

**Growth goes through one door**, the way every other register's does:
`register_many` refuses an incomplete list, a reserved name, a word another
register may not share, and -- the check a context-free grammar has always
needed -- a list that can never finish expanding.
"""

import hashlib
import random
import re

from evennia.utils import logger

#: Where a world keeps its lists.
ATTR = "token_lists"

#: Where a holder keeps what was chosen for it.
CHOICES = "token_choices"

#: Where a choice may live. See the module docstring.
SCOPES = ("render", "object", "room", "world", "viewer")

DEFAULT_SCOPE = "object"

#: Scopes whose choices may become facts. A choice made once per viewer
#: cannot put one thing into two states, and one made on every render has
#: nowhere to stay.
FACT_SCOPES = frozenset(("object", "room", "world"))

#: How deep a list may expand into lists. Past this only entries that name no
#: other list are chosen from, so a list that refers to itself still finishes.
MAX_DEPTH = 8

#: Most entries a list keeps. Enough for a real list and short enough that a
#: model cannot pour a thesaurus into one.
MOST_ENTRIES = 60

#: Longest an entry may be.
LONGEST_ENTRY = 300

#: Most entries shown when a list is spelled out.
ENTRIES_SHOWN = 6

_NAME = re.compile(r"[a-z_][a-z0-9_]*")


def _slug(name):
    return re.sub(r"[^a-z0-9_]", "", str(name or "").lower().strip())


def vocabulary(world_root):
    """{name: list} for this world."""
    if world_root is None:
        return {}
    try:
        return {name: dict(entry)
                for name, entry in (world_root.db.token_lists or {}).items()}
    except (AttributeError, TypeError, ValueError):
        return {}


def get(world_root, name):
    return vocabulary(world_root).get(_slug(name))


# ---------------------------------------------------------------------------
# Reading a declaration
# ---------------------------------------------------------------------------

def clean(declared):
    """
    (list, complaint) for a list somebody wrote down, before the world is
    consulted.

    An entry may be a plain string -- what a player types and what a model
    writes for decoration -- or {"text", "weight", "sets"}. A list with no
    `means` is refused: it is what `help` shows and what the next prompt
    reads, and a list nobody can explain is one nobody can reuse correctly.
    """
    try:
        given = dict(declared or {})
    except (TypeError, ValueError):
        return None, "not a list at all"

    means = str(given.get("means") or "").strip()
    if not means:
        return None, "no sentence saying what the list is for"

    scope = str(given.get("scope") or DEFAULT_SCOPE).strip().lower()
    if scope not in SCOPES:
        scope = DEFAULT_SCOPE

    entries = []
    for raw in list(given.get("entries") or [])[:MOST_ENTRIES]:
        if isinstance(raw, str):
            raw = {"text": raw}
        try:
            text = str(raw.get("text") or "").strip()[:LONGEST_ENTRY]
        except AttributeError:
            continue
        if not text:
            continue
        try:
            weight = min(max(float(raw.get("weight") or 1), 0.0), 100.0)
        except (TypeError, ValueError):
            weight = 1.0
        if weight <= 0:
            continue
        sets = raw.get("sets") or {}
        try:
            states = [_slug(s) for s in (sets.get("states") or []) if _slug(s)]
            traits = {}
            for slug, value in dict(sets.get("traits") or {}).items():
                traits[_slug(slug)] = float(value)
        except (AttributeError, TypeError, ValueError):
            return None, f"entry {text!r} sets something that is not a fact"
        entry = {"text": text, "weight": weight}
        if states or traits:
            entry["sets"] = {"states": states, "traits": traits}
        entries.append(entry)
    if not entries:
        return None, "no entries"

    return {
        "means": means,
        "scope": scope,
        "group": _slug(given.get("group")),
        "for": sorted({str(k).strip().lower()
                       for k in (given.get("for") or []) if str(k).strip()}),
        "fallback": str(given.get("fallback") or "").strip()[:LONGEST_ENTRY],
        "entries": entries,
    }, ""


def references(text):
    """Every name a piece of text asks to have filled: slots, and `$pick`s."""
    from world import tokens

    found = set()

    def walk(nodes):
        for node in nodes:
            if isinstance(node, tokens.Slot):
                found.add(node.name)
            elif isinstance(node, tokens.Call):
                if node.name == "pick" and node.args:
                    first = "".join(n.text for n in node.args[0]
                                    if isinstance(n, tokens.Text)).strip()
                    if first:
                        found.add(first)
                for arg in node.args:
                    walk(arg)
                for _key, value in node.kwargs:
                    walk(value)

    walk(tokens.parse(text))
    return found


def productive(lists):
    """
    The names of every list that can finish expanding.

    The standard check for a context-free grammar, as a fixed point: a list
    can finish if one of its entries names only lists that can. A list whose
    every entry names itself, or names only lists that never finish, is
    exactly the one that loops.
    """
    good, changed = set(), True
    names = set(lists)
    while changed:
        changed = False
        for name, entry in lists.items():
            if name in good:
                continue
            for item in entry.get("entries") or []:
                if references(item.get("text", "")) & names <= good:
                    good.add(name)
                    changed = True
                    break
    return good


# ---------------------------------------------------------------------------
# The one door
# ---------------------------------------------------------------------------

def _reserved(name):
    from world import tokens

    return (name in tokens.RESERVED_SLOTS or name in tokens.RESERVED_CALLS
            or name in tokens._PROVIDED_SLOTS or name in tokens._PROVIDED_CALLS)


def _known_name(name, world_root):
    """Whether a reference will come to something other than itself."""
    from world import tokens

    return (name in tokens.RESERVED_SLOTS or name in tokens._PROVIDED_SLOTS
            or name in vocabulary(world_root))


def _fold(world_root, name):
    """The list already kept under this name or its singular, or ""."""
    from world import lexicon

    kept = vocabulary(world_root)
    if name in kept:
        return name
    single = lexicon.lemma(name.replace("_", " "), "n").replace(" ", "_")
    for existing in kept:
        if lexicon.lemma(existing.replace("_", " "), "n").replace(" ", "_") == single:
            return existing
    return ""


def _settle_facts(world_root, name, entry):
    """
    Make the facts a list names real, or say why they cannot be.

    A list with a group is declaring its states: an unknown one is registered
    into that group, as a state declared anywhere else would be. A list
    without a group may only name states the world already keeps. A trait must
    already be kept either way -- a trait has a type and bounds, and a word in
    a list says neither.
    """
    from world import traits, verbs

    group = entry.get("group") or ""
    if group:
        group = verbs.register_group(world_root, group, exclusive=True)
        entry["group"] = group

    for item in entry["entries"]:
        sets = item.get("sets")
        if not sets:
            continue
        settled = []
        for slug in sets.get("states") or []:
            known = slug in verbs.vocabulary(world_root) or verbs.group_of(
                world_root, slug)
            if not known and not group:
                return f"{slug!r} is not a state this world keeps"
            if known:
                if group and verbs.group_of(world_root, slug) not in (group, None):
                    return (f"{slug!r} belongs to the group "
                            f"{verbs.group_of(world_root, slug)!r}, not {group!r}")
                settled.append(slug)
                continue
            slug = verbs.register_state(
                world_root, slug, means=f"{entry['means']}: {item['text']}",
                group=group)
            if not slug:
                return f"{item['text']!r} names a state that could not be kept"
            settled.append(slug)
        sets["states"] = settled
        for slug in sets.get("traits") or {}:
            if not traits.known(world_root, slug):
                return f"{slug!r} is not a trait this world keeps"
    return ""


def complaints(world_root, declared=(), texts=()):
    """
    What `register_many` would refuse in these declarations, and the slots in
    `texts` nothing would answer, as short phrases; [] when there is nothing.

    For a finish tool, so a list is sent back rather than refused and logged
    after the answer was taken. The same checks, over the same candidate set:
    everything this world keeps plus everything declared here, so declared
    lists may name each other. A list already kept under another spelling is
    not a complaint here -- `vocabulary.near_duplicates` says that.
    """
    said, batch = [], {}
    for given in list(declared or []):
        if not isinstance(given, dict):
            said.append("a word list that was not an object")
            continue
        asked = _slug(given.get("name"))
        if not asked or not _NAME.fullmatch(asked):
            said.append(f"a word list needs a name of letters, digits and "
                        f"underscores, not {given.get('name')!r}")
            continue
        if _reserved(asked):
            said.append(f"{{{asked}}} is a name the game itself answers; "
                        f"choose another")
            continue
        if world_root is not None and _fold(world_root, asked):
            continue
        entry, complaint = clean(given)
        if complaint:
            said.append(f"the word list {{{asked}}} cannot be kept: {complaint}")
            continue
        batch[asked] = entry

    kept = vocabulary(world_root) if world_root is not None else {}
    candidate = {**kept, **batch}
    good = productive(candidate)
    for name, entry in batch.items():
        unknown = sorted(
            ref for item in entry["entries"] for ref in references(item["text"])
            if ref not in candidate and not _known_name(ref, world_root))
        if name not in good:
            said.append(f"the word list {{{name}}} can never finish expanding")
        elif unknown:
            said.append(f"the word list {{{name}}} names "
                        + ", ".join(f"{{{ref}}}" for ref in unknown)
                        + ", which nothing answers")

    if world_root is not None:
        unknown = sorted({ref for text in texts or ()
                          for ref in references(str(text or ""))
                          if ref not in candidate
                          and not _known_name(ref, world_root)})
        if unknown:
            said.append("the description asks for word lists this world does "
                        "not keep: " + ", ".join(f"{{{ref}}}" for ref in unknown)
                        + "; declare them in new_token_lists or write the "
                          "words out")
    return said


def register_many(world_root, declared):
    """
    Put lists in the world's register. Returns {asked: name in use}.

    Every caller must use the name that comes back. A list refused is left out
    of the answer and logged, loudly enough to find: a model naming states it
    never declared is exactly the refusal worth watching for.

    Declared together so that lists may name each other: the references and
    the productivity check are read over everything this world keeps plus
    everything in this batch, and whatever fails is taken out and the rest
    checked again.
    """
    if world_root is None:
        return {}

    used, batch = {}, {}
    for given in list(declared or []):
        try:
            asked = _slug(given.get("name"))
        except AttributeError:
            continue
        if not asked or not _NAME.fullmatch(asked):
            continue
        if _reserved(asked):
            logger.log_info(f"tokens: refused a list called {asked!r} -- reserved")
            continue
        folded = _fold(world_root, asked)
        if folded:
            used[asked] = folded
            continue
        entry, complaint = clean(given)
        if complaint:
            logger.log_info(f"tokens: refused {asked!r} -- {complaint}")
            continue
        batch[asked] = entry

    kept = vocabulary(world_root)
    while batch:
        candidate = {**kept, **batch}
        good = productive(candidate)
        refused = {}
        for name, entry in batch.items():
            unknown = sorted(
                ref for item in entry["entries"]
                for ref in references(item["text"])
                if ref not in candidate and not _known_name(ref, world_root))
            if name not in good:
                refused[name] = "it can never finish expanding"
            elif unknown:
                refused[name] = f"it names {', '.join(unknown)}, which nothing answers"
        if not refused:
            break
        for name, complaint in refused.items():
            logger.log_info(f"tokens: refused {name!r} -- {complaint}")
            batch.pop(name)

    from world import vocabulary as vocabulary_mod

    for name, entry in batch.items():
        if not vocabulary_mod.permit(world_root, name, "token"):
            continue
        complaint = _settle_facts(world_root, name, entry)
        if complaint:
            logger.log_info(f"tokens: refused {name!r} -- {complaint}")
            continue
        kept[name] = entry
        used[name] = name
        logger.log_info(f"tokens: {world_root.key} learned list {name!r}")
    world_root.db.token_lists = kept
    return used


def register(world_root, name, declared):
    """One list. Returns the name in use, or ""."""
    return register_many(world_root, [{**dict(declared or {}),
                                       "name": name}]).get(_slug(name), "")


def declare(world_root, lists):
    """What a generator's `new_token_lists` asked for, registered."""
    if not lists or not isinstance(lists, (list, tuple)):
        return {}
    return register_many(world_root, lists)


def unregister(world_root, name):
    """
    Take a list away. Returns (removed, complaint).

    Refused while another list names it, because that list would start
    showing its braces. Choices already made from it stay where they are.
    """
    name = _slug(name)
    kept = vocabulary(world_root)
    if name not in kept:
        return False, f"This world keeps no list called {name}."
    users = sorted(other for other, entry in kept.items() if other != name
                   and any(name in references(item["text"])
                           for item in entry["entries"]))
    if users:
        return False, (f"{name} is used by {', '.join(users)}; take "
                       f"{'that' if len(users) == 1 else 'those'} away first.")
    kept.pop(name)
    world_root.db.token_lists = kept
    return True, ""


# ---------------------------------------------------------------------------
# Choosing
# ---------------------------------------------------------------------------

def resolve(name, context, label="", scope=None):
    """
    What a list comes to in this rendering, as a Phrase, or None if the world
    keeps no such list.
    """
    entry = get(context.world_root, name)
    if entry is None:
        return None
    return choose(_slug(name), entry, context, label=label, scope=scope)


def choose(step, entry, context, label="", scope=None):
    """
    What a list -- one the world keeps, or one a dictionary made up on the spot
    -- comes to in this rendering, as a Phrase.

    `step` is the name the choice is kept under: the list's own name, or the
    call that produced the list, so that `$found_at(galley)` and
    `$found_at(forge)` on one thing are two choices.
    """
    from world import tokens

    scope = scope if scope in SCOPES else entry.get("scope", DEFAULT_SCOPE)
    step = f"{step}#{_slug(label)}" if label else step
    path = tuple(context.path) + (step,)
    holder, key = _holder(scope, context, path)
    outermost = not context.path
    group = entry.get("group") or ""

    # A list of states reads the thing's state before anything remembered: the
    # state is the fact, and the fact is what a rule changes.
    if group and scope in FACT_SCOPES and holder is not None:
        current = _state_in(holder, group, context.world_root)
        if current:
            chosen = _entry_setting(entry, current)
            if chosen is None:
                return tokens.Phrase(current)
            return _expand(chosen["text"], context, path)
        if key in _choices(holder):
            # Chosen once, and the fact has since been taken away: the thing is
            # no longer any of these, and remembering the old word would lie.
            fallback = entry.get("fallback") or ""
            return _expand(fallback, context, path) if fallback else tokens.Phrase("")

    stored = _choices(holder).get(key) if scope != "render" else None
    if stored is None:
        item = _pick(entry, context, holder, key, len(path), scope)
        if item is None:
            fallback = entry.get("fallback") or ""
            return _expand(fallback, context, path) if fallback else tokens.Phrase("")
        stored = item["text"]
        if scope != "render" and holder is not None and key:
            _remember(holder, key, stored)
            if outermost and scope in FACT_SCOPES and item.get("sets"):
                _apply(holder, item["sets"], context.world_root)
    return _expand(stored, context, path)


def _holder(scope, context, path):
    """(the object a choice is kept on, the key it is kept under)."""
    key = "/".join(path)
    about = context.about
    if scope == "render":
        return None, ""
    if scope == "world":
        return context.world_root, key
    if scope == "room":
        from evennia.objects.objects import DefaultRoom

        if isinstance(about, DefaultRoom):
            return about, key
        where = getattr(about, "location", None)
        if where is None and context.event is not None:
            where = context.event.room
        if where is None:
            where = getattr(context.viewer, "location", None)
        return where, key
    if scope == "viewer":
        if context.viewer is None or about is None:
            return None, key
        return about, f"{key}@{getattr(context.viewer, 'id', 0)}"
    return about, key


def _choices(holder):
    if holder is None:
        return {}
    try:
        return dict(getattr(holder.db, CHOICES, None) or {})
    except AttributeError:
        return {}


def _remember(holder, key, text):
    choices = _choices(holder)
    choices[key] = text
    setattr(holder.db, CHOICES, choices)


def _pick(entry, context, holder, key, depth, scope):
    """
    One entry, by weight. Seeded from the world, the holder and the slot, so
    the same world makes the same choices -- which is what a test and a soak
    replay need -- and unseeded for a render scope, which exists to vary.
    """
    items = list(entry.get("entries") or [])
    if depth >= MAX_DEPTH:
        lists = set(vocabulary(context.world_root))
        items = [item for item in items
                 if not references(item["text"]) & lists]
    if not items:
        return None
    weights = [float(item.get("weight") or 1) for item in items]
    if scope == "render":
        return random.choices(items, weights)[0]
    seed = (f"{getattr(context.world_root, 'id', 0)}:"
            f"{getattr(holder, 'id', 0)}:{key}")
    number = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16], 16)
    return random.Random(number).choices(items, weights)[0]


def _expand(text, context, path):
    """An entry's text, rendered with its own references nested under `path`."""
    from world import tokens

    before = context.path
    context.path = path
    try:
        words = tokens.text(text, context)
    finally:
        context.path = before
    return tokens.Phrase(words)


def _state_in(holder, group, world_root):
    from world import verbs

    try:
        present = sorted(verbs.states(holder))
    except AttributeError:
        return ""
    for state in present:
        if verbs.group_of(world_root, state) == group:
            return state
    return ""


def _entry_setting(entry, state):
    for item in entry.get("entries") or []:
        if state in ((item.get("sets") or {}).get("states") or []):
            return item
    return None


def _apply(holder, sets, world_root):
    """Make a choice's facts true of whatever holds it. Silently: nobody acted."""
    from world import traits, verbs

    states = list(sets.get("states") or [])
    if states:
        verbs.apply_states(holder, add=states, world_root=world_root,
                           announce=False)
    for slug, value in (sets.get("traits") or {}).items():
        if traits.has_traits(holder):
            traits.adjust(holder, slug, set_to=value, world_root=world_root,
                          announce=False)


# ---------------------------------------------------------------------------
# Lists nobody wrote: the dictionaries
# ---------------------------------------------------------------------------

#: Longest a ConceptNet answer may be, in words. The corpus is crowdsourced,
#: and past three words an answer is a sentence somebody typed rather than a
#: thing that could be lying about.
MOST_WORDS = 3

#: A WordNet sense id, as a call's argument: `sword.n.01`.
_SENSE = re.compile(r"[\w'\-]+\.[nv]\.\d+")


def _sense(argument):
    """A sense id as given, or the one sense a plain word settles to, or ""."""
    from world import lexicon

    argument = str(argument or "").strip()
    if _SENSE.fullmatch(argument):
        return argument
    return lexicon.settled_noun_sense(lexicon.head_noun(argument))


def plausible(word):
    """
    Whether something ConceptNet said is fit to be a word in a description.

    The corpus is advisory everywhere in this game, and this is where its
    advice is checked before anybody reads it: a few words at most, a head
    noun the dictionary knows, and not a person -- "cook" is found in a
    galley, and a galley description is no place to conjure one. False for
    everything without WordNet, which leaves every call to its `else`.
    """
    from world import lexicon

    words = str(word or "").split()
    if not words or len(words) > MOST_WORDS:
        return False
    head = lexicon.head_noun(word)
    if not head or not lexicon.known(head):
        return False
    sense = lexicon.settled_noun_sense(head)
    return not (sense and "person" in lexicon.buckets(sense))


def _hyponym(argument):
    from world import lexicon

    return lexicon.hyponyms(_sense(argument))


def _part_of(argument):
    from world import lexicon

    return lexicon.parts(_sense(argument))


def _conceptnet(relation, forward=False):
    def lookup(argument):
        from world import commonsense

        asked = commonsense.forward if forward else commonsense.backward
        return [word for word in asked(argument, relation, 24)
                if plausible(word)]
    return lookup


#: The calls a description or a list entry may make on the dictionaries, and
#: what each asks. `tokens` reserves the names.
SOURCES = {
    "hyponym": _hyponym,                          # a sort of sword
    "part_of": _part_of,                          # a part of a ship
    "found_at": _conceptnet("AtLocation"),        # something lying in a galley
    "used_for": _conceptnet("UsedFor"),           # something used for cooking
    "kind_of": _conceptnet("IsA", forward=True),  # what bread is a sort of
}


def source(name, args, kwargs, context):
    """
    `$hyponym(sword.n.01)`, `$found_at(galley, else=a crate)`: a word chosen
    from a dictionary, kept the way a world list's choice is kept.

    The answer is made into a list on the spot and chosen from by the same
    path a kept list is, so it has the same scope, seeding and `as=` label --
    and a galley that says "a pot" keeps saying "a pot". `else=` is what it
    says when the dictionary has nothing: no corpus, a word nobody has heard
    of, or nothing that passed `plausible`. A choice already made stays made
    whatever the corpus says later.
    """
    from world import tokens

    lookup = SOURCES.get(name)
    argument = (args[0] if args else "").strip()
    fallback = str(kwargs.get("else") or "")
    words = []
    if lookup is not None and argument:
        try:
            words = [word for word in lookup(argument) if word]
        except Exception as exc:
            logger.log_info(f"tokens: ${name}({argument}) failed ({exc})")
    if not words:
        return tokens.Phrase(fallback)
    entry = {
        "scope": DEFAULT_SCOPE, "group": "", "fallback": fallback,
        "entries": [{"text": re.sub(r"([\\{}$])", r"\\\1", word), "weight": 1.0}
                    for word in dict.fromkeys(words)],
    }
    step = f"{name}:{argument.lower().replace('/', ' ')}"
    return choose(step, entry, context, label=kwargs.get("as", ""),
                  scope=kwargs.get("scope"))


# ---------------------------------------------------------------------------
# Saying what a world keeps
# ---------------------------------------------------------------------------

def spelled(entry, most=ENTRIES_SHOWN):
    """"blue, pink, yellow" -- a list as somebody would read it."""
    texts = [item["text"] for item in entry.get("entries") or []]
    shown = ", ".join(texts[:most])
    return shown + (f", and {len(texts) - most} more" if len(texts) > most else "")


#: What a generator is told, beneath whatever lists this world already keeps.
#: How to use and declare word lists, for a generator that answers through a
#: tool. The lists are behind `list_word_lists` rather than pasted in, and a
#: new one is declared in the tool's `new_token_lists` field.
TOOL_PROMPT = """A description may use a word list: write {name} and one entry
is chosen and kept, so the thing reads the same on every look. Use one only for
a detail that could reasonably differ between two of the same thing -- most
descriptions need none. list_word_lists shows the lists this world keeps; name
only those, or one you declare in new_token_lists.

To make the choice a fact rules can read, give a declared list a "group" and
give each entry the state it sets: {"text": "red", "sets": {"states": ["red"]}}.

A description or an entry may also draw a word from the dictionaries, chosen
and kept the same way: $hyponym(sword.n.01) is some sort of sword,
$part_of(ship.n.01) some part of a ship, $found_at(galley) something found in
a galley, $used_for(cooking) something used for cooking, $kind_of(bread) what
bread is a sort of. Always give an else for when the dictionary has nothing:
$found_at(galley, else=a crate).
"""


# ---------------------------------------------------------------------------
# Lookups (docs/generator-tool-loops.md §5)
# ---------------------------------------------------------------------------

def lookup_tools():
    """`list_word_lists`, `show_word_list` and `try_text`."""
    from world import toolbox as tb

    def listing(ctx, args):
        wanted = str(args.get("for_kind") or "").strip()
        kept = vocabulary(ctx.world_root)
        ordered = sorted(kept.items(),
                         key=lambda pair: (wanted not in (pair[1].get("for")
                                                          or ()), pair[0]))
        return tb.paged([f"{{{name}}}: {spelled(entry)} — "
                         f"{entry.get('means', '')}"
                         for name, entry in ordered], args, "word lists")

    def showing(ctx, args):
        name = _slug(args.get("name"))
        entry = get(ctx.world_root, name)
        if entry is None:
            return f"This world keeps no word list called {name}."
        said = [f"{{{name}}}: {entry.get('means', '')}",
                f"kept per: {entry.get('scope') or DEFAULT_SCOPE}"]
        if entry.get("group"):
            said.append(f"sets the group: {entry['group']}")
        if entry.get("for"):
            said.append(f"for: {', '.join(entry['for'])}")
        said.append("entries: " + spelled(entry, most=MOST_ENTRIES))
        return "\n".join(said)

    def trying(ctx, args):
        from world import effects, tokens

        text = str(args.get("text") or "")
        unknown = sorted(
            name for name in references(text)
            if name not in effects._BUILTIN_SLOTS
            and name not in tokens._PROVIDED_SLOTS
            and get(ctx.world_root, name) is None)
        shown = tokens.text(text, tokens.Context(
            viewer=ctx.actor, world_root=ctx.world_root, purpose="display"))
        said = f"That comes to: {shown}"
        if unknown:
            said += ("\nThis world keeps no list called "
                     + ", ".join("{" + name + "}" for name in unknown)
                     + "; declare it, or use one it keeps.")
        return said

    return [
        tb.Tool("list_word_lists",
                "The word lists a description here may use, those meant for "
                "one sort of thing first.",
                tb.params({**tb.PAGE, "for_kind": {
                    "type": "string",
                    "description": "Optional. Put lists meant for this sort of "
                                   "thing first"}}),
                tb.answering(listing), doing="looking up word lists",
                looks=True),
        tb.Tool("show_word_list", "One word list, every entry.",
                tb.params({"name": {"type": "string",
                                    "description": "The list's name, without "
                                                   "braces"}}, ["name"]),
                tb.answering(showing), doing="looking up a word list",
                looks=True),
        tb.Tool("try_text",
                "What a description comes to once its word lists are filled "
                "in, and which lists it asks for that this world does not keep.",
                tb.params({"text": {"type": "string",
                                    "description": "The description to try"}},
                          ["text"]),
                tb.answering(trying), doing="trying out a description",
                looks=True),
    ]


# ---------------------------------------------------------------------------
# The shape of a declaration, and whether it is one this world has (docs §4.1)
# ---------------------------------------------------------------------------

def schema(ctx=None):
    """One word list, as `clean` reads it."""
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string",
                     "description": "The list's name, as it is written in "
                                    "braces"},
            "means": {"type": "string",
                      "description": "One sentence on what the list is for"},
            "scope": {"type": "string", "enum": list(SCOPES),
                      "description": "What a choice is kept on"},
            "group": {"type": "string",
                      "description": "Optional. The state group its entries "
                                     "set"},
            "for": {"type": "array", "items": {"type": "string"},
                    "description": "Optional. The sorts of thing it is meant "
                                   "for"},
            "fallback": {"type": "string",
                         "description": "Optional. What to say if nothing can "
                                        "be chosen"},
            "entries": {"type": "array",
                        "items": {"type": "object", "properties": {
                            "text": {"type": "string"},
                            "weight": {"type": "number"},
                            "sets": {"type": "object"}},
                            "required": ["text"]},
                        "description": "The words it chooses between"},
        },
        "required": ["name", "means", "entries"],
    }


def near_duplicate(world_root, name):
    """The list this world already keeps under another spelling, or ""."""
    wanted = _slug(name)
    folded = _fold(world_root, wanted) if wanted else ""
    return folded if folded and folded != wanted else ""
