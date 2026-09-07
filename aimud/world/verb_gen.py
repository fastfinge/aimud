"""
Learning what a verb does, and describing what happened.

Two model calls with very different lifetimes, which is the point:

* A *rule* says what "read" does to anything readable -- its preconditions,
  its effects, whether it can be repeated.  It is cached per world against
  the verb and the affordances of the things it acts on, so learning to read
  a flyer teaches the world to read posters too.  It never mentions a room.

* A *narration* says what is written on this particular poster.  That is a
  property of the object, so it is cached on the object and travels with it.

Splitting them is what fixes results that only made sense where they were
first produced: the part that generalises is stored by kind, the part that is
specific is stored on the specific thing, and neither is stored on the room.
"""

import json
import re
import urllib.request

from twisted.internet import threads

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_RULE_SYSTEM = """You define what a verb does in a text MUD, as a reusable rule.

Respond with a single JSON object — no other text — matching:
{
  "valid": true,
  "reason": "if invalid, one sentence on why",
  "requires": {"<role>": {"has": ["affordance"], "is": ["state"], "lacks": ["state"], "holds": ["item name"], "trait": {"stamina": {"min": 10}}}},
  "effects": [ ... ],
  "new_states": [{"slug": "burning", "means": "on fire", "group": "fire"}],
  "new_traits": [{"slug": "stamina", "name": "Stamina", "means": "how much effort is left in someone", "trait_type": "gauge", "base": 100, "min": 0}],
  "repeatable": true
}

You are defining the verb for EVERY object of this kind, not for one object in
one place. Never refer to a room, a location, or anything you were not told is
part of the objects themselves. If the action only makes sense somewhere
specific, it is not a rule — mark it invalid.

Roles are the parts the player named: "direct" is the thing acted on,
"instrument" the thing used, "target" what it is applied to, "container",
"source". "actor" is the character acting.

requires are the conditions that must hold before the verb works:
  has    — an affordance the object must have (readable, flammable, openable)
  is     — a state it must be in (open, lit, wet)
  lacks  — a state it must NOT be in (already burning, already open)
  holds  — something the actor must be carrying
  trait  — a figure the character must reach: {"stamina": {"min": 10}}, or
           {"reputation": {"max": 0}}. Only people have traits, so this
           belongs on "actor" or on a role that is a character.

effects change the world. Each is one of:
{"type": "set_state", "role": "direct", "add": ["burning"], "remove": ["dry"]}
  (role may be "actor" to change the character acting)
{"type": "create_object", "name": "...", "description": "...", "takeable": true, "affordances": [...], "states": [...], "location": "room|actor"}
{"type": "destroy_object", "name_role": "direct"}
{"type": "move_object", "name_role": "direct", "to": "actor|room"}
{"type": "modify_object", "name_role": "direct", "new_name": "...", "new_description": "..."}
{"type": "move_actor", "exit": "north"}
{"type": "set_trait", "role": "actor", "trait": "stamina", "change": -5}
{"type": "set_trait", "role": "actor", "trait": "poisoned", "set_to": 20, "rate": -1}

set_trait changes a figure about a person. "change" moves it by an amount,
"set_to" puts it at one. "rate" is change per second from then on, and is how
an effect plays out over time instead of all at once: a poison that drains at
-1 a second, a rest that restores at +2, a skill going slowly rusty. Set rate
back to 0 to stop it. Use set_trait for anything that is true of a character
by degree — effort spent, harm taken, practice gained, standing won or lost.

Prefer set_state over destroying and recreating things. Use an empty effects
list for a verb that only produces a sensation.

new_states declares any state slug you used that may not exist yet: give its
meaning, and its "group" if it belongs to one. Reuse the existing vocabulary
when it already covers what you mean.

new_traits declares any trait you used that may not exist yet. trait_type is
one of:
  counter — a number that moves from a base, up and down. Skills, standing,
            tallies. The usual choice.
  gauge   — something depletable that refills to a maximum. Health, stamina.
  static  — a fixed figure nothing but deliberate change moves.
Give "base" (where it starts), and "min"/"max" where there are limits.

You may also give "descs": the words this world uses for standing at a figure,
as {number: "word"} from smallest to largest. Each number is the TOP of the
band it names, so {0: "hopeless", 10: "trained", 40: "dangerous"} calls 5
trained and 17 dangerous. These are what a player is shown, so they are worth
giving for anything a character would describe in words rather than digits.

Reusing an existing trait matters more than any other reuse here. A world
where one character has "magic" and another "mana" has two half-working
systems and no working one, and rules written against either will fail on
half the people they meet. If the register below already has a trait for what
you mean, use that name exactly, even if you would have called it something
better.

A group is a set of states only one of which can be true at once, so you do
not have to list what a state cancels -- membership does it. "posture" holds
seated, standing, lying, kneeling and the like, and ends when the character
walks anywhere, so never write a rule that removes a posture on movement or
requires the actor to not be standing before sitting; that is handled.

Wearing is handled too, and is not a verb you define. The game already knows
what it means to put a garment on, take it off, cover it or uncover it, and
tracks who is wearing what. So never invent a "worn", "wearing", "equipped" or
"dressed" state, never write an effect that moves clothing onto a character to
represent wearing it, and never require an actor to be wearing something. If
the verb you are given is only a way of saying "put this on", mark it invalid.
Return only the JSON object."""

