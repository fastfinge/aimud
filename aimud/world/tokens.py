"""
Words that stand for something, and what they come to for one reader.

Four things in this game used to put a variable into a sentence, and none of
them knew about the others: narration templates (`{actor}`, `$pconj(hand)`),
a world's description (`<user>`, spelled three ways), Evennia's funcparser in
player speech, and f-strings in memory. This module is the one grammar they
share. See docs/tokens-and-phrases.md.

**A token resolves to a phrase, not a string.** "a {fruit}" is "a apple", and
"{count} {animal}" is "three sheeps", unless what a token comes to carries
what is grammatically true of it -- its number, whether it is you, what it
refers to -- so that whatever follows can agree with it. A rendering is a
sequence of *spans*: plain strings for words as written, `Phrase` for words
about something. `str()` joins them. Everything that shows a player text
reads that string; everything that wants to know which words were which
object -- memory annotations, and one day MXP links -- reads the spans.

**The grammar is the one already stored.** Every narration template every
world has cached is spelled `{actor} $pconj(hand) {target} {direct}.`, and
`verb_gen` already teaches models to write it:

    {name}  {name.field.field}  {name's}  {name}'s
        a slot. What `name` means comes from, in order: the words a caller
        bound as quotes, the roles of an event, the built-ins below, and
        whatever a plugin provided. A slot nothing answers is left exactly as
        written.
    $name(argument, key=value)
        a call. Arguments are text and may hold slots and calls of their own;
        a double-quoted argument is taken as written, commas and all. An
        unknown call, or one whose parenthesis never closes, is left as
        written.
    \\{  \\}  \\$  \\\\
        the character itself, not the start of anything.

`<user>`, `{{user}}` and `$user` are older spellings of `{user}` and read the
same. There are no conditionals and no loops, and there will not be: "damp if
wet" is a state read or a rule. A slot's fields are a closed table, never
attribute access -- see `_field`.

**Why not Evennia's `FuncParser`**, which already parses `$name(...)`: it
joins every call's result with `str()` the moment there is any text around the
call, so a `Phrase` never survives a sentence. The spike that measured this,
and the behaviour copied from it, are recorded in the plan's phase 1.

**What is expanded and what is not is decided by where text comes from**, not
by escaping it. A template is author text and expands. Words somebody said,
and names, arrive as *quotes*: bound to a slot by whoever builds the event,
and inserted as a plain span that is never parsed. An NPC whose line contains
`{target}` says "{target}".
"""

import re
from collections import namedtuple
from functools import lru_cache

#: The roles a narration can name, in the order they rank.
#:
#: Grammatical role order, which is what centering theory ranks by: the
#: subject outranks the object, the object outranks everything oblique.
#: `world.events` ranks participants by it, and a world may never declare a
#: token under one of these names.
ROLES = ("actor", "direct", "target", "container", "source", "instrument")

#: Slot names that mean something before any world says anything.
RESERVED_SLOTS = frozenset(ROLES + ("self", "user", "viewer", "here", "world",
                                    "quote"))

#: Call names kept for this game's own use: `pconj`, the English calls -- `an`,
#: `the`, `plural`, `count` -- and `pick`, which chooses from a world list.
RESERVED_CALLS = frozenset(("pconj", "an", "the", "plural", "count", "pick"))

#: The tenses a rendering can be asked for. `$pconj` conjugates for either.
TENSES = ("present", "past")

#: What a rendering is for. `display` is somebody reading, `prompt` is a model
#: reading, `memory` is a character remembering.
PURPOSES = ("display", "prompt", "memory")

#: The forms a pronoun set has, as a slot's field: `{target.object}`.
PRONOUN_FIELDS = ("subject", "object", "adjective", "possessive", "reflexive")

#: What the reader is called in each form. Never spends anything, never
#: ambiguous.
SECOND_PERSON = {"subject": "you", "object": "you", "adjective": "your",
                 "possessive": "yours", "reflexive": "yourself"}

