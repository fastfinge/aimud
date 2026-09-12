"""
What happened, said once and rendered for each person who saw it.

Every delivery site in this game used to do the same thing: take the facts of
an action, melt them into a sentence, and throw the facts away.

    on_message(f"You put {label} {preposition} {where}.",
               f"{name} puts {label} {preposition} {where}.")

The verb, the roles, the preposition, the outcome and the effects that fired
are all present on that line, and none of them survives it. Six things want
exactly those facts -- sound, two out-of-band protocols, the web client,
shared worlds, and the renderer that has to choose between "she" and
"Jessica" -- and each of them would otherwise mean visiting every site again.

So what travels is the **event**, and a sentence is one rendering of it.

**Why the rendering loop is here rather than Evennia's.** `msg_contents`
already renders per recipient, and the obvious plan was to hand it a template
and a mapping and let it do the work. It cannot do what comes next.
`objects.py` builds its parser from `funcparser.ACTOR_STANCE_CALLABLES`, a
fixed dict, so a callable of ours is never consulted however it is configured;
and its `{key}` substitution goes through `get_display_name`, which is the
same call that names things in an inventory listing and in a room's contents.
Making *that* answer "she" would put a pronoun in both.

What is needed instead is a substitution that knows it is rendering a
narration, knows which role each name is filling, and knows who is reading.
That is what `render` is. `msg_contents` stays exactly right for everything
that is not an action.

**Who gets a pronoun, and why it is not "whoever was mentioned last".** The
rule is centering theory's (Grosz, Joshi and Weinstein): if anything in a
sentence is a pronoun, it is the *backward-looking centre* -- the
highest-ranked participant of the last sentence this reader was shown that
is also in this one. Ranked by grammatical role, actor first, which is what
`RANK` is. Three consequences, each a test below in `tests/test_events.py`:

* "Jessica picks up the sword" then "**She** hands Britney the sword" -- the
  centre carries into the subject.
* "Britney examines the sword" then "Jessica hands **her** the sword" -- the
  centre carries into the object, and English marks precisely that.
* "The lamp gutters" then "Jessica hands Britney the sword" -- nothing
  carries over, so **nobody** is a pronoun. A pronoun with no antecedent in
  the reader's attention is worse than a name, and a most-recently-mentioned
  heuristic produces one constantly.

The budget is **one pronoun per surface form**: "She hands her the sword" is
unreadable and "She examines it" is not, and the difference lives entirely
within a form. The reader themselves is always "you", which is never
ambiguous and spends nothing.

**A template says what happened; the reader decides the words.** Two kinds of
slot, both filled here and nowhere else:

    {actor} {direct} {target} {container} {source} {instrument}
        a participant, by role -- a name, "you", or a pronoun. The actor
        is the sentence's subject and gets the subject form; every other
        role gets the object form.
    {actor's} {direct's}
        the same participant as a possessor -- "Jessica's", "your", "her".
    $pconj(verb)  $pconj(verb, role)
        a verb agreeing with its subject: "hands" for one person, "hand"
        for they/them and for the reader. Only the first word is
        conjugated, so "$pconj(pick) up" and "$pconj(pick up)" both work.

Rendering has one side effect, and it is the whole mechanism: the reader's
`referents` table is told what they were just shown, so that the next line
knows what they are thinking about and "hug her", typed after watching
Jessica act, reaches Jessica.
"""

import re

from world import referents

#: The roles a narration can name, in the order they rank.
#:
#: Grammatical role order, which is what centering theory ranks by: the
#: subject outranks the object, the object outranks everything oblique.
#: `participants` returns things in this order and `centre` reads it.
RANK = ("actor", "direct", "target", "container", "source", "instrument")

#: A placeholder in a narration template: `{actor}`, `{direct}`, and the
#: possessive `{actor's}` (or `{actor}'s`, which a model writes just as often).
_SLOT = re.compile(r"\{(\w+)('s)?\}('s)?")

#: A verb to agree with its subject: `$pconj(pick)`, `$pconj(pick, direct)`.
#: Evennia's funcparser spells it the same way, so a template written for one
#: reads correctly in the other; the machinery here is ours (see the module
#: docstring for why).
_CONJ = re.compile(r"\$pconj\(([^)]*)\)")


