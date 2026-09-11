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
That is twenty lines, and they are here. `msg_contents` stays exactly right
for everything that is not an action.

**Nothing here decides to use a pronoun yet.** Every viewer gets the name,
which is what the old code did, so this phase changes what the code knows and
not what anybody reads. P4 changes `name_for`, in one place, and nothing else
moves.
"""

import re

#: The roles a narration can name, in the order they rank.
#:
#: Grammatical role order, which is what centering theory ranks by and what
#: P4's rule reads: the subject outranks the object, the object outranks
#: everything oblique. Nothing reads it today except `participants`, and it is
#: asserted in the tests anyway -- a ranking nobody checks is one that drifts.
RANK = ("actor", "direct", "target", "container", "source", "instrument")

#: A placeholder in a narration template: `{actor}`, `{direct}`.
_SLOT = re.compile(r"\{(\w+)\}")


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

        The order P4's centering rule reads. `viewer` is accepted and unused
        for the same reason `choosing.ask` takes an `on_chosen` it ignores:
        it is what the caller will pass when the rule arrives, and taking it
        now means today's callers are the ones that still work.
        """
        mapping = self.mapping()
        found = [mapping[role] for role in RANK if role in mapping]
        for role, obj in sorted(mapping.items()):
            if role not in RANK and obj not in found:
                found.append(obj)
        return found

    def __repr__(self):
        return (f"<Event {self.verb!r} by {getattr(self.actor, 'key', None)!r}"
                f" {self.outcome}>")


def repair(template):
    """
    A narration template with a subject, whatever the model sent back.

    A reply of "lights the candle." must not be broadcast with nobody attached
    to it. Repaired rather than refused, because the alternative is losing an
    action that really happened -- and repaired on the TEMPLATE rather than on
    a rendered sentence, so the fix is stored and every later viewer gets it
    too.
    """
    text = str(template or "").strip()
    if not text:
        return ""
    if "{" in text:
        return text
    return f"{{actor}} {text}" if text[:1].islower() else text


def name_for(obj, viewer, role="", event=None):
    """
    What to call one participant, for one person reading.

    The single place a name is chosen, and the whole reason the loop below is
    ours. Today it is always the name, which is what every site did before.
    P4 makes it answer "she" where the reader is already thinking about her,
    and nothing outside this function has to change for that.
    """
    if obj is None:
        return ""
    if obj is viewer:
        return "you"
    try:
        return obj.get_display_name(viewer)
    except AttributeError:
        return str(getattr(obj, "key", obj))


def render(template, viewer, event):
    """
    The template as this viewer should read it.

    A regex rather than `str.format_map`, because a template is often a
    sentence a model wrote and a stray brace in it must not raise in the
    middle of delivering something that already happened. A slot naming
    nothing is left alone and caught by the structural test rather than shown
    with a guess in it.
    """
    mapping = event.mapping()

    def fill(match):
        role = match.group(1)
        if role not in mapping:
            return match.group(0)
        return name_for(mapping[role], viewer, role, event)

    text = _SLOT.sub(fill, str(template or ""))
    return text[:1].upper() + text[1:] if text[:1].islower() else text


def deliver(event, to_actor=True):
    """
    Tell everybody what happened, each in their own words.

    The actor reads their own line, which is already second person and needs
    no rendering. Everybody else gets the template rendered for them, one at a
    time -- which is what makes "She hands you the sword" possible later, and
    what makes it possible without a second visit to every site that raises an
    event.
    """
    actor, room = event.actor, event.room

    if to_actor and event.actor_text and actor is not None:
        actor.msg(event.actor_text)

    if not event.seen or room is None:
        return

    template = repair(event.room_template)
    for viewer in list(getattr(room, "contents", []) or []):
        if viewer is actor or not hasattr(viewer, "msg"):
            continue
        line = render(template, viewer, event)
        if line:
            viewer.msg(line)

    _tell_the_characters(event, template)


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
    reading a different set of names.
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
    genuinely about words.
    """
    from world.npc_gen import notify_npcs

    actor, room = event.actor, event.room
    if actor is None or room is None:
        return
    spoken = render(template, None, event)
    notify_npcs(room, "action", name_for(actor, None), spoken,
                exclude=actor, actor=actor)