#: The older spellings of `{user}`. {{user}} was what the world wizard first
#: offered, and Evennia's display eats one of its braces; <user> is what the
#: wizard teaches now. Both keep working, for every world written with them.
USER_ALIAS = re.compile(
    r"\{\{\s*user\s*\}\}" r"|<\s*user\s*>" r"|\$user\b(?!\()",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# What a token comes to
# ---------------------------------------------------------------------------

class Phrase:
    """
    Words, and what is true of them.

    `ref` is the object the words are about, when they are about one. `plural`
    is read off that object's pronoun set the first time anybody asks, rather
    than for every slot of every rendering: most phrases are never asked.
    """

    __slots__ = ("text", "_plural", "person", "countable", "proper", "ref",
                 "sense", "facts", "_world_root")

    def __init__(self, text="", plural=None, person=3, countable=True,
                 proper=False, ref=None, sense="", facts=(), world_root=None):
        self.text = str(text or "")
        self._plural = plural
        self.person = person
        self.countable = countable
        self.proper = proper
        self.ref = ref
        self.sense = sense
        self.facts = tuple(facts)
        self._world_root = world_root

    @property
    def plural(self):
        if self._plural is None:
            if self.ref is None:
                self._plural = False
            else:
                from world.events import pronoun_forms

                self._plural = bool(pronoun_forms(
                    self.ref, self._world_root).get("plural"))
        return self._plural

    def __str__(self):
        return self.text

    def __repr__(self):
        return f"Phrase({self.text!r}, ref={getattr(self.ref, 'key', self.ref)!r})"


class Rendering:
    """
    A template as one reader will read it: a sequence of spans.

    A span is a `str` -- words as written, or words somebody said -- or a
    `Phrase`. `str()` is the sentence.
    """

    __slots__ = ("spans",)

    def __init__(self, spans=()):
        self.spans = list(spans)

    def refs(self):
        """Everything the rendering named, in the order it named them."""
        return [span.ref for span in self.spans
                if isinstance(span, Phrase) and span.ref is not None]

    def __str__(self):
        return "".join(str(span) for span in self.spans)

    def __repr__(self):
        return f"Rendering({self.spans!r})"


class Context:
    """
    Everything a rendering may ask about.

    `about` is the object the text belongs to -- a description's owner --
    and is what `{self}` means. `naming` is whatever decides what to call a
    participant; `world.events` hands in its `Naming`, which knows the
    centering rule, and a rendering with none names everybody plainly. `quotes`
    are words bound to slots that must never be parsed.
    """

    __slots__ = ("viewer", "event", "about", "world_root", "tense", "purpose",
                 "naming", "quotes", "path", "_bound", "_mapping")

    def __init__(self, viewer=None, event=None, about=None, world_root=None,
                 tense="present", purpose="display", naming=None, quotes=None):
        self.viewer = viewer
        self.event = event
        self.about = about
        if world_root is None and event is not None:
            world_root = event.world_root
        self.world_root = world_root
        self.tense = tense if tense in TENSES else "present"
        self.purpose = purpose if purpose in PURPOSES else "display"
        self.naming = naming
        self.quotes = dict(quotes or {})
        # The word-list slots being expanded around this one, outermost first.
        # See `world.token_lists`.
        self.path = ()
        self._bound = None
        self._mapping = None

    def bound_quotes(self):
        """The event's quotes -- its words and its effects -- then the caller's."""
        if self._bound is None:
            found = {}
            if self.event is not None:
                found.update(getattr(self.event, "quoted", dict)())
            found.update(self.quotes)
            self._bound = found
        return self._bound

    def mapping(self):
        if self._mapping is None:
            self._mapping = (self.event.mapping() if self.event is not None
                             else {})
        return self._mapping

    def namer(self):
        """What decides names: the caller's, or one that names everybody."""
        if self.naming is None:
            from world.events import Naming

            self.naming = Naming(self.viewer, self.event, previous=[])
            if self.naming.world_root is None:
                self.naming.world_root = self.world_root
        return self.naming


# ---------------------------------------------------------------------------
# Reading a template
# ---------------------------------------------------------------------------

Text = namedtuple("Text", "text")
Slot = namedtuple("Slot", "name fields possessive raw")
Call = namedtuple("Call", "name args kwargs raw")

#: A slot, fields and possessive included. `\w+` rather than an identifier
#: for the name because that is what every template stored so far was read
#: with, and a slot nothing answers is left alone either way.
_SLOT = re.compile(r"\{(\w+(?:\.\w+)*)('s)?\}('s)?")

#: The start of a call: a dollar, a name that can start one, a parenthesis.
#: "$5" and "$ 5" are money.
_CALL = re.compile(r"\$([A-Za-z_]\w*)\(")

#: A keyword argument's key.
_KEYWORD = re.compile(r"\s*([A-Za-z_]\w*)\s*=(.*)\Z", re.DOTALL)

#: What an escape may escape. Anything else keeps its backslash, so a stray
#: one in something a model wrote is left as it was.
_ESCAPABLE = "\\{}$"

#: A thing following a possessive in the same clause: "{target's} {direct}",
#: "{target's} own {direct}". It is already determined, and "her the sword" is
#: not English. What may stand between them is up to two plain words.
_DETERMINED = re.compile(r"\s+(?:\w+\s+){0,2}")

#: A name a plugin may provide.
_NAME = re.compile(r"[A-Za-z_]\w*")


def parse(template):
    """The nodes of a template: `Text`, `Slot` and `Call`, in order."""
    return _parse(USER_ALIAS.sub("{user}", str(template or "")))


@lru_cache(maxsize=4096)
def _parse(text):
    """
    Cached, because a world has a few hundred templates and renders each of
    them once per person in the room.
    """
    nodes, words = [], []

    def flush():
        if words:
            nodes.append(Text("".join(words)))
            words.clear()

    at, end = 0, len(text)
    while at < end:
        char = text[at]
        if char == "\\" and text[at + 1:at + 2] and text[at + 1] in _ESCAPABLE:
            words.append(text[at + 1])
            at += 2
            continue
        if char == "{":
            match = _SLOT.match(text, at)
            if match:
                flush()
                name, *fields = match.group(1).split(".")
                nodes.append(Slot(name, tuple(fields),
                                  bool(match.group(2) or match.group(3)),
                                  match.group(0)))
                at = match.end()
                continue
        if char == "$":
            match = _CALL.match(text, at)
            close = _closing(text, match.end()) if match else -1
            if close >= 0:
                flush()
                args, kwargs = _arguments(text[match.end():close])
                nodes.append(Call(match.group(1), args, kwargs,
                                  text[at:close + 1]))
                at = close + 1
                continue
        words.append(char)
        at += 1
    flush()
    return tuple(nodes)


def _closing(text, start):
    """Where the parenthesis opened just before `start` closes, or -1."""
    depth, quoted, at = 1, False, start
    while at < len(text):
        char = text[at]
        if char == "\\":
            at += 2
            continue
        if char == '"':
            quoted = not quoted
        elif not quoted:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return at
        at += 1
    return -1


def _arguments(inner):
    """
    (args, kwargs) of a call, each value a tuple of nodes.

    Split on commas that are not inside quotes, parentheses, braces or
    brackets. A double-quoted value is text exactly as written; anything else
    is stripped and read as a template of its own, which is what lets a call
    hold a slot or another call. An empty unquoted argument is no argument.
    """
    pieces, current, depth, quoted, at = [], [], 0, False, 0
    while at < len(inner):
        char = inner[at]
        if char == "\\" and at + 1 < len(inner):
            current.append(inner[at:at + 2])
            at += 2
            continue
        if char == '"':
            quoted = not quoted
        elif not quoted:
            if char in "([{":
                depth += 1
            elif char in ")]}":
                depth -= 1
            elif char == "," and depth == 0:
                pieces.append("".join(current))
                current = []
                at += 1
                continue
        current.append(char)
        at += 1
    pieces.append("".join(current))

    args, kwargs = [], []
    for piece in pieces:
        key = None
        keyword = _KEYWORD.match(piece)
        if keyword and '"' not in piece[:keyword.start(2)]:
            key, piece = keyword.group(1), keyword.group(2)
        value = piece.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            nodes = (Text(value[1:-1]),)
        elif value:
            nodes = _parse(value)
        elif key is None:
            continue
        else:
            nodes = ()
        if key is None:
            args.append(nodes)
        else:
            kwargs.append((key, nodes))
    return tuple(args), tuple(kwargs)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render(template, context):
    """
    A template as `context` will read it, as a `Rendering`.

    One pass, left to right, so that a slot can know what came before it in
    its clause: that is how "{target's} {direct}" comes out "her sword"
    rather than "her the sword".
    """
    return Rendering(_spans(parse(template), context))


def text(template, context):
    """The same, as the sentence."""
    return str(render(template, context))


def _spans(nodes, context):
    spans = []
    # The words since the last possessive slot, or None when there was none
    # in this clause. A clause ends at punctuation, which `_DETERMINED`
    # refuses to match, and at any other slot.
    since_possessive = None
    for node in nodes:
        if isinstance(node, Text):
            spans.append(node.text)
            if since_possessive is not None:
                since_possessive += node.text
        elif isinstance(node, Call):
            span = _call(node, context)
            spans.append(span)
            if since_possessive is not None:
                since_possessive += str(span)
        else:
            determined = (since_possessive is not None
                          and _DETERMINED.fullmatch(since_possessive))
            spans.append(_slot(node, context, bare=bool(determined)))
            since_possessive = "" if node.possessive else None
    return spans


def _flat(nodes, context):
    """An argument, as plain text."""
    return "".join(str(span) for span in _spans(nodes, context)).strip()


def _slot(node, context, bare=False):
    name, fields, possessive = node.name, node.fields, node.possessive

    quotes = context.bound_quotes()
    if name in quotes:
        if fields:
            return node.raw
        said = str(quotes[name] or "")
        return f"{said}'s" if possessive and said else said

    mapping = context.mapping()
    if name in mapping:
        return _about(mapping[name], name, fields, possessive, bare, context,
                      node)

    if name == "self" and context.about is not None:
        return _about(context.about, "self", fields, possessive, bare, context,
                      node)
    if name == "viewer" and context.viewer is not None:
        return _about(context.viewer, "viewer", fields, possessive, bare,
                      context, node)
    if name in ("user", "here", "world") and not fields:
        found = _builtin(name, context)
        if found is not None:
            words = f"{found.text}'s" if possessive and found.text else found.text
            found.text = words
            return found

    if not fields and context.world_root is not None:
        from world import token_lists

        found = token_lists.resolve(name, context)
        if found is not None:
            if possessive and found.text:
                found.text = f"{found.text}'s"
            return found

    provided = _PROVIDED_SLOTS.get(name)
    if provided is not None:
        try:
            found = provided(context, fields=fields, possessive=possessive)
        except Exception as exc:
            from evennia.utils import logger

            logger.log_info(f"tokens: {name} failed ({exc})")
            found = None
        if found is not None:
            return found

    return node.raw


def _about(obj, role, fields, possessive, bare, context, node):
    """A slot that names an object: the name, or one of its fields."""
    if fields:
        found = _field(obj, fields, possessive, context)
        return node.raw if found is None else found
    words = context.namer().name(obj, role, possessive, bare=bare)
    return Phrase(words, ref=obj, person=2 if obj is context.viewer else 3,
                  world_root=context.world_root)


def _builtin(name, context):
    """`{user}`, `{here}` and `{world}`: a Phrase, or None."""
    if name == "user":
        from world import lore

        return Phrase(lore.user_name(context.world_root, context.viewer),
                      ref=context.viewer, proper=True)
    if name == "here":
        room = (context.event.room if context.event is not None
                else getattr(context.viewer, "location", None))
        if room is None:
            return None
        title = getattr(room.db, "room_title", None) or room.key
        return Phrase(title, ref=room)
    if name == "world" and context.world_root is not None:
        from world import lore

        return Phrase(lore.title(context.world_root), ref=context.world_root,
                      proper=True)
    return None


def _field(obj, fields, possessive, context):
    """
    One field of an object, or None for a field there is no such thing as.

    The whole table, deliberately: a field is a question this game already
    knows how to answer about anything, never a path into an object's
    attributes. A world that could write `{direct.db.api_key}` would be a
    world that could read one.

        name                                   what it is called, bare
        subject object adjective possessive reflexive
                                               its pronoun, in that form
        state.<group>                          which state of that group it is in
        trait.<slug>                           its value for that trait
        owner                                  who owns it
    """
    viewer, world_root = context.viewer, context.world_root
    head, rest = fields[0], fields[1:]

    if head == "name" and not rest:
        try:
            words = obj.get_display_name(viewer)
        except AttributeError:
            words = str(getattr(obj, "key", obj))
        return Phrase(f"{words}'s" if possessive else words, ref=obj)

    if head in PRONOUN_FIELDS and not rest:
        if obj is viewer:
            return Phrase(SECOND_PERSON[head], ref=obj, person=2)
        from world.events import pronoun_forms

        forms = pronoun_forms(obj, world_root)
        return Phrase(forms.get(head, ""), ref=obj,
                      plural=bool(forms.get("plural")))

    if head == "state" and len(rest) == 1:
        from world import verbs

        for state in sorted(verbs.states(obj)):
            if verbs.group_of(world_root, state) == rest[0]:
                return Phrase(state)
        return Phrase(verbs.group_rules(world_root, rest[0]).get("default", ""))

    if head == "trait" and len(rest) == 1:
        from world import traits

        value = traits.value(obj, rest[0])
        if value is None:
            return Phrase("")
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return Phrase(str(value))

    if head == "owner" and not rest:
        from world import ownership

        owner = ownership.owner_of(obj)
        if owner is None:
            return Phrase(ownership.owner_name(obj))
        words = context.namer().name(owner, "owner", possessive)
        return Phrase(words, ref=owner, person=2 if owner is viewer else 3,
                      world_root=world_root)

    return None


def _call(node, context):
    args = [_flat(arg, context) for arg in node.args]
    kwargs = {key: _flat(value, context) for key, value in node.kwargs}

    if node.name == "pconj":
        return _pconj(args, context)
    if node.name in _ENGLISH:
        return _english(node, args)
    if node.name == "pick":
        # `$pick(color)`, `$pick(color, scope=room)`, `$pick(color, as=stripes)`:
        # a world list with its defaults overridden. See `world.token_lists`.
        from world import token_lists

        found = token_lists.resolve(args[0] if args else "", context,
                                    label=kwargs.get("as", ""),
                                    scope=kwargs.get("scope"))
        return node.raw if found is None else found

    provided = _PROVIDED_CALLS.get(node.name)
    if provided is not None:
        try:
            found = provided(context, *args, **kwargs)
        except Exception as exc:
            from evennia.utils import logger

            logger.log_info(f"tokens: ${node.name} failed ({exc})")
            found = None
        if found is not None:
            return found

    return node.raw


def _pconj(args, context):
    """
    `$pconj(verb)` and `$pconj(verb, role)`: the verb agreeing with its subject,
    in the rendering's tense. The role defaults to the actor.
    """
    from world.events import conjugate

    verb = args[0] if args else ""
    role = args[1] if len(args) > 1 and args[1] else "actor"
    namer = context.namer()
    return conjugate(verb, context.mapping().get(role), context.viewer,
                     namer.world_root or context.world_root,
                     tense=context.tense)


#: The calls `world.english` answers.
_ENGLISH = ("an", "the", "plural", "count")


def _english(node, args):
    """
    `$an(sword)`, `$the(sword)`, `$plural(tooth)`, `$count(3, coin)`.

    On words, not on things: an argument arrives as text, so nothing here
    knows that "water" is stuff or that "Raldor" is somebody. A slot already
    chooses its own article from the thing it names; these are for words a
    template or a list writes out.
    """
    from world import english

    noun = args[-1] if args else ""
    if node.name == "an":
        return english.with_article(noun)
    if node.name == "the":
        return english.with_article(noun, definite=True)
    if node.name == "plural":
        return english.plural(noun)
    if len(args) < 2:
        return node.raw
    try:
        number = int(args[0])
    except ValueError:
        return node.raw
    return english.count(number, noun)


# ---------------------------------------------------------------------------
# What plugins may add
# ---------------------------------------------------------------------------

_PROVIDED_SLOTS = {}
_PROVIDED_CALLS = {}


def provide(name, resolver, call=False):
    """
    Let something installed on this server answer a slot or a call.

    `resolver(context, fields=..., possessive=...)` for a slot, and
    `resolver(context, *args, **kwargs)` for a call, returning a `Phrase`, a
    string, or None for "not mine after all" -- in which case the slot is left
    as written. Refuses a reserved name and one that is not a name at all:
    a plugin can add to what the game understands but never change what it
    already means.

    Only the seam. The loader is `future-plans.md`'s affect plugins.
    """
    name = str(name or "")
    if not _NAME.fullmatch(name):
        raise ValueError(f"{name!r} is not a token name")
    if name in RESERVED_SLOTS or name in RESERVED_CALLS:
        raise ValueError(f"{name!r} is reserved")
    (_PROVIDED_CALLS if call else _PROVIDED_SLOTS)[name] = resolver


def withdraw(name):
    """Take back whatever `provide` added under this name."""
    _PROVIDED_SLOTS.pop(name, None)
    _PROVIDED_CALLS.pop(name, None)


# ---------------------------------------------------------------------------
# A thing's own text
# ---------------------------------------------------------------------------

def world_root_of(obj):
    """The world a thing belongs to: its own for a room, or wherever it is."""
    where, steps = obj, 0
    while where is not None and steps < 20:
        root = getattr(getattr(where, "db", None), "world_root", None)
        if root is not None:
            return root
        where = getattr(where, "location", None)
        steps += 1
    return None


def text_of(obj, attribute="desc", viewer=None, purpose="prompt"):
    """
    A thing's stored text with its tokens filled in: what a prompt reads.

    Everything that puts a description in front of a model comes through
    here rather than reading `db.desc`, because the stored text keeps its
    tokens -- so that a fact behind one goes on rendering live -- and a model
    shown a raw `{color}` will invent one.
    """
    if obj is None:
        return ""
    try:
        raw = getattr(obj.db, attribute, None)
    except AttributeError:
        return ""
    if not raw:
        return ""
    return text(raw, Context(viewer=viewer, about=obj,
                             world_root=world_root_of(obj), purpose=purpose))


def settle(obj, attribute="desc"):
    """
    Make every choice a thing's own text depends on, now.

    Called where a thing is made and where its text is rewritten, so that a
    choice exists before anything -- a player, or a model writing a rule about
    it -- reads the text. A choice once per viewer cannot be made in advance
    and is left for whoever looks.
    """
    return text_of(obj, attribute)
