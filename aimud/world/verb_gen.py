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

from evennia.utils.dbserialize import deserialize

from world import llm


_NARRATION_SYSTEM = """You narrate the result of an action in a text MUD, and say what it changed.

Answer by calling narrate, with:
  actor       what the acting character experiences, 1-3 sentences
  room        one full sentence others in the room see, beginning {actor} $pconj(verb)
  effects     only where this thing differs; see below
  difficulty  only where this thing differs; see below

You are writing about THESE things, not about their sort. The verb's rule
already says what the action means in general; what you add is what it does
to this particular thing, and how hard it is on this particular thing.

"effects" is what changes here, in the same form the rule uses. Leave it out
entirely to accept the rule's own effects unchanged, which is the ordinary
case and the right answer whenever nothing about this thing is special. Give
it only where this thing genuinely differs — opening this door reveals the
stairs, opening that one is barred from the far side.

The commonest reason to differ is AMOUNT. A rule says drinking costs thirst
and gains intoxication, and it had to pick one number for both; water and
neat spirits are not that number. Whenever the rule changes a figure by some
amount, ask what THIS thing would do, and give the whole effects list back
with your own amount if it differs. Zero is a real answer: water intoxicates
nobody.

"difficulty" is the number to beat for THIS thing, when the rule says the verb
is contested. A flimsy crate and a bank vault are both pried, and they are not
both a 15. Leave it 0 to accept whatever the rule set. 10 is even odds for
someone unpracticed, 15 a real test, 20 hard.

Never invent an effect that contradicts the rule, and never add a check to a
verb the rule left uncontested.

Write only from the character and the objects involved. Do NOT mention the
room, the location, the surroundings, the weather, or anything you were not
given — this text is stored on the object and will be shown again wherever
that object later turns up.

"actor" is second person, addressed to whoever acted: "You unfold the flyer
and the ink has run."

"room" is third person and is a TEMPLATE, not a finished sentence. The game
fills it in for each person watching, who may be told "she", "you" or a name
depending on what they were just looking at, and the same text is shown again
later when somebody else does this. So:

- Refer to the acting character ONLY as the literal placeholder {actor}. Never
  a name, never "he", "she" or "they".
- Refer to every other thing involved ONLY by its role placeholder — the
  user message lists them, such as {direct}, {target}, {container}, {source},
  {instrument}. Never write its name, and never "it", "him" or "them". Write
  the placeholder bare: the game supplies "the", so "{direct}" not "the
  {direct}". For a possessive write {actor's} or {target's}.
- Write every verb whose subject is {actor} as $pconj(verb), with the verb in
  its base form: "{actor} $pconj(unfold) {direct} and $pconj(frown) at it."
  The game conjugates it — "unfolds" for one person, "unfold" for someone who
  goes by they. Verbs about anything else are written normally.
- Write a whole sentence, not a fragment.

Right: "{actor} $pconj(hand) {target} {direct} without a word."
Wrong: "Jessica hands Britney the sword." — names; "{actor} hands {target}
the {direct}." — a conjugated verb and an article on a placeholder.

Both say what actually happened, including the outcome. Present tense.

You may be told the OUTCOME of the attempt. Write that outcome and no other.
A failure must NOT quietly accomplish the thing anyway: if the swing missed,
it missed, and the text says what went wrong instead. A critical failure went
wrong and cost the actor something; a critical success went better than they
had any right to expect. Say how close it was in the prose — a near miss and
a hopeless one do not read alike — but never mention dice, rolls, chances,
odds, numbers or traits, and never say the word "check". The character does
not know they were measured; they know the blade turned on a rivet."""


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
    """
    The rule this world has learned for that key, as plain Python.

    Decoupled from the database on the way out, and that is not tidiness. An
    Attribute hands back _SaverDict and _SaverList -- a MutableMapping and a
    MutableSequence, neither of them a dict or a list -- and a rule is nested:
    `requires` is a mapping, `effects` a list of mappings. Everything that
    merely reads a rule is happy with those; `json.dumps` is not, and refuses
    the whole structure with "Object of type _SaverDict is not JSON
    serializable".

    That matters because a rule goes into a prompt. `ask_admission` writes the
    verb's rule out as JSON, in the main thread, in the middle of building its
    message -- and a rule that would not serialise there used to end the
    attempt, and take the caller's hold on the object with it.

    A shallow `dict(rule)` at each such place looks like the fix and is not:
    it unwraps the outside and leaves every nested container exactly as it
    was. So it is done once, properly, here.
    """
    if not world_root:
        return None
    rule = (world_root.db.verb_rules or {}).get(key)
    return deserialize(rule) if rule is not None else None