class Event:
    """
    One thing that happened, before anybody has been told about it.

    Carries the facts and the words separately. `actor_text` and
    `room_template` are what a model wrote or what a mechanic composed; the
    rest is what actually occurred, and is what everything other than prose
    will want.
    """

    __slots__ = ("actor", "room", "verb", "roles", "outcome", "effects",
                 "actor_text", "room_template", "raw", "manner", "contested")

    def __init__(self, actor=None, room=None, verb="", roles=None,
                 outcome="success", effects=(), actor_text="",
                 room_template="", raw="", manner=(), contested=False):
        self.actor = actor
        self.room = room if room is not None else getattr(actor, "location", None)
        self.verb = verb
        self.roles = dict(roles or {})
        self.outcome = outcome
        self.effects = list(effects)
        self.actor_text = actor_text
        self.room_template = room_template
        self.raw = raw
        self.manner = list(manner)
        self.contested = contested

    @property
    def seen(self):
        """Whether anybody but the actor has anything to read."""
        return bool(str(self.room_template or "").strip())

    def mapping(self):
        """
        {slot: object} for the template. The actor under its own name as well
        as the roles, because a template says `{actor}` and nothing else in
        the mapping knows who that is.
        """
        found = {role: obj for role, obj in self.roles.items()
                 if obj is not None}
        if self.actor is not None:
            found["actor"] = self.actor
        return found

    def participants(self, viewer=None):
        """
        Everybody and everything the event names, ranked.

        The order the centering rule reads. `viewer` is accepted and unused:
        the rule excludes the reader itself, but does so where it decides
        rather than here, so that what is recorded about a sentence is the
        same for everybody who read it.
        """
        mapping = self.mapping()
        found = [mapping[role] for role in RANK if role in mapping]
        for role, obj in sorted(mapping.items()):
            if role not in RANK and obj not in found:
                found.append(obj)
        return found

    @property
    def world_root(self):
        room = self.room
        try:
            return room.db.world_root if room is not None else None
        except AttributeError:
            return None

    def __repr__(self):
        return (f"<Event {self.verb!r} by {getattr(self.actor, 'key', None)!r}"
                f" {self.outcome}>")


#: An article standing immediately before a placeholder.
#:
#: The prompt forbids it and a model writes it anyway, because every sentence
#: it has ever read has the article there. `plain_name` supplies the
#: determiner itself -- it has to, since the same slot may come back "her" or
#: "you" -- so what is left is "the the sword".
_ARTICLE_BEFORE_SLOT = re.compile(r"\b[Aa]n?\b\s+(?=\{)|\b[Tt]he\b\s+(?=\{)")

#: A bare third-person-singular verb where the actor's verb should be.
#:
#: Only the word directly after `{actor}`, and only when it is visibly
#: third-person singular: the repair has to be one this can be certain of.
_ACTOR_VERB = re.compile(r"(\{actor(?:'s)?\}|\{actor\}'s)(\s+)([a-z]+(?:e?s))\b")


def _base_form(word):
    """
    The base form of a third-person-singular verb, or "" if it is not one.

    Asked of Evennia's conjugator rather than guessed at with suffix rules,
    which is the only way "tries" comes back "try" and "watches" "watch"
    without a table of exceptions here. "" for anything whose third person is
    not the word given -- "is", "has", a plural noun that happens to end in s
    -- so the caller leaves alone whatever it cannot be sure about.
    """
    for guess in _base_guesses(word):
        try:
            if _stance(guess, False)[1] == word:
                return guess
        except Exception:
            continue
    return ""


def _base_guesses(word):
    """Every base form `word` could be the third person singular of."""
    if word.endswith("ies") and len(word) > 4:
        yield word[:-3] + "y"
    if word.endswith(("ses", "xes", "zes", "ches", "shes")):
        yield word[:-2]
    if word.endswith("es"):
        yield word[:-1]
        yield word[:-2]
    if word.endswith("s"):
        yield word[:-1]


