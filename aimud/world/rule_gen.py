"""
Asking a world to write its own rules, one small one at a time.

The old question was "define this verb for every object of this kind, never
refer to a room, and if it only makes sense somewhere specific then mark it
invalid". It demanded a universal answer and refused the verb when no
universal answer existed, which is why 85 of 326 rules in the exported worlds
are permanent refusals and seven of those say, in as many words, that the verb
needed a place.

The new question is smaller in every direction. Here is what already applies,
in the order it applies. Here are the places you may file a rule, as a list of
identifiers. Write what is missing, and require only what is not required
already.

Three things follow from asking it that way.

**The hard judgement becomes multiple choice.** "How general is this?" is the
question a model is worst at and this design most depends on, and a menu of
closed identifiers is a much easier thing to answer than an invitation to
write prose that will drift.

**Nothing has to be right, only not wrong.** A rule that says too little is
repaired by adding another, because the check phase accumulates. That is why
the prompt shows what is already decided: not politeness, but so the model can
leave it alone.

**A model may say it cannot.** `cannot_say` is a permitted answer and it is
logged, which turns "what is the effect vocabulary missing" from an argument
into a measurement.
"""

from evennia.utils import logger

from world import llm, rulebooks

#: How far up the taxonomy a rule may be filed, by depth from the root. A
#: scope is too general exactly when it is too near the top, which makes the
#: taxonomy its own measure and saves anybody writing a list.
#:
#: Set by looking at where the useful scopes actually sit:
#:
#:     physical_entity.n.01     2   everything
#:     object.n.01              3   everything
#:     artifact.n.01            5   everything anybody made
#:     instrumentality.n.03     6   most objects in the game
#:     device.n.01              7   a real sort of thing
#:     container.n.01           7   a real sort of thing
#:     publication.n.01         9
#:     spacecraft.n.01         12
#:
#: Six is the line: it refuses the four that would put one rule over the whole
#: world, and offers the ones a rule is genuinely worth having about.
SCOPE_CEILING = 6

#: What a generated rule may say. Anything else is dropped and logged: a
#: condition nothing can evaluate and an effect nothing can apply are both
#: rules that will never do anything, and the place to catch them is here.
PHASES = rulebooks.PHASES
EFFECTS = ("set_state", "set_trait", "create_object", "destroy_object",
           "move_object", "modify_object", "modify_room", "move_actor",
           "set_exit", "describe", "try", "stop")


# ---------------------------------------------------------------------------
# Where a rule may be filed
# ---------------------------------------------------------------------------

def menu(world_root, bound=None, actor=None):
    """
    The scopes this attempt may file a rule against, most specific first.

    Every entry is `(token, what it is, scope)`. The token is what the model
    writes back, and it is an identifier the world already holds -- a synset,
    a zone id, or the word `world`. There is nothing to spell wrong and
    nothing to invent.
    """
    from world import kinds, lexicon, zones

    found, seen = [], set()

    def offer(token, said, scope):
        if token and token not in seen:
            seen.add(token)
            found.append((token, said, scope))

    for role in ("direct", "target", "instrument", "container", "source"):
        thing = (bound or {}).get(role)
        for kind in kinds.of(thing) if thing is not None else []:
            offer(kind, f"the {role} object, a {lexicon.word_of(kind)}",
                  {rulebooks.KIND: kind})
            for parent in _worth_offering(world_root, kind):
                offer(parent, f"... and what that is a sort of",
                      {rulebooks.KIND: parent})

    room = getattr(actor, "location", None)
    for kind in kinds.of(room) if room is not None else []:
        offer(kind, f"the sort of place you are in, a "
                    f"{lexicon.word_of(kind)}", {rulebooks.KIND: kind})

    zone_id = zones.slugify(getattr(room.db, "zone", "") or "") if room else ""
    while zone_id and zone_id != zones.ROOT:
        kind = zones.kind_of(world_root, zone_id)
        if kind:
            offer(kind, f"the sort of place you are in, a "
                        f"{lexicon.word_of(kind)}", {rulebooks.KIND: kind})
        offer(zone_id, f"this area, {zones.name_of(world_root, zone_id)}",
              {rulebooks.ZONE: zone_id})
        zone_id = zones.parent_of(world_root, zone_id)

    offer("world", "everywhere, in every part of this world",
          {rulebooks.WORLD: True})
    return found