def store_rule(world_root, key, rule):
    if not world_root:
        return
    rules = dict(world_root.db.verb_rules or {})
    rules[key] = rule
    world_root.db.verb_rules = rules


def _states_of_kinds(world_root, bound):
    """Conditions things of the sorts involved here have been in before."""
    from world import kinds

    seen = set()
    for obj in (bound or {}).values():
        seen |= kinds.states_of(world_root, getattr(obj.db, "kinds", None))
    return seen


def _placeholder_block(bound):
    """
    The placeholders this narration may use, and what each one stands for.

    Told rather than left to be inferred from the role names above, because a
    model shown "direct: sword" writes "the sword" far more readily than it
    writes "{direct}", and a name in the template is shown to everybody for
    ever -- the exact thing per-viewer rendering exists to prevent.
    """
    lines = ["{actor} — whoever did it"]
    for role, obj in sorted(bound.items()):
        if obj is None:
            continue
        lines.append(f"{{{role}}} — {getattr(obj, 'key', obj)}")
    return ("Placeholders for the \"room\" line (use these, never the names):\n  "
            + "\n  ".join(lines) + "\n\n")


def _describe_objects(bound, actor):
    """
    What the model is allowed to know: the objects, and nothing else.

    Including where each one is relative to the others, and what it is holding.
    A rule about pouring a jug into a bowl cannot be written sensibly without
    knowing the bowl is a container and that it already has something in it,
    and a model told neither will invent a state to stand in for both.
    """
    from world import relations, tokens, verbs

    lines = [f"actor: {actor.get_display_name(actor)}"]
    for role, obj in sorted(bound.items()):
        marks = ", ".join(sorted(verbs.affordances(obj))) or "no special properties"
        condition = ", ".join(sorted(verbs.states(obj))) or "nothing notable"
        entry = (f"{role}: {obj.key} — {tokens.text_of(obj) or '(no description)'}\n"
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


def state_block(world_root, bound=None):
    """
    The states this world already has, as a generator should be shown them.

    Shared by both generators, because they choose from the same vocabulary
    and the whole reason to show it is that a word not shown gets coined
    again under another name.

    Each state is shown with the group it belongs to, and the groups are
    listed again on their own, because a group can only be reused if it can
    be seen. Left to guess, one rule called a group "power_state" and the
    next "charge_status" -- so a thing could be active and uncharged at the
    same moment, neither name knowing the other existed.

    The conditions things of this sort have actually been in come first and
    separately. A world's vocabulary runs to sixty states before long, and
    sixty undifferentiated lines are not read -- which is how "shut" got
    coined beside "closed" and "dormant" beside "inactive". The handful that
    have ever been true of a bottle are worth putting in front of the rest.
    """
    from world import verbs

    vocab = verbs.vocabulary(world_root)

    def line(slug, info):
        return (f"  {slug}: {info.get('means','')}"
                f" (group: {verbs.group_of(world_root, slug) or 'none'};"
                f" cancels: {', '.join(info.get('conflicts') or []) or 'nothing'})")

    familiar = _states_of_kinds(world_root, bound)
    near_text = "\n".join(line(slug, vocab[slug])
                          for slug in sorted(familiar & set(vocab)))
    vocab_text = "\n".join(
        line(slug, info) for slug, info in sorted(vocab.items())
        if slug not in familiar
    ) or "  (none yet)"
    group_text = ", ".join(sorted(verbs.groups(world_root))) or "(none yet)"

    return (
        (f"Conditions things of this sort have been in before, and the ones "
         f"to reuse if any of them fit:\n{near_text}\n\n"
         if near_text else "")
        + f"Every other state this world uses:\n{vocab_text}\n\n"
        + f"State groups already in use, to be reused rather than renamed: "
          f"{group_text}\n\n")


_ADMISSION_SYSTEM = """You decide whether a sort of thing can be acted on at all.

Answer by calling admit.

You are told what a verb means in this world and asked about a KIND of thing,
not a particular one. So the question is never whether this bottle happens to
be burnable — it is whether a bottle, any bottle, is the sort of thing that
verb can be done to.

Be generous about what is possible and strict about what is meaningless.
A bottle can be burned (glass melts, labels char), a bottle can be thrown, a
bottle can be smelled. A bottle cannot be read, cannot be worn, cannot be
persuaded. If a player would expect something to happen, allow it.

Answer for the ordinary case. A locked door is still the sort of thing that
opens; being locked is a condition, and the game handles conditions.

PEOPLE ARE THE EXCEPTION TO THAT GENEROSITY, and the only one. A person can be
spoken to, greeted, followed, thanked, struck, healed, kissed, robbed -- all
the things one person does to another. A person is not material and not
scenery: they cannot be eaten, drunk, worn, read, opened, filled, planted,
sharpened, mined or harvested, however hungry anybody is. Refuse a verb that
treats a person as a substance, a container, a surface or a tool. Everybody in
this game is somebody a player has met, which is why the line is drawn here and
nowhere else.

A verb that is only a figure of speech is not admitted either: you can lose
your temper, and you cannot lose it at a chair."""


def ask_admission(sponsor, world_root, verb, rule, kind, on_answer, on_error):
    """
    Async. Ask whether a kind of thing can be verbed at all, and remember it.

    One bit, once, per kind and verb. This is what replaced generating a whole
    rule every time an object said nothing about the verb being tried -- which
    was 86% of every rule five worlds had learned, each one a large JSON
    invented to answer a yes-or-no question.

    The verb's own rule goes into the prompt, which is what keeps the answer
    about mechanism rather than about vibes: "can a bottle be burned" is a
    different question depending on whether burning, in this world, means
    catching fire or means being consumed utterly.
    """
    model = sponsor.model_for("commands")
    try:
        sponsor.key()          # refuse early rather than mid-prompt
    except ValueError as e:
        on_error(str(e))
        return

    means = ""
    if rule:
        try:
            means = json.dumps(dict(rule), indent=2)
        except Exception:
            means = ""

    # Asked in English rather than in synset ids. `person.n.01` names a sense
    # and is not a word anybody uses, so "Can a person.n.01 be eaten?" asks a
    # model to do lexicography before it can answer the question. The gloss
    # comes with it, being the whole of what the sense means and free to send.
    from world import lexicon

    word = lexicon.word_of(kind) or str(kind)
    gloss = lexicon.definition(kind)
    asked = f"a {word} ({gloss})" if gloss else f"a {word}"

    messages = [
        {"role": "system", "content": _ADMISSION_SYSTEM},
        {
            "role": "user",
            "content": (
                (f"In this world, '{verb}' means:\n{means}\n\n"
                 if means else "")
                + f"Can {asked} be {verb}ed?"
            ),
        },
    ]

    from world import toolbox as tb

    box = tb.Toolbox([tb.Tool(
        "admit", f"Say whether {asked} can be {verb}ed at all.",
        tb.params({"allowed": {"type": "boolean",
                               "description": f"Whether that sort of thing "
                                              f"can be {verb}ed"},
                   "reason": {"type": "string", "description": "A few words"}},
                  ["allowed"]),
        lambda ctx, args, answer: answer(tb.accept(args)), finishes=True)],
        tb.ToolContext(world_root=world_root, sponsor=sponsor, job="commands"))

    def _done(data):
        on_answer(bool(data.get("allowed")), str(data.get("reason") or ""))

    llm.converse(sponsor, model, messages, box, on_done=_done,
                 on_error=on_error,
                 on_exhausted=lambda _last: on_error(
                     f"no answer came back about whether {asked} can be "
                     f"{verb}ed"),
                 rounds=ADMISSION_ROUNDS)


def narrate(sponsor, verb, bound, actor, raw, on_success, on_error, result=None):
    """
    Async. Describe this action on these particular objects.

    `result` is the roll, when the verb was contested, and decides what the
    text has to say happened. The caller files the answer under that outcome,
    so one lock keeps a description of being picked and a separate one of
    being snapped off in the barrel.
    """
    from world import checks

    model = sponsor.model_for("commands")
    try:
        sponsor.key()          # refuse early rather than mid-prompt
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
                f"{_placeholder_block(bound)}"
                + (f"Outcome: {hint}\n\n" if hint else "")
                + "Narrate the result."
            ),
        },
    ]

    from world import toolbox as tb

    room = getattr(actor, "location", None)
    world_root = getattr(room.db, "world_root", None) if room is not None \
        else None
    box = tb.Toolbox([narration_tool(bound, actor)],
                     tb.ToolContext(world_root=world_root, room=room,
                                    actor=actor, bound=bound, sponsor=sponsor,
                                    job="commands"))

    def _done(data):
        data = data if isinstance(data, dict) else {}
        try:
            actor_text = str(data.get("actor") or "").strip()
            if not actor_text:
                raise ValueError("the narrator said nothing about what "
                                 "happened")
            # What this thing in particular does, riding the call that was
            # being made anyway. A narration is already written per object and
            # per outcome; asking the same reply what it changed here is not a
            # second round trip, and it is the only place a difference between
            # two doors can honestly live.
            specifics = {}
            if data.get("effects") is not None:
                specifics["effects"] = data.get("effects")
            try:
                difficulty = int(data.get("difficulty") or 0)
            except (TypeError, ValueError):
                difficulty = 0
            if difficulty > 0:
                specifics["difficulty"] = difficulty
            room_text = str(data.get("room") or "").strip()
        except Exception as exc:
            on_error(str(exc))
            return
        on_success(actor_text, room_text, specifics)

    # Rounds out, the last narration is taken as it stands. A narration a
    # little wrong is better than an action that happened and says nothing,
    # and `events.repair` still runs on it on the way in.
    llm.converse(sponsor, model, messages, box, on_done=_done,
                 on_error=on_error, on_exhausted=_done,
                 rounds=NARRATION_ROUNDS)