def repair(template):
    """
    A narration template that will render, whatever the model sent back.

    Three things a narrator gets wrong, all of which are permanent rather
    than one-off: what is stored is the template, replayed for every later
    viewer and for everybody who does this afterwards. So they are fixed here,
    on the TEMPLATE, before storage -- and on everything already cached, which
    is what lets a world written before P4 go on reading correctly.

    * No subject at all -- "lights the candle." -- broadcast with nobody
      attached to it. Repaired rather than refused: the alternative is losing
      an action that really happened.
    * An article before a placeholder -- "the {direct}" -- which renders "the
      the sword", since the slot supplies its own determiner and has to.
    * The actor's verb conjugated -- "{actor} hands" -- which can never agree
      with anybody. It is "hands" for a they/them character who should get
      "hand", and "hands" for the reader themselves who should get "you
      hand". Wrapping it in `$pconj` is the difference between a template
      that works for one pronoun set and one that works for all of them.
    """
    text = str(template or "").strip()
    if not text:
        return ""
    if "{" not in text:
        if not text[:1].islower():
            return text
        text = f"{{actor}} {text}"
    text = _ARTICLE_BEFORE_SLOT.sub("", text)
    return _ACTOR_VERB.sub(_wrap_actor_verb, text)


def _wrap_actor_verb(match):
    """`{actor} hands` -> `{actor} $pconj(hand)`, or leave it be."""
    slot, gap, verb = match.groups()
    base = _base_form(verb)
    return f"{slot}{gap}$pconj({base})" if base else match.group(0)


# ---------------------------------------------------------------------------
# Choosing a name
# ---------------------------------------------------------------------------

def centre(previous, current, viewer=None):
    """
    What the reader is already thinking about, or None.

    Centering theory's backward-looking centre: the highest-ranked entity of
    the PREVIOUS sentence that also appears in this one. Both arguments are
    ranked participant lists and the ranking that counts is `previous`'s --
    attention is about what was last read, not about what is being said now.

    The reader is never the centre: they are "you" in whatever slot they
    fill, and a second-person pronoun spends nothing.

    None when nothing carries over, and that answer matters as much as the
    others. It is what keeps a pronoun from appearing with no antecedent.
    """
    for obj in previous or []:
        if obj is None or obj is viewer:
            continue
        if any(obj is here for here in current or []):
            return obj
    return None


def pronoun_forms(obj, world_root=None):
    """
    The set a participant would be referred to by, whatever it is.

    A person goes by the set they chose; a thing has only a number, "it" or
    "them", read off its name the way `referents.forms_of` reads it. Never
    None, so a caller may index it.
    """
    from world import pronouns
    from world.quests import is_person

    if obj is None:
        return dict(pronouns.SEEDED["it"])
    if is_person(obj):
        return pronouns.of(obj, world_root)
    return dict(pronouns.SEEDED["they" if referents.is_plural(obj) else "it"])


def plain_name(obj, viewer, bare=False):
    """
    The name, as it reads in a sentence. No pronouns.

    A person is their name. A thing is "the sword": definite, because a
    narration is about a thing everybody present can see, and "Jessica picks
    up a sword" reads as though one had just appeared. A name that already
    starts with an article is left alone, and `bare` asks for none at all --
    for a thing that follows a possessive, where "her the sword" is not
    English.
    """
    if obj is None:
        return ""
    try:
        name = obj.get_display_name(viewer)
    except AttributeError:
        return str(getattr(obj, "key", obj))
    from world.quests import is_person

    try:
        person = is_person(obj)
    except AttributeError:
        person = False
    if person or bare or not name:
        return name
    if str(name).lower().split(" ", 1)[0] in ("the", "a", "an", "some"):
        return name
    return f"the {name}"


def _reads(viewer):
    """Whether this viewer is somebody, with attention worth tracking."""
    if viewer is None or not hasattr(viewer, "ndb"):
        return False
    from world.quests import is_person

    try:
        return bool(is_person(viewer))
    except AttributeError:
        return False


