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
import urllib.request

from evennia.utils import logger
from twisted.internet import threads

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_RULE_SYSTEM = """You define what a verb does in a text MUD, as a reusable rule.

Respond with a single JSON object — no other text — matching:
{
  "valid": true,
  "reason": "if invalid, one sentence on why",
  "requires": {"<role>": {"has": ["affordance"], "is": ["state"], "lacks": ["state"], "holds": ["direct" or "item name"], "trait": {"stamina": {"min": 10}}}},
  "check": {"trait": "swordsmanship", "against": {"role": "direct", "trait": "swordsmanship"}},
  "effects": [ ... ],
  "new_states": [{"slug": "burning", "means": "on fire", "group": "fire", "group_ends_on_move": false}],
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
  holds  — something the role must be carrying. Either a role ("direct"),
           meaning the thing itself must be in their hands, or the name of a
           separate item ("brass key"). Use the role whenever the condition is
           about the thing being acted on: throwing something requires holding
           that something, and naming it any other way is a condition no
           player can ever meet.
  trait  — a figure the character must reach: {"stamina": {"min": 10}}, or
           {"reputation": {"max": 0}}. Only people have traits, so this
           belongs on "actor" or on a role that is a character.

has, is, lacks and holds are always lists, including when the condition names
one thing: "holds": ["direct"], never "holds": "direct".

effects change the world. Each is one of:
{"type": "set_state", "role": "direct", "add": ["burning"], "remove": ["dry"]}
  (role may be "actor" to change the character acting)
{"type": "create_object", "name": "...", "description": "...", "takeable": true, "affordances": [...], "states": [...], "location": "room|actor"}
{"type": "destroy_object", "name_role": "direct"}
{"type": "move_object", "name_role": "direct", "to": "actor|room"}
{"type": "move_object", "name_role": "direct", "to": "container", "preposition": "in"}
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

move_object's "to" is "actor" (into their hands), "room" (onto the floor), or
the ROLE of another thing involved, in which case give a "preposition" saying
how it goes there: "in", "on", "under" or "behind". So a verb that tips a
drawer's contents onto a table moves them to that role with "on", and one that
posts a letter moves it to the box with "in". Never invent a state like
"in_box" or "on_table" to stand in for this -- where a thing is, is not a
property of the thing, and the game tracks it properly.

Putting something somewhere is not itself a verb you define. The game already
knows what `put`, `place` and `insert` mean, and that things go IN containers
and ON surfaces; if the verb you are given is only a way of saying "put this
there", mark it invalid. Define a verb when the placement is a *consequence*
of something else -- pouring, posting, sheathing, burying.

Prefer set_state over destroying and recreating things. Use an empty effects
list for a verb that only produces a sensation.

check is what makes a verb a gamble instead of a certainty, and is the one
thing here that decides whether this is a game. Give a check ONLY when a
capable person could plausibly fail and the failure would be interesting:
fighting, forcing, climbing, sneaking, stealing, persuading, working a
delicate craft under pressure. NEVER give one to a verb that simply works —
reading a notice, opening an unlocked door, smelling bread, sitting down.
Most verbs have no check at all; leave it out entirely for those.

  trait      — the actor's figure that decides it. Reuse an existing one.
  against    — for a contest against another person: the role they play and
               the trait of theirs that opposes. Use this whenever the verb is
               done TO somebody, so that a formidable opponent is genuinely
               harder than a feeble one and the same rule covers both.
  difficulty — a fixed number to beat instead, for a verb contested by the
               world rather than by a person. 10 is even odds for someone
               unpracticed, 15 is a real test, 20 is hard.

When you give a check, "effects" MUST be an object keyed by outcome instead of
a list:

  "effects": {"success": [ ... ], "failure": [ ... ],
              "critical_failure": [ ... ], "critical_success": [ ... ]}

"failure" must not be empty. A failure that costs nothing means the player
repeats the command until it works, which is worse than not rolling at all —
so spend a gauge, take a wound, break the tool, drop the thing, make a noise
somebody hears. "critical_failure" and "critical_success" are optional and
fall back to "failure" and "success" when you leave them out.

Without a check, "effects" stays a plain list and always happens, as before.

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

{naming_rule}
A group is a set of states only one of which can be true at once, so you do
not have to list what a state cancels -- membership does it. Give one whenever
a state is one of a set that answers the same question: open and closed are an
"openness", hot and cold a "temperature". That is the cheapest thing you can
write, and without it a thing can be open and closed at the same moment.

Add "group_ends_on_move": true only if standing up and walking away would end
it, the way sitting down ends when you leave the room. Almost nothing does. "posture" holds
seated, standing, lying, kneeling and the like, and ends when the character
walks anywhere, so never write a rule that removes a posture on movement or
requires the actor to not be standing before sitting; that is handled.

Holding a thing in your hands is handled too, and is not a verb you define.
The game knows what it means to wield, brandish or lower something, and tracks
what each character has in hand. So never invent a "wielded", "equipped",
"held" or "drawn" state and never write an effect that represents taking hold
of something; if the verb you are given is only a way of saying "take this in
hand", mark it invalid.

Nor is a thing's own worth a verb's business. What a sword or a breastplate
does for whoever has it is written on the item as a bonus and applies for
exactly as long as they wear or hold it — so never write a rule where drawing
a weapon or donning armour raises a trait, and never require the actor to be
holding a particular thing in order to be good at something. That is already
true of them while they hold it.

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

Both say what actually happened, including the outcome. Present tense.

You may be told the OUTCOME of the attempt. Write that outcome and no other.
A failure must NOT quietly accomplish the thing anyway: if the swing missed,
it missed, and the text says what went wrong instead. A critical failure went
wrong and cost the actor something; a critical success went better than they
had any right to expect. Say how close it was in the prose — a near miss and
a hopeless one do not read alike — but never mention dice, rolls, chances,
odds, numbers or traits, and never say the word "check". The character does
not know they were measured; they know the blade turned on a rivet."""


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
    """
    Parse a model response that should be a single JSON object.

    Delegates to world.model_json, which repairs the near-misses models make
    -- a trailing comma, a stray comment, an answer cut off mid-object --
    rather than losing a whole generation over one character.
    """
    from world.model_json import parse_object

    return parse_object(content)


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
    """
    What the model is allowed to know: the objects, and nothing else.

    Including where each one is relative to the others, and what it is holding.
    A rule about pouring a jug into a bowl cannot be written sensibly without
    knowing the bowl is a container and that it already has something in it,
    and a model told neither will invent a state to stand in for both.
    """
    from world import relations, verbs

    lines = [f"actor: {actor.get_display_name(actor)}"]
    for role, obj in sorted(bound.items()):
        marks = ", ".join(sorted(verbs.affordances(obj))) or "no special properties"
        condition = ", ".join(sorted(verbs.states(obj))) or "nothing notable"
        entry = (f"{role}: {obj.key} — {obj.db.desc or '(no description)'}\n"
                 f"    properties: {marks}\n    currently: {condition}")

        where = relations.context_line(obj, actor)
        if where:
            entry += f"\n    sitting: {where}"
        holding = []
        for preposition in relations.PREPOSITIONS:
            here = relations.contents(obj, preposition)
            if here:
                holding.append(f"{preposition} it: "
                               f"{', '.join(o.key for o in here)}")
        if holding:
            entry += f"\n    holding: {'; '.join(holding)}"
        lines.append(entry)
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

    from world import checks

    # Every branch, not only the successful one: a failure that costs stamina
    # has to spend the same stamina everything else measures.
    for effect in checks.every_effect(data.get("effects")):
        try:
            slug = effect.get("trait")
        except AttributeError:
            continue
        if slug in renames:
            effect["trait"] = renames[slug]

    # The trait a check rolls has to be renamed too, or the verb would be
    # contested by a figure nobody in this world has and every attempt would
    # roll from zero.
    check = data.get("check")
    if isinstance(check, dict):
        for holder in (check, check.get("against")):
            if not isinstance(holder, dict):
                continue
            if holder.get("trait") in renames:
                holder["trait"] = renames[holder["trait"]]

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

    from world import checks, traits, verbs

    vocab = verbs.vocabulary(world_root)
    # Each state is shown with the group it belongs to, and the groups are
    # listed again on their own, because a group can only be reused if it can
    # be seen. Left to guess, one rule called a group "power_state" and the
    # next "charge_status" -- so a thing could be active and uncharged at the
    # same moment, neither name knowing the other existed.
    vocab_text = "\n".join(
        f"  {slug}: {info.get('means','')}"
        f" (group: {verbs.group_of(world_root, slug) or 'none'};"
        f" cancels: {', '.join(info.get('conflicts') or []) or 'nothing'})"
        for slug, info in sorted(vocab.items())
    ) or "  (none yet)"
    group_text = ", ".join(sorted(verbs.groups(world_root))) or "(none yet)"

    messages = [
        {"role": "system",
         "content": _RULE_SYSTEM.replace(
             "{naming_rule}", verbs.naming_rule())},
        {
            "role": "user",
            "content": (
                f"World: {_lore(world_root, actor)}\n\n"
                f"The player typed: '{raw}'\n"
                f"Verb: {verb}\n\n"
                f"Things involved:\n{_describe_objects(bound, actor)}\n\n"
                f"State vocabulary already in use:\n{vocab_text}\n\n"
                f"State groups already in use, to be reused rather than "
                f"renamed: {group_text}\n\n"
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
                    ends_on_move=state.get("group_ends_on_move"),
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
            rule = {
                "valid": bool(data.get("valid", True)),
                "reason": str(data.get("reason", "")).strip(),
                "requires": data.get("requires") or {},
                "check": checks.clean(data.get("check")),
                "effects": data.get("effects") or [],
                "repeatable": bool(data.get("repeatable", False)),
            }
            # A contest the player can lose for free is one they will simply
            # retype until they win. Nothing is invented to fix it -- a
            # penalty no rule asked for is a mechanic nobody wrote -- but a
            # world quietly accumulating them is worth being able to find.
            if checks.free_to_fail(rule):
                logger.log_info(
                    f"verb rule {verb!r} is contested but failing it costs "
                    f"nothing; players can retry it for free"
                )
            on_success(rule)
        except Exception as exc:
            on_error(str(exc))

    threads.deferToThread(
        _call_openrouter, api_key, model, messages
    ).addCallbacks(_done, lambda f: on_error(f.getErrorMessage()))


def narrate(account, verb, bound, actor, raw, on_success, on_error, result=None):
    """
    Async. Describe this action on these particular objects.

    `result` is the roll, when the verb was contested, and decides what the
    text has to say happened. The caller files the answer under that outcome,
    so one lock keeps a description of being picked and a separate one of
    being snapped off in the barrel.
    """
    from world import checks

    model = account.model_for("commands")
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    hint = checks.narration_hint(result)
    messages = [
        {"role": "system", "content": _NARRATION_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Action: '{raw}' (verb: {verb})\n\n"
                f"Things involved:\n{_describe_objects(bound, actor)}\n\n"
                + (f"Outcome: {hint}\n\n" if hint else "")
                + "Narrate the result."
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