_NARRATION_SYSTEM = """You narrate the result of an action in a text MUD.

Respond with a single JSON object — no other text — matching:
{"actor": "what the acting character experiences, 1-3 sentences",
 "room": "one full sentence others in the room see, beginning {actor}"}

Write only from the character and the objects involved. Do NOT mention the
room, the location, the surroundings, the weather, or anything you were not
given — this text is stored on the object and will be shown again wherever
that object later turns up.

"actor" is second person, addressed to whoever acted: "You unfold the flyer
and the ink has run."

"room" is third person and MUST refer to the acting character as the literal
placeholder {actor}, never by a name and never as "he", "she" or "they" —
the game substitutes whoever really did it, which may be someone else
entirely when this text is shown again later. Write a whole sentence, not a
fragment: "{actor} unfolds a damp flyer and frowns at it." — not "unfolds a
damp flyer".

Both say what actually happened, including the outcome. Present tense."""


def _call_openrouter(api_key, model, messages):
    payload = {"model": model, "messages": messages}
    # The sampling settings chosen for this job ride on the model choice. See
    # world.model_params: only what the player actually set is sent.
    from world.model_params import of as _settings

    payload.update(_settings(model))
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())["choices"][0]["message"]["content"]


def _parse_json_object(content):
    try:
        return json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON in model response: {content!r}")
        return json.loads(match.group())


# ---------------------------------------------------------------------------
# Rule cache (per world, keyed by verb and the kind of thing acted on)
# ---------------------------------------------------------------------------

def get_rule(world_root, key):
    if not world_root:
        return None
    return (world_root.db.verb_rules or {}).get(key)


def store_rule(world_root, key, rule):
    if not world_root:
        return
    rules = dict(world_root.db.verb_rules or {})
    rules[key] = rule
    world_root.db.verb_rules = rules


def _lore(world_root, actor):
    """The world, and its rules, as they read to whoever is acting."""
    from world import lore

    return (f"{lore.description(world_root, actor)}\n\n"
            f"{lore.guidance_block(world_root, 'validation', actor)}").rstrip()


def _describe_objects(bound, actor):
    """What the model is allowed to know: the objects, and nothing else."""
    from world import verbs

    lines = [f"actor: {actor.get_display_name(actor)}"]
    for role, obj in sorted(bound.items()):
        marks = ", ".join(sorted(verbs.affordances(obj))) or "no special properties"
        condition = ", ".join(sorted(verbs.states(obj))) or "nothing notable"
        lines.append(
            f"{role}: {obj.key} — {obj.db.desc or '(no description)'}\n"
            f"    properties: {marks}\n    currently: {condition}"
        )
    return "\n".join(lines)