class Naming:
    """
    Every name in one sentence, for one reader.

    The two things a name cannot decide on its own: which participant is the
    centre, and which pronoun forms this sentence has already spent. Both are
    per sentence and per reader, which is why this is an object made once per
    `render` rather than a function.

    `previous` is what the reader was last shown, and is read from their
    referents table unless a caller supplies it -- which is how the rule can
    be tested as the pure thing it is: two ranked lists in, a choice out.
    """

    def __init__(self, viewer, event, previous=None):
        self.viewer = viewer
        self.event = event
        self.world_root = event.world_root if event is not None else None
        self.reads = _reads(viewer)
        self.spent = set()
        current = event.participants() if event is not None else []
        if previous is None:
            previous = referents.told(viewer) if self.reads else []
        self.centre = centre(previous, current, viewer) if self.reads else None

    def name(self, obj, role="", possessive=False, bare=False):
        """
        What to call one participant, in one slot.

        The reader is "you". The centre is a pronoun, unless this sentence
        has already used that form for something -- then it is named, because
        one "her" is a reference and two is a puzzle. Everybody else is named.
        `bare` is a thing after a possessive, which takes no article.
        """
        if obj is None:
            return ""
        if obj is self.viewer:
            return "your" if possessive else "you"
        if obj is self.centre:
            forms = pronoun_forms(obj, self.world_root)
            if possessive:
                word = forms.get("adjective", "")
            elif role == "actor":
                word = forms.get("subject", "")
            else:
                word = forms.get("object", "")
            if word and word not in self.spent:
                self.spent.add(word)
                return word
        name = plain_name(obj, self.viewer, bare=bare)
        return f"{name}'s" if possessive else name

    def remember(self):
        """
        Record what the reader was just shown.

        Two tables, one module: the ranked participants, which is what the
        next sentence's centre is chosen from, and the pronoun table the
        parser reads, so that "hug her" typed after watching Jessica act
        reaches Jessica. Noted from the bottom of the ranking up, so that the
        thing acted on wins "it" over the thing it was put on -- and the
        actor does not become "the last thing referred to", because "all of
        them" after watching somebody pick up a wrench means wrenches.
        """
        if not self.reads or self.event is None:
            return
        participants = self.event.participants()
        referents.was_told(self.viewer, participants)
        actor = self.event.actor
        for obj in reversed(participants):
            if obj is self.viewer:
                continue
            referents.note(self.viewer, obj, self.world_root,
                           last=obj is not actor)


def name_for(obj, viewer, role="", event=None):
    """
    What to call one participant, for one person reading, with no sentence
    around it -- so no centre and no pronoun. "You" for the reader, the name
    for everybody else. `render` is the version that knows the sentence.
    """
    return Naming(viewer, event, previous=[]).name(obj, role)


def conjugate(verb, subject, viewer, world_root=None):
    """
    A verb agreeing with its subject, as this reader would see it.

    "hands" for one person, "hand" for a they/them character or a pile of
    coins, "hand" for the reader themselves. Only the first word is touched;
    "pick up" comes back "picks up". Evennia's conjugator does the English,
    and a verb it cannot place gets the plain third-person suffix rather
    than nothing at all.
    """
    verb = str(verb or "").strip()
    if not verb:
        return ""
    head, _, tail = verb.partition(" ")
    if subject is not None and subject is viewer:
        word = _stance(head, False)[0]
    else:
        plural = bool(pronoun_forms(subject, world_root).get("plural")) \
            if subject is not None else False
        word = _stance(head, plural)[1]
    return f"{word} {tail}".strip()


def _stance(verb, plural):
    """(second person, third person) for one word."""
    try:
        from evennia.utils.verb_conjugation.conjugate import (
            verb_actor_stance_components)

        second, third = verb_actor_stance_components(verb, plural=plural)
        return str(second or verb), str(third or verb)
    except Exception:
        return verb, verb if plural else f"{verb}s"


def render(template, viewer, event, previous=None):
    """
    The template as this viewer should read it.

    Verbs agree first, then names are chosen, then the reader's table is
    told what they saw -- the one side effect, and only for a reader who is
    somebody. A regex rather than `str.format_map`, because a template is
    often a sentence a model wrote and a stray brace in it must not raise in
    the middle of delivering something that already happened. A slot naming
    nothing is left alone and caught by the structural test rather than shown
    with a guess in it.

    `previous` overrides what the reader was last shown; for tests of the
    rule, and for nothing else.
    """
    mapping = event.mapping()
    naming = Naming(viewer, event, previous)

    def agree(match):
        verb, _, role = match.group(1).partition(",")
        role = role.strip() or "actor"
        return conjugate(verb, mapping.get(role), viewer, naming.world_root)

    def fill(match):
        role = match.group(1)
        if role not in mapping:
            return match.group(0)
        possessive = bool(match.group(2) or match.group(3))
        # "{target's} {direct}", "{target's} own {direct}": a thing that
        # follows a possessive in the same clause is already determined, and
        # "her the sword" is not English.
        clause = re.split(r"[.,;:!?]", text[:match.start()])[-1]
        determined = bool(re.search(r"(?:'s\}|\}'s)\s+(?:\w+\s+){0,2}$", clause))
        return naming.name(mapping[role], role, possessive,
                           bare=determined)

    text = _CONJ.sub(agree, str(template or ""))
    text = _SLOT.sub(fill, text)
    if text.strip():
        naming.remember()
    return text[:1].upper() + text[1:] if text[:1].islower() else text