def _worth_offering(world_root, kind):
    """
    The ancestors of a kind that are worth filing a rule against.

    Cut off above `SCOPE_CEILING`, because a rule filed at
    `physical_entity.n.01` is a rule about everything, and a model offered it
    will sometimes take it. The ceiling is the taxonomy's own depth, which is
    the natural measure: a scope is too general exactly when it is too near
    the root.
    """
    from world import kinds, lexicon

    out = []
    for parent in sorted(kinds.ancestors(world_root, kind),
                         key=lambda name: -len(lexicon.ancestors(name))):
        if parent == kind:
            continue
        if len(lexicon.ancestors(parent)) <= SCOPE_CEILING:
            continue
        out.append(parent)
    return out[:3]


def too_general(scope, world_root=None):
    """Whether a scope is nearer the root of the taxonomy than we allow."""
    from world import lexicon

    kind = (scope or {}).get(rulebooks.KIND)
    if not kind:
        return False
    depth = len(lexicon.ancestors(kind))
    return bool(depth) and depth <= SCOPE_CEILING


# ---------------------------------------------------------------------------
# Reading what came back
# ---------------------------------------------------------------------------

def validate(reply, offered, action):
    """
    The rules in a reply that are worth keeping, and what was wrong with the
    rest.

    Returns `(rules, complaints)`. Everything is checked against a closed list
    -- the scope against the menu it was offered, the phase against the four,
    every predicate and every effect type against what exists -- because a
    rule nothing can evaluate is a rule that will sit in the book forever
    doing nothing, and the cheapest place to catch it is before it is written
    down.
    """
    from world import conditions

    scopes = {token: scope for token, _said, scope in offered}
    kept, complaints = [], []

    try:
        given = list(reply.get("rules") or [])
    except AttributeError:
        return [], ["the reply was not a rule"]

    for entry in given:
        try:
            entry = dict(entry)
        except (TypeError, ValueError):
            complaints.append("a rule that was not an object")
            continue

        phase = str(entry.get("phase") or "").strip().lower()
        if phase not in PHASES:
            complaints.append(f"unknown phase {phase!r}")
            continue

        token = str(entry.get("scope") or "").strip()
        if token not in scopes:
            complaints.append(f"{token!r} was not one of the scopes offered")
            continue
        if too_general(scopes[token]):
            complaints.append(f"{token!r} is too near the top of the taxonomy")
            continue

        conds, bad = _clean_conditions(entry.get("conditions"), conditions)
        complaints += bad
        guards, bad = _clean_conditions(entry.get("when"), conditions)
        complaints += bad
        effects, bad = _clean_effects(entry.get("effects"))
        complaints += bad

        if phase == rulebooks.CHECK and not conds:
            complaints.append("a check rule that checks nothing")
            continue
        if phase in (rulebooks.CARRY_OUT, rulebooks.AFTER) and not effects:
            complaints.append(f"a {phase} rule that changes nothing")
            continue

        kept.append(rulebooks.blank(
            action=action, phase=phase, scope=scopes[token],
            about=str(entry.get("about") or "direct"),
            name=str(entry.get("name") or "").strip(),
            when=guards, conditions=conds, effects=effects,
            contest=entry.get("contest"), source="generated"))
    return kept, complaints


def _clean_conditions(given, conditions):
    """Conditions that name a predicate this game can actually test."""
    kept, complaints = [], []
    for entry in (given or []):
        try:
            entry = dict(entry)
        except (TypeError, ValueError):
            complaints.append("a condition that was not an object")
            continue
        name, _value = conditions.predicate_of(entry)
        if not name:
            complaints.append(f"a condition asking nothing: {entry}")
            continue
        kept.append(entry)
    return kept, complaints


def _clean_effects(given):
    """Effects of a type something knows how to apply."""
    kept, complaints = [], []
    for entry in (given or []):
        try:
            etype = str(dict(entry).get("type") or "")
        except (TypeError, ValueError):
            complaints.append("an effect that was not an object")
            continue
        if etype not in EFFECTS:
            complaints.append(f"no such effect as {etype!r}")
            continue
        kept.append(dict(entry))
    return kept, complaints


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------