def _apply_renames(data, renames):
    """
    Rewrite a rule to use the trait names the world actually settled on.

    Folding "str" onto an existing "strength" achieves nothing if the rule
    that asked for it goes on being stored with "str" in its effects: it would
    change a trait nobody tests and require one nobody has. So the rule is
    rewritten to match the register before it is cached, once, here.
    """
    if not renames:
        return data

    for effect in data.get("effects") or []:
        try:
            slug = effect.get("trait")
        except AttributeError:
            continue
        if slug in renames:
            effect["trait"] = renames[slug]

    for needed in (data.get("requires") or {}).values():
        try:
            wanted = needed.get("trait") or needed.get("traits")
        except AttributeError:
            continue
        if not isinstance(wanted, dict):
            continue
        for asked, settled in renames.items():
            if asked in wanted:
                wanted[settled] = wanted.pop(asked)
    return data


def learn_rule(account, world_root, verb, bound, actor, raw, on_success, on_error):
    """Async. Work out what this verb does to things of this kind."""
    model = account.model_for("commands")
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    from world import traits, verbs

    vocab = verbs.vocabulary(world_root)
    vocab_text = "\n".join(
        f"  {slug}: {info.get('means','')} (cancels: {', '.join(info.get('conflicts') or []) or 'nothing'})"
        for slug, info in sorted(vocab.items())
    ) or "  (none yet)"

    messages = [
        {"role": "system", "content": _RULE_SYSTEM},
        {
            "role": "user",
            "content": (
                f"World: {_lore(world_root, actor)}\n\n"
                f"The player typed: '{raw}'\n"
                f"Verb: {verb}\n\n"
                f"Things involved:\n{_describe_objects(bound, actor)}\n\n"
                f"State vocabulary already in use:\n{vocab_text}\n\n"
                f"{traits.vocabulary_block(world_root)}"
                f"Define '{verb}' as a rule for objects like these."
            ),
        },
    ]

    def _done(content):
        try:
            data = _parse_json_object(content)
            for state in data.get("new_states") or []:
                verbs.register_state(
                    world_root,
                    str(state.get("slug", "")),
                    means=str(state.get("means", "")),
                    conflicts=[str(c) for c in state.get("conflicts", [])],
                    group=str(state.get("group", "")).strip().lower() or None,
                )
            # Registered before the rule is stored, so that a trait the rule
            # goes on to change is one the world knows about -- and so that
            # the next rule to be written is shown it and reuses the name.
            renames = {}
            for spec in data.get("new_traits") or []:
                asked = traits._slug(spec.get("slug", ""))
                settled = traits.register(
                    world_root, asked,
                    name=str(spec.get("name", "")),
                    means=str(spec.get("means", "")),
                    trait_type=str(spec.get("trait_type", "")).strip().lower()
                    or traits.DEFAULT_TRAIT_TYPE,
                    base=spec.get("base"), min=spec.get("min"),
                    max=spec.get("max"), rate=spec.get("rate"),
                    descs=spec.get("descs"),
                )
                if settled and settled != asked:
                    renames[asked] = settled
            data = _apply_renames(data, renames)
            on_success({
                "valid": bool(data.get("valid", True)),
                "reason": str(data.get("reason", "")).strip(),
                "requires": data.get("requires") or {},
                "effects": data.get("effects") or [],
                "repeatable": bool(data.get("repeatable", False)),
            })
        except Exception as exc:
            on_error(str(exc))

    threads.deferToThread(
        _call_openrouter, api_key, model, messages
    ).addCallbacks(_done, lambda f: on_error(f.getErrorMessage()))


def narrate(account, verb, bound, actor, raw, on_success, on_error):
    """Async. Describe this action on these particular objects."""
    model = account.model_for("commands")
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    messages = [
        {"role": "system", "content": _NARRATION_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Action: '{raw}' (verb: {verb})\n\n"
                f"Things involved:\n{_describe_objects(bound, actor)}\n\n"
                f"Narrate the result."
            ),
        },
    ]

    def _done(content):
        try:
            data = _parse_json_object(content)
            actor_text = str(data.get("actor", "")).strip()
            if not actor_text:
                raise ValueError("empty narration")
            on_success(actor_text, str(data.get("room", "")).strip())
        except Exception as exc:
            on_error(str(exc))

    threads.deferToThread(
        _call_openrouter, api_key, model, messages
    ).addCallbacks(_done, lambda f: on_error(f.getErrorMessage()))