# ---------------------------------------------------------------------------
# Delivering
# ---------------------------------------------------------------------------

def deliver(event, to_actor=True):
    """
    Tell everybody what happened, each in their own words.

    The actor reads their own line, which is already second person and needs
    no rendering -- and establishes no centre, so a player acting alone has
    no narration centre at all. Everybody else gets the template rendered for
    them, one at a time, which is what makes "She hands you the sword"
    possible from one cached template.
    """
    actor, room = event.actor, event.room

    if to_actor and event.actor_text and actor is not None:
        actor.msg(event.actor_text)

    if not event.seen or room is None:
        return

    template = repair(event.room_template)
    show_the_room(event, template)
    _tell_the_characters(event, template)


def show_the_room(event, template=None):
    """
    Everybody present but the actor reads the template in their own words.

    The loop and nothing else -- no memory, no NPC reactions -- so that a
    caller with its own arrangements for those (an NPC acting, which
    witnesses through a depth-capped path) can still have each watcher told
    in their own words rather than one sentence broadcast to all of them.
    """
    actor, room = event.actor, event.room
    if room is None:
        return
    if template is None:
        template = repair(event.room_template)
    for viewer in list(getattr(room, "contents", []) or []):
        if viewer is actor or not hasattr(viewer, "msg"):
            continue
        line = render(template, viewer, event)
        if line:
            viewer.msg(line)


def show(actor_text, event=None, actor=None):
    """
    Deliver whatever a verb came to, whichever shape it came in.

    The one call every consumer makes, because there are three shapes and no
    consumer should have to know which it has: nothing visible (a refusal),
    one event, or a bulk action's worth of them. Keeping the fan-out here is
    what let `on_message` change from two strings to a fact without every
    caller learning what a fact is.
    """
    if isinstance(event, (list, tuple)):
        deliver_many(event, actor_text=actor_text, actor=actor)
        return
    if event is None:
        if actor_text and actor is not None:
            actor.msg(actor_text)
        return
    if actor_text:
        event.actor_text = actor_text
    deliver(event)


def deliver_many(events, actor_text="", actor=None, room=None):
    """
    A bulk action's worth of events, as one answer rather than a dozen.

    Eating everything on the table is a dozen actions and one thing that
    happened, and the room hears about it once. Joined per viewer rather than
    once for everybody, because that is the whole point: each of them may be
    reading a different set of names -- and rendered in order, so the second
    line knows the first was read: "Jessica drops the mug. She drops the
    plate."
    """
    events = [event for event in events if event is not None and event.seen]
    if actor is None and events:
        actor = events[0].actor
    if room is None and events:
        room = events[0].room

    if actor_text and actor is not None:
        actor.msg(actor_text)
    if not events or room is None:
        return

    templates = [repair(event.room_template) for event in events]
    for viewer in list(getattr(room, "contents", []) or []):
        if viewer is actor or not hasattr(viewer, "msg"):
            continue
        lines = [render(template, viewer, event)
                 for template, event in zip(templates, events)]
        spoken = " ".join(line for line in lines if line)
        if spoken:
            viewer.msg(spoken)

    for template, event in zip(templates, events):
        _tell_the_characters(event, template)


def _tell_the_characters(event, template):
    """
    Let the people here notice, with the facts rather than the sentence.

    `notify_npcs` has always been handed the room's prose, which a model then
    reads back to work out what occurred -- paying for a parse of a sentence
    this code wrote. It is given the event now; what it does with it is its
    own business, and the prose is still there for the part of it that is
    genuinely about words. Rendered for nobody, so it carries names and no
    pronouns: a model reading it has no attention to resolve them with.
    """
    from world.npc_gen import notify_npcs

    actor, room = event.actor, event.room
    if actor is None or room is None:
        return
    spoken = render(template, None, event)
    notify_npcs(room, "action", name_for(actor, None), spoken,
                exclude=actor, actor=actor)