_SYSTEM = """You add one or two rules to a text MUD that already has some.

Respond with a single JSON object — no other text:
{"rules": [{"phase": "check", "scope": "<one of the scopes offered>",
            "about": "direct", "name": "one short sentence",
            "conditions": [...], "effects": [...]}],
 "new_states": [{"slug": "powered", "means": "running under its own power",
                 "group": "power"}],
 "new_traits": [],
 "cannot_say": ""}

A rule is one small fact about when something works, what it does, or what
follows. Write the fewest that make this verb behave properly here. Two or
three is normal; one is common.

**phase** is one of:
  check      a reason it will not work. These accumulate: every check rule
             that applies must pass, so yours joins the ones already listed
             rather than replacing them. Needs "conditions".
  carry_out  what the verb actually does. Needs "effects".
  instead    this verb means something else here, and the ordinary meaning
             does not happen. Use it sparingly, and only when the meaning
             genuinely differs rather than the conditions.
  after      what follows once it has worked. Needs "effects".

**scope** says what your rule is about, and must be copied exactly from the
list offered. File it as generally as is *true*: a rule about opening that
holds for every container belongs on the container, not on this one chest.
File it narrowly when the fact is narrow.

**about** says which participant the scope is matched against: a role
("direct", "target", "instrument", "container", "source"), or "enclosure"
when the rule is about the place the character is standing in rather than a
thing they named. Getting this wrong is the difference between a rule about
the ship somebody is aboard and a rule about a model ship on a shelf.

**Require only what is not required already.** Everything listed as already
decided will be checked regardless. Restating it makes the refusal worse, not
safer.

{conditions}
{effects}
**new_states** declares any state slug your rules used that the vocabulary
below does not already have: its meaning, and its "group" if it belongs to
one. A group is a set of states only one of which can be true at a time, so
powering a thing on takes it out of whatever "power" state it was in without
any rule saying so. Reuse an existing state whenever one fits -- a second word
for a condition the world already has is two facts that cannot see each other.

**new_traits** does the same for a trait a condition or effect named, with
"slug", "name", "means" and "trait_type" ("counter" or "gauge").

If this verb needs something you cannot say with the conditions and effects
above, leave "rules" empty and put one sentence in "cannot_say" describing
what was missing. That is a useful answer and it is recorded; a rule that
pretends with the wrong effect is not.
"""

_CONDITIONS = """A condition is {"subject": ..., "<predicate>": ...}:
  {"subject": "direct", "is": ["powered"]}          it is in that state
  {"subject": "direct", "lacks": ["damaged"]}       it is not
  {"subject": "direct", "affords": ["read"]}        that can be done to it
  {"subject": "actor", "holds": ["direct"]}         they are carrying it
  {"subject": "actor", "wears": ["direct"]}         they have it on
  {"subject": "actor", "trait": "piloting", "min": 10}
  {"subject": {"enclosure": "<a kind>"}, "is": ["powered"]}
  {"subject": {"zone": true}, "lacks": ["port_closed"]}
  {"subject": "direct", "unbound": true}            nobody named one
Subjects are the roles, "actor", "here", {"enclosure": kind} or {"zone": true}.
"""

_EFFECTS = """An effect is one of:
  {"type": "set_state", "role": "direct", "add": ["powered"], "remove": []}
  {"type": "set_trait", "role": "actor", "trait": "stamina", "change": -5}
  {"type": "move_object", "name_role": "direct", "to": "actor"}
  {"type": "move_object", "name_role": "direct", "to": "<a room's name>"}
  {"type": "set_exit", "exit": "airlock", "to": "<a room's name>"}
  {"type": "create_object", "name": "...", "description": "..."}
  {"type": "destroy_object", "name_role": "direct"}
  {"type": "try", "action": "<verb>", "roles": {"direct": {"enclosure": "<kind>"}}}
"set_exit" changes where a way out of this room leads, and "move_object" with a
room's name sends a thing to another room entirely. Both name a room the way
somebody reading would -- its name, never a number -- and do nothing at all if
this world has no room by that name, so name one that exists.

"try" is how a verb typed with no object comes to have one: aboard a ship,
"launch" means launching the ship. Use it in an "instead" rule, guarded by
{"subject": "direct", "unbound": true} -- otherwise it fires when somebody
did name a thing, and powering a datapad would power the ship instead.
"""