# ---------------------------------------------------------------------------
# The finish tools (docs/generator-tool-loops.md §4.2)
# ---------------------------------------------------------------------------

#: Rounds each may take (§10.3). Admission is a yes or no a player waits on.
ADMISSION_ROUNDS = 4
NARRATION_ROUNDS = 6

#: A placeholder in a room line: `{direct}`, or `{actor's}` for a possessive.
_SLOT = re.compile(r"\{(\w+?)(?:'s)?\}")


def narration_tool(bound, actor):
    """`narrate`, the finish tool a narration answers with."""
    from world import effects as effects_mod
    from world import toolbox as tb

    def parameters(ctx):
        return tb.params({
            "actor": {"type": "string",
                      "description": "What the acting character experiences, "
                                     "1-3 sentences, second person"},
            "room": {"type": "string",
                     "description": "One sentence for everyone else, as a "
                                    "template: " + _placeholders(bound)},
            "effects": {"type": "array", "items": effects_mod.schema(ctx),
                        "description": "Only where this thing differs from "
                                       "the rule; the whole list, with your "
                                       "amounts"},
            "difficulty": {"type": "integer", "minimum": 0,
                           "description": "Only for a contested verb: the "
                                          "number to beat for this thing; 0 "
                                          "keeps the rule's"},
        }, ["actor"])

    def handler(ctx, args, answer):
        said = narration_complaints(args, bound, actor)
        if said:
            answer(tb.complain("Not taken: " + "; ".join(said) + ". Send the "
                               "narration again with that put right.",
                               value=args))
            return
        answer(tb.accept(args))

    return tb.Tool("narrate", "Say what happened, and what it changed here.",
                   parameters, handler, finishes=True)