def prompt(world_root, action, bound, actor, offered):
    """Everything the model is shown, assembled."""
    from world import actions, conditions, lore

    lines = [f'The player typed a verb this world has not settled: "{action}".']
    declared = actions.spec(world_root, action)
    if declared and declared.get("means"):
        lines.append(f'It means: {declared["means"]}')

    already = rulebooks.for_attempt(world_root, action, bound, actor)
    if already:
        lines.append("\nAlready decided, in the order it is decided:")
        for rule in already:
            said = rule.get("name") or (
                conditions.describe(rule["conditions"][0])
                if rule.get("conditions") else "")
            lines.append(f"  {rule['phase']:10} "
                         f"{rulebooks.said_scope(rule['scope'], world_root)}"
                         f" -- {said}")
    else:
        lines.append("\nNothing has been decided about it yet.")

    lines.append("\nFile each rule against exactly one of these, copied "
                 "exactly:")
    for token, said, _scope in offered:
        lines.append(f"  {token:22} {said}")

    if bound:
        from world.verb_gen import _describe_objects

        lines.append("\n" + _describe_objects(bound, actor))

    # The vocabulary a rule should be choosing from rather than adding to.
    # Shown in full for the same reason the old generator showed it: a state
    # that cannot be seen gets coined again under another name, and then a
    # thing is powered and inactive at once with neither word knowing the
    # other exists.
    from world import traits, verb_gen

    lines.append("\n" + verb_gen.state_block(world_root, bound)
                 + traits.vocabulary_block(world_root))
    lines.append("\n" + lore.description(world_root, actor))
    return "\n".join(lines)


def learn(account, world_root, action, bound, actor, on_success, on_error):
    """
    Async. Ask this world what `action` should do here, and file the answer.

    `on_success` is given the rules that were kept, which may be none: a
    model that says it cannot express something has answered, and the world
    goes on without a rule rather than with a wrong one.
    """
    try:
        api_key = account.get_openrouter_key()
    except ValueError as err:
        on_error(str(err))
        return
    model = account.model_for("commands")
    offered = menu(world_root, bound, actor)

    system = _SYSTEM.replace("{conditions}", _CONDITIONS) \
                    .replace("{effects}", _EFFECTS)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt(world_root, action, bound, actor,
                                           offered)},
    ]

    def answered(content):
        from world.model_json import parse_object

        try:
            reply = parse_object(content)
        except Exception as exc:
            on_error(str(exc))
            return
        cannot = str(reply.get("cannot_say") or "").strip()
        if cannot:
            logger.log_info(f"rule_gen: {action} cannot_say -- {cannot}")
        kept, complaints = validate(reply, offered, action)
        for complaint in complaints:
            logger.log_info(f"rule_gen: {action} dropped -- {complaint}")
        _register_states(world_root, reply)
        on_success([rulebooks.add(world_root, rule) for rule in kept])

    llm.fetch(llm.ask, api_key, model, messages,
              on_success=answered,
              on_error=lambda failure: on_error(failure.getErrorMessage()))


def _register_states(world_root, reply):
    """
    Any word the rules coined, entered in the world's vocabulary.

    Without this a rule can set a state the world has never heard of: the
    state works -- it is a string on an object -- but it has no meaning, no
    group, and nothing to stop the next rule coining a second word for it. The
    group matters most: it is what makes powering a thing on take it out of
    being off, with no rule saying so.
    """
    from world import traits, verbs

    for entry in (reply.get("new_states") or []):
        try:
            slug = str(entry.get("slug") or "").strip()
        except AttributeError:
            continue
        if not slug:
            continue
        verbs.register_state(
            world_root, slug,
            means=str(entry.get("means") or ""),
            conflicts=[str(c) for c in (entry.get("conflicts") or [])],
            group=str(entry.get("group") or "").strip().lower() or None,
            ends_on_move=entry.get("group_ends_on_move"),
            prevents_acting=entry.get("group_prevents_acting"),
            prevents_moving=entry.get("group_prevents_moving"),
            prevents_speaking=entry.get("group_prevents_speaking"))

    for entry in (reply.get("new_traits") or []):
        try:
            slug = str(entry.get("slug") or "").strip()
        except AttributeError:
            continue
        if not slug:
            continue
        traits.register(
            world_root, traits._slug(slug),
            name=str(entry.get("name") or ""),
            means=str(entry.get("means") or ""),
            trait_type=str(entry.get("trait_type") or "").strip().lower()
            or traits.DEFAULT_TRAIT_TYPE,
            base=entry.get("base"), min=entry.get("min"),
            max=entry.get("max"))