def _placeholders(bound):
    roles = ["{actor}"] + [f"{{{role}}}" for role, obj in
                           sorted((bound or {}).items()) if obj is not None]
    return ", ".join(roles)


def narration_complaints(args, bound, actor):
    """
    What is wrong with a narration that can be put right by asking, as short
    phrases; [] when nothing is.

    Only what `events.repair` cannot mend on its own. An article before a
    placeholder and a conjugated actor verb are repaired on the way in for
    nothing, so they are not worth a round a player waits for. A name written
    out, a placeholder for nobody, and an effect nothing can apply are not
    repairable: a name is shown for ever to people who know that person by
    another, and an unknown placeholder renders as itself.
    """
    from world import effects as effects_mod

    said = []
    room = str(args.get("room") or "")
    if room:
        allowed = {"actor"} | {role for role, obj in (bound or {}).items()
                               if obj is not None}
        strange = sorted({name for name in _SLOT.findall(room)
                          if name not in allowed})
        if strange:
            said.append("the room line uses "
                        + ", ".join(f"{{{name}}}" for name in strange)
                        + ", which stand for nobody here; the placeholders "
                          "are " + _placeholders(bound))
        named = []
        for obj in [actor, *(bound or {}).values()]:
            key = str(getattr(obj, "key", "") or "")
            if key and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", room,
                                 re.IGNORECASE):
                named.append(key)
        if named:
            said.append("the room line names " + ", ".join(named)
                        + "; write the placeholder instead")
    for effect in args.get("effects") or []:
        kind = str(effect.get("type") or "") if isinstance(effect, dict) \
            else ""
        if kind not in effects_mod.VOCABULARY:
            said.append(f"there is no such effect as {kind!r}")
    return said
