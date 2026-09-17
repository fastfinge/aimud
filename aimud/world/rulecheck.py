"""
What a world's own rules say about each other, read without asking anybody.

Everything here is inference over registers a world already holds. No model, no
corpus, no network -- which is why it can run on a timer, at server start, or
over a fixture in a test, and why it was worth building before the rulebook
change rather than after it.

It finds faults that are invisible while a world is being played and fatal to it
afterwards. Measured across the seven exported worlds:

    72% of every state a rule can set, no rule can unset
    7 states are required by some rule and settable by none

A lamp that can be lit and never put out. A door that opens and never closes.
And rules that wanted `closed` or `unlit`, which can never fire however long
anybody plays, because nothing in the world can bring that condition about.

Those two findings are usually **the same missing rule seen from both ends**, and
saying so is the most useful thing this module does. A world that groups `open`
and `closed` as one exclusive condition has told us they are a pair; if one is
set-and-never-unset while the other is wanted-and-never-settable, the gap between
them is a single rule nobody ever wrote, and `pairs` names it.

The output is a report rather than a repair. Nothing here writes a rule -- see
the plan's phase 10 for the half that proposes one -- and nothing here costs
anything, so the worst it can do is tell somebody something true.
"""

import re

#: Why a rule was refused, as far as its own sentence admits. Three buckets,
#: because they mean three different things: the first is a verb the engine
#: already answers and is mostly an old wound, the second is the gap the rulebook
#: change exists to close, and the third is the system working correctly.
_ENGINE = re.compile(
    r"\b(already (?:handle|handles|handled|knows|know)|native|engine|built-in"
    r"|core (?:action|game)|fundamental|standard)\b", re.I)
_PLACE = re.compile(
    r"\b(location|locations|room|rooms|place|places|surrounding|surroundings"
    r"|environment|establishment|vendor|fountain|context|situational"
    r"|specific (?:place|location|setting)|depends on)\b", re.I)

REFUSAL_KINDS = ("engine already does it", "needs a place or a context",
                 "genuinely implausible")


# ---------------------------------------------------------------------------
# Reading a world, from either of the two places one can be
# ---------------------------------------------------------------------------

#: What a scan reads. Named so that the two readers below cannot disagree about
#: it. Both rule shapes are in here: `verb_rules` is one rule per verb per world
#: and `rules` is the rulebook, and a world mid-cutover holds some of each.
REGISTERS = ("verb_rules", "rules", "state_vocabulary", "state_groups",
             "kind_specs")


def of_world(world_root):
    """The registers of a live world, as plain Python."""
    from evennia.utils.dbserialize import deserialize

    if world_root is None:
        return {name: {} for name in REGISTERS}
    return {name: dict(deserialize(getattr(world_root.db, name, None)) or {})
            for name in REGISTERS}


def of_record(record):
    """The registers of an exported world. See tests/fixtures/export.py."""
    return {name: dict(record.get(name) or {}) for name in REGISTERS}


# ---------------------------------------------------------------------------
# Reading one rule
# ---------------------------------------------------------------------------

def effects_of(rule):
    """
    Every effect a rule can have, from whichever shape it stores them in.

    A contested rule keeps its effects keyed by outcome, so a scan that read
    only the list form would believe every rule with a check does nothing at
    all -- and contested rules are exactly the ones that change the most.
    """
    effects = rule.get("effects")
    if isinstance(effects, dict):
        found = []
        for branch in effects.values():
            found.extend(branch or [])
    else:
        found = list(effects or [])
    return [e for e in found if hasattr(e, "get")]


def _states(effect, field):
    return {str(s).lower().strip() for s in (effect.get(field) or []) if s}


def _required(rule, field):
    """Every state a rule's preconditions name under `field`."""
    found = set()
    for needed in (rule.get("requires") or {}).values():
        if not hasattr(needed, "get"):
            continue
        found |= {str(s).lower().strip() for s in (needed.get(field) or []) if s}
    return found


def verb_of(key):
    """The verb a rule is filed under, whatever the key's shape."""
    return str(key).split("#", 1)[0]


def as_verb_rule(rule):
    """
    One rulebook rule in the shape the scan reads.

    The scan asks two questions of a rule -- what states it can set, and what
    states it requires -- and both are answerable of either shape. What differs
    is only the spelling: a verb rule keeps its preconditions as a mapping of
    role to what that role must be, a rulebook rule as a list of conditions
    each naming its own subject. Translating is cheaper than scanning twice,
    and it means a finding reads the same whichever kind of rule produced it.

    A check rule has no effects and a carry-out has no conditions, which is the
    point of separating them -- so a rulebook rule contributes to one side of
    the ledger or the other, and the scan adds them up across the book.
    """
    from world import conditions as conditions_mod
    from world.model_json import listed

    requires = {}
    for top in (rule.get("conditions") or []):
        # Only what the rule demands. A state inside an `any` is one way of
        # passing among several, and counting it as required would call a
        # rule dead that another branch lets through.
        for condition, optional in conditions_mod.leaves(top):
            if optional or not hasattr(condition, "get"):
                continue
            subject = str(condition.get("subject") or "direct")
            entry = requires.setdefault(subject, {"is": [], "lacks": []})
            for field in ("is", "lacks"):
                entry[field] += [str(s) for s in listed(condition.get(field))]
    return {"valid": True,
            "requires": requires,
            "effects": rule.get("effects") or [],
            "check": rule.get("contest"),
            # Carried across so that `inert` can tell the two silences apart: a
            # check rule with no effects is doing its job, and a carry-out with
            # none is the fault this scan exists to name.
            "phase": rule.get("phase")}


def _both_shapes(registers):
    """
    Every rule this world holds, keyed by verb, in one shape.

    Rulebook rules are keyed `verb#rule_id` so that a key still says which verb
    it is about, which is all the scan wants a key for. A rule about every
    action -- `action` of None, which is how "nothing works while you are dead"
    is said once -- is filed under the empty verb rather than invented a name
    for.
    """
    found = dict(registers.get("verb_rules") or {})
    for rule_id, rule in sorted((registers.get("rules") or {}).items()):
        if not hasattr(rule, "get"):
            continue
        if not rule.get("listed", True):
            continue        # taken out of its rulebook; it applies to nothing
        action = str(rule.get("action") or "")
        found[f"{action}#{rule_id}"] = as_verb_rule(rule)
    return found


# ---------------------------------------------------------------------------
# The scan
# ---------------------------------------------------------------------------

def scan(registers):
    """
    Everything wrong, and the numbers behind it.

    Returns a dict of findings. Every list is sorted, so two runs over the same
    world produce the same report and a difference in one means a difference in
    the world.
    """
    rules = _both_shapes(registers)
    vocabulary = registers.get("state_vocabulary") or {}
    groups = registers.get("state_groups") or {}
    learned = set(registers.get("verb_rules") or {})

    added, removed, wanted, forbidden = set(), set(), set(), set()
    refusals = {kind: [] for kind in REFUSAL_KINDS}
    inert, accepted, contested = [], 0, 0
    by_verb = {}

    for key, rule in sorted(rules.items()):
        if not rule.get("valid", True):
            refusals[refusal_kind(rule)].append(verb_of(key))
            continue
        accepted += 1
        if rule.get("check"):
            contested += 1

        effects = effects_of(rule)
        if not effects and _should_do_something(rule, key in learned):
            inert.append(key)
        for effect in effects:
            if effect.get("type") == "set_state":
                added |= _states(effect, "add")
                removed |= _states(effect, "remove")
        wanted |= _required(rule, "is")
        forbidden |= _required(rule, "lacks")
        if key in learned:
            # `forked` is a question about the old cache key, and many rules
            # for one verb is what a rulebook is FOR -- so rulebook rules are
            # kept out of it rather than reported as the fault it used to be.
            by_verb.setdefault(verb_of(key), []).append((key, rule))

    # A state is unset by its own group as well as by a rule that says so.
    # `verbs.apply_states` clears every other member of an exclusive group when
    # one is set, so a world with rules for both `open` and `closed` has a way
    # back from each with neither rule carrying a `remove` list -- and reading
    # only the `remove` lists called 30 of 56 "one-way" states in the infinite
    # dungeon one-way when they were nothing of the sort. This scan's headline
    # figure was wrong in the direction that hides an improvement, which is the
    # worst direction for a ratchet to be wrong in.
    #
    # Kept separate from `touched`, which is a different question: "can this be
    # undone" is about the way back, and "has any rule ever mentioned this" is
    # about dead vocabulary. A word that is only ever cancelled by a sibling is
    # still a word nobody wrote a rule about.
    undone = removed | _cancelled(added, vocabulary, groups)

    one_way = added - undone
    unsettable = wanted - added
    touched = added | removed | wanted | forbidden

    return {
        "one_way": sorted(one_way),
        "unsettable": sorted(unsettable),
        "dead_vocabulary": sorted(set(vocabulary) - touched),
        "pairs": pairs(one_way, unsettable, vocabulary, groups),
        "self_defeating": self_defeating(registers.get("rules") or {}),
        "after_self_defeating": after_self_defeating(
            registers.get("rules") or {}),
        "ungrounded": ungrounded(registers.get("kind_specs") or {}),
        "inert": sorted(inert),
        "refusals": {kind: sorted(verbs) for kind, verbs in refusals.items()},
        "forked": forked(by_verb),
        "counts": {
            "rules": len(rules),
            "accepted": accepted,
            "refused": len(rules) - accepted,
            "contested": contested,
            "verbs": len({verb_of(key) for key in rules if verb_of(key)}),
            "filed": len([key for key in rules if key not in learned]),
            "states_set": len(added),
            "states_unset": len(undone),
            "vocabulary": len(vocabulary),
        },
    }


def _should_do_something(rule, learned):
    """
    Whether a rule with no effects is a fault or is simply not that sort of rule.

    An old-shape verb rule is one rule for a whole verb, so having no effects at
    all means the verb does nothing: 32% of the exported corpus, and one of the
    numbers this design claims it will improve.

    A rulebook rule is one of four kinds, and only two of them are supposed to
    change anything. A check rule with no effects is a well-written check; a
    carry-out with none is the same fault under a new name, and reporting the
    first would bury the second. The first draft of this scan excluded every
    rulebook rule to avoid that, which meant the measurement could not be taken
    on a world built by the new engine at all.
    """
    if learned:
        return True
    return str(rule.get("phase") or "") in ("carry_out", "after")


def refusal_kind(rule):
    """Which of REFUSAL_KINDS a refusal's own sentence puts it in."""
    said = str(rule.get("reason") or "")
    if _ENGINE.search(said):
        return REFUSAL_KINDS[0]
    if _PLACE.search(said):
        return REFUSAL_KINDS[1]
    return REFUSAL_KINDS[2]


def _cancelled(added, vocabulary, groups):
    """
    Every state that some rule undoes by setting a sibling of it.

    Exclusivity is the cheapest way back there is and the one a world gets for
    nothing: a group is a set of conditions only one of which can hold, so a
    rule that sets one has unset the rest whether or not it mentions them.
    """
    members = {}
    for slug in (vocabulary or {}):
        group = group_of(slug, vocabulary)
        if group:
            members.setdefault(group, set()).add(slug)

    undone = set()
    for slug in added:
        group = group_of(slug, vocabulary)
        if not group:
            continue
        try:
            exclusive = bool((groups.get(group) or {}).get("exclusive", True))
        except AttributeError:
            exclusive = True
        if exclusive:
            undone |= members.get(group, set()) - {slug}
    return undone


def group_of(state, vocabulary):
    try:
        return str((vocabulary.get(state) or {}).get("group") or "")
    except AttributeError:
        return ""


def pairs(one_way, unsettable, vocabulary, groups):
    """
    One missing rule, seen from both ends.

    A state that can be set and never unset, beside a state that is wanted and
    never settable, in the same exclusive group: the world has said those two
    answer one question, and the rule that would move it the other way does not
    exist. `(open, closed)` and `(lit, unlit)` both come out of the development
    corpus this way, from the world's own grouping and nothing else.
    """
    found = []
    for stuck in sorted(one_way):
        group = group_of(stuck, vocabulary)
        if not group:
            continue
        try:
            exclusive = bool((groups.get(group) or {}).get("exclusive", True))
        except AttributeError:
            exclusive = True
        if not exclusive:
            continue
        for missing in sorted(unsettable):
            if group_of(missing, vocabulary) == group:
                found.append((stuck, missing, group))
    return found


def self_defeating(rules):
    """
    Check rules that demand the very state their own verb brings about.

    The commonest fault in the phase 13 soak corpus by a long way: 56 of 135
    generated check rules across the two new worlds require the exact state
    their action's carry-out rule adds. Every one is the same slip -- "you
    cannot oil what is already oiled" written as `is: ["oiled"]` where it had
    to be `lacks: ["oiled"]` -- and the rule it makes can never pass. The verb
    is dead from the moment it is learned, which is why `open` was refused 41
    times in one world and succeeded never.

    Mechanical and provable, which is why it belongs here rather than in a
    judgement: a check demanding what the carry-out produces admits only a
    thing something else already did, and then does it again.

    A suspended rule is out of its book and applies to nothing, so it is
    neither a fault nor evidence of one -- which is what makes `rules suspend
    dead` a repair rather than a gesture. Filtered on both sides: a carry-out
    nobody has listed does not produce the state its own check would demand.

    Returns [(rule id, action, [states], name), ...].
    """
    listed = {rule_id: rule for rule_id, rule in (rules or {}).items()
              if hasattr(rule, "get") and rule.get("listed", True)}

    produced = {}
    for rule in listed.values():
        if rule.get("phase") != "carry_out":
            continue
        for effect in effects_of(rule):
            if effect.get("type") == "set_state":
                produced.setdefault(rule.get("action"), set()).update(
                    _states(effect, "add"))

    return _defeated(listed, produced, "check", "conditions", "is")


def after_self_defeating(rules):
    """
    After rules that only follow when their own verb's result is absent.

    The twin of `self_defeating`, and possible only since an after rule's
    guards are tested once carry-out has run (docs/becoming-and-time.md 6.8).
    "After lighting it, when it is not lit" was written against the world as it
    was before the verb, and against the world after it can never pass: the
    carry-out that ran is the one that made it lit.

    Returns [(rule id, action, [states], name), ...], the same shape.
    """
    listed = {rule_id: rule for rule_id, rule in (rules or {}).items()
              if hasattr(rule, "get") and rule.get("listed", True)}
    produced = {}
    for rule in listed.values():
        if rule.get("phase") != "carry_out":
            continue
        for effect in effects_of(rule):
            if effect.get("type") == "set_state":
                produced.setdefault(rule.get("action"), set()).update(
                    _states(effect, "add"))
    return _defeated(listed, produced, "after", "when", "lacks")


def _defeated(listed, produced, phase, key, field):
    """Rules of `phase` whose `key` conditions `field` a state their verb makes."""
    found = []
    for rule_id, rule in sorted(listed.items()):
        if rule.get("phase") != phase:
            continue
        made = produced.get(rule.get("action")) or set()
        if not made:
            continue
        clash = set()
        for condition in (rule.get(key) or []):
            clash |= dead_states(condition, made, field)
        clash = sorted(clash)
        if clash:
            found.append((str(rule_id), str(rule.get("action") or ""), clash,
                          str(rule.get("name") or "")))
    return found


def dead_states(condition, made, field="is"):
    """
    The states that make this condition impossible, given what its verb makes.

    A check condition demanding a state its own carry-out adds can never pass,
    and nor can an after rule's guard forbidding one (`field` is then "lacks").
    For a plain condition that is the `field` states among `made`. Through a
    node: an `all` is dead when any member is, and an `any` only when every
    branch is -- a rule with one live way through is not dead, and suspending
    it would take away a verb that works.

    Returns a set of state slugs, empty when the condition can pass.
    """
    from world import conditions as conditions_mod
    from world.model_json import listed

    made = {str(s).lower() for s in (made or ())}
    kind, members = conditions_mod.node_of(condition)
    if kind == conditions_mod.ALL:
        found = set()
        for member in members:
            found |= dead_states(member, made, field)
        return found
    if kind == conditions_mod.ANY:
        branches = [dead_states(member, made, field) for member in members]
        if branches and all(branches):
            return set().union(*branches)
        return set()
    try:
        return {str(v).lower() for v in listed(condition.get(field))} & made
    except AttributeError:
        return set()


def ungrounded(kind_specs):
    """
    Kinds with no taxonomy above them at all, real or anchored.

    Phase 1's promise was that every kind in a fresh world has non-empty
    ancestors. Across the two soak worlds 37 of 192 do not -- and they are not
    the invented nouns the anchor mechanism was built for. They are `box`,
    `key`, `knife`, `pen`, `shoe`, `wheel`: ordinary words WordNet knows
    perfectly well, whose senses straddle a bucket, so `canonical` leaves them
    as bare words and `needs_anchor` says no because they *have* senses.

    A bare kind takes no floor from the taxonomy, prunes against nothing, and
    can never be reached by a rule filed against a sort of thing. Worse, it
    doubles: one world holds `box` and `box.n.01` as two kinds, with 36
    attempts against the first and every rule filed against the second.

    Told apart by spelling, which looks crude and is exact: a synset id has a
    dot in it and a bare word does not, and `kinds.canonical` leaves a bare
    word behind only when it could not ground one. Doing it this way keeps the
    whole scan free of WordNet and of Evennia, which is what lets it run over a
    fixture, in a tier A test, and in `baseline.py` with no database at all.
    """
    found = []
    for kind, spec in sorted((kind_specs or {}).items()):
        if "." in str(kind):
            continue                     # a synset, which knows its own parents
        try:
            anchored = str((spec or {}).get("under") or "").strip()
        except AttributeError:
            anchored = ""
        if not anchored:
            found.append(str(kind))
    return found


def forked(by_verb):
    """
    Verbs that have more than one accepted rule and cannot agree what they do.

    A symptom of the old cache key, which forked on affordances -- `wash` in one
    world has five rules shuffling `clean`, `dirty`, `dry`, `wet` and `sweaty`
    five different ways. Keying on the verb alone ended it, so this should read
    zero in any world built since; it is kept because a world built before that
    still holds the evidence, and because a fork reappearing would mean the key
    had quietly regressed.
    """
    found = []
    for verb, entries in sorted(by_verb.items()):
        if len(entries) < 2:
            continue
        fingerprints = set()
        for _key, rule in entries:
            states = set()
            traits = set()
            for effect in effects_of(rule):
                if effect.get("type") == "set_state":
                    states |= _states(effect, "add") | _states(effect, "remove")
                elif effect.get("type") == "set_trait":
                    traits.add(str(effect.get("trait") or ""))
            fingerprints.add((tuple(sorted(states)), tuple(sorted(traits))))
        if len(fingerprints) > 1:
            found.append((verb, len(entries), len(fingerprints)))
    return found


# ---------------------------------------------------------------------------
# Saying it out loud
# ---------------------------------------------------------------------------

#: How many of a list to name before saying how many more there are. A report is
#: read aloud as often as it is looked at, so a finding says its count first and
#: then enough examples to recognise it by, rather than a wall to be scrolled.
MOST_NAMED = 12


def _listed(items):
    items = list(items)
    if len(items) <= MOST_NAMED:
        return ", ".join(items)
    return (", ".join(items[:MOST_NAMED])
            + f", and {len(items) - MOST_NAMED} more")


def report(findings, name=""):
    """
    The scan as plain prose, a finding to a line.

    Deliberately without bars, columns or aligned figures, for the same reason
    `score` is: the count comes first in the sentence, so it is the first thing
    heard, and nothing here depends on seeing the shape of the page.
    """
    counts = findings["counts"]
    lines = [f"|wWhat {name or 'this world'} has decided|n",
             f"  {counts['rules']} rules over {counts['verbs']} verbs: "
             f"{counts['accepted']} in force, {counts['refused']} refused, "
             f"{counts['contested']} contested.",
             f"  {counts['vocabulary']} conditions in its vocabulary; "
             f"{counts['states_set']} can be set, {counts['states_unset']} "
             f"can be unset."]

    # Only worth a line while a world holds both kinds. Every rule written from
    # now on is filed against a scope, so in a new world this says nothing --
    # and in an old one it says which half of the findings below are about the
    # arrangement that is being replaced.
    old_shape = counts["rules"] - counts["filed"]
    if counts["filed"] and old_shape:
        lines.append(f"  {counts['filed']} are filed against a scope; "
                     f"{old_shape} are one-per-verb rules from before the "
                     f"rulebooks.")

    trouble = []
    if findings.get("self_defeating"):
        dead = findings["self_defeating"]
        verbs = sorted({action for _id, action, _states, _name in dead})
        trouble.append(
            f"{len(dead)} check rules require the very condition their own "
            f"verb produces, so those {len(verbs)} verbs can never work: "
            f"{_listed(verbs)}.")
    if findings.get("after_self_defeating"):
        dead = findings["after_self_defeating"]
        verbs = sorted({action for _id, action, _states, _name in dead})
        trouble.append(
            f"{len(dead)} after rules follow only when their own verb has not "
            f"done what it just did, so they can never fire, over "
            f"{len(verbs)} verbs: {_listed(verbs)}.")
    if findings.get("ungrounded"):
        trouble.append(
            f"{len(findings['ungrounded'])} kinds have nothing above them in "
            f"the taxonomy, so no rule about a sort of thing can reach them: "
            f"{_listed(findings['ungrounded'])}.")
    if findings["one_way"]:
        trouble.append(
            f"{len(findings['one_way'])} conditions can be set and never "
            f"unset: {_listed(findings['one_way'])}.")
    if findings["unsettable"]:
        trouble.append(
            f"{len(findings['unsettable'])} conditions are required by a rule "
            f"and settable by nothing, so those rules can never fire: "
            f"{_listed(findings['unsettable'])}.")
    for stuck, missing, group in findings["pairs"]:
        trouble.append(
            f"Nothing can make anything {missing}. It and {stuck} are one "
            f"condition ({group}), so one rule is missing.")
    if findings["inert"]:
        verbs = sorted({verb_of(k) for k in findings["inert"]})
        trouble.append(
            f"{len(findings['inert'])} rules change nothing at all, over "
            f"{len(verbs)} verbs: {_listed(verbs)}.")
    if findings["dead_vocabulary"]:
        trouble.append(
            f"{len(findings['dead_vocabulary'])} conditions are in the "
            f"vocabulary and used by no rule: "
            f"{_listed(findings['dead_vocabulary'])}.")
    for kind, verbs in findings["refusals"].items():
        if not verbs:
            continue
        distinct = sorted(set(verbs))
        trouble.append(
            f"{len(verbs)} rules refused over {len(distinct)} verbs -- "
            f"{kind}: {_listed(distinct)}.")
    for verb, count, answers in findings["forked"]:
        trouble.append(f"'{verb}' has {count} rules giving {answers} different "
                       f"answers about what it changes.")

    if not trouble:
        lines.append("\n  Nothing amiss.")
        return "\n".join(lines)

    lines.append("")
    lines.append(f"|yWorth looking at ({len(trouble)}):|n")
    lines += [f"  {n}. {said}" for n, said in enumerate(trouble, 1)]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# What the faults say about one attempt
# ---------------------------------------------------------------------------

#: The most lines a rule-writing prompt is given about this world's faults.
#: A hint, not a report: `worldcheck` is the report.
MOST_HINTS = 6


def states_near(world_root, bound):
    """
    The states that bear on an attempt: what the things involved are in now,
    and what things of their sorts have been in before.
    """
    from world import kinds, verbs

    near = set()
    for obj in (bound or {}).values():
        if obj is None:
            continue
        try:
            near |= {str(state).lower() for state in verbs.states(obj)}
            near |= set(kinds.states_of(world_root, obj.db.kinds))
        except AttributeError:
            continue
    return near


def relevant(findings, registers, verb, near=(), proposals=(), wants=(),
             most=MOST_HINTS):
    """
    What this world's faults say about one attempt, as at most `MOST_HINTS`
    lines, the most useful first.

    Pure, like everything else here. `near` is the states that bear on the
    attempt (`states_near`), widened to every other member of their groups;
    `proposals` is what `suggest.queue` holds; `wants` is lines about wants
    nothing can satisfy, already worded by whoever asked (§5.1).

    In order: wants; one missing rule seen from both ends; a rule this world
    has already derived for this verb; conditions rules require and nothing
    sets; conditions set and never ended; unused words in the groups at hand;
    this verb's own rules that can never fire or change nothing. What this
    call can do nothing about -- ungrounded kinds, refusals, forked verbs --
    is left to `worldcheck`.
    """
    from world.suggest import _verb_for_state

    vocabulary = (registers or {}).get("state_vocabulary") or {}
    near = {str(state).lower() for state in (near or ())}
    groups = {group_of(state, vocabulary) for state in near} - {""}
    close = near | {slug for slug in vocabulary
                    if group_of(slug, vocabulary) in groups}

    def them(items):
        return "it" if len(items) == 1 else "them"

    lines = [str(line) for line in (wants or ()) if line]

    for stuck, missing, group in findings.get("pairs") or []:
        if _verb_for_state(missing) == verb or stuck in close or missing in close:
            lines.append(
                f"Nothing in this world can make anything {missing}. It and "
                f"{stuck} are one condition ({group}). If {verb} is what does "
                f"that, say so.")

    for rule in proposals or ():
        if rule.get("action") != verb:
            continue
        why = f": {rule['why']}" if rule.get("why") else ""
        lines.append(f"This world has already worked out a rule for {verb}, "
                     f"waiting to be adopted -- {rule.get('id')}, "
                     f"{rule.get('name') or 'unnamed'}{why}.")

    required = [state for state in findings.get("unsettable") or []
                if state in close]
    if required:
        lines.append(f"Rules already require {_listed(required)}, and nothing "
                     f"sets {them(required)}.")

    stuck_on = [state for state in findings.get("one_way") or []
                if state in close]
    if stuck_on:
        lines.append(f"{_listed(stuck_on)} can be set and nothing ever ends "
                     f"{them(stuck_on)}. If {verb} ends {them(stuck_on)}, "
                     f"remove {them(stuck_on)}.")

    unused = [state for state in findings.get("dead_vocabulary") or []
              if group_of(state, vocabulary) in groups]
    if unused:
        lines.append(f"Already in the vocabulary and used by nothing: "
                     f"{_listed(unused)}. Reuse one before coining another.")

    never = [name or rule_id for rule_id, action, _states, name
             in (findings.get("self_defeating") or [])
             + (findings.get("after_self_defeating") or [])
             if action == verb]
    inert = [key for key in findings.get("inert") or [] if verb_of(key) == verb]
    if never or inert:
        said = []
        if never:
            said.append(f"{len(never)} that can never fire")
        if inert:
            said.append(f"{len(inert)} that change nothing")
        lines.append(f"Rules about {verb} already here include "
                     f"{' and '.join(said)}; write the one that works rather "
                     f"than another like them.")

    return lines[:most] if most else lines


def lookup_tools():
    """`world_faults`: what `worldcheck` finds, for a model to read."""
    import re

    from world import toolbox as tb

    def world_faults(ctx, args):
        registers = of_world(ctx.world_root)
        findings = scan(registers)
        verb = str(args.get("verb") or "").strip().lower()
        kind = str(args.get("kind") or "").strip()
        if not verb and not kind:
            from world import lore

            text = report(findings, lore.title(ctx.world_root))
            return re.sub(r"\|[a-zA-Z]", "", text)
        near = set()
        if kind:
            from world import kinds

            near |= set(kinds.states_of(ctx.world_root, [kind]))
        from world import suggest

        lines = relevant(findings, registers, verb, near=near,
                         proposals=suggest.queue(ctx.world_root), most=None)
        return "\n".join(lines) or "Nothing this world has found bears on that."

    return [tb.Tool(
        "world_faults",
        "What this world's own rules say is wrong with them: conditions nothing "
        "can undo, conditions required that nothing sets, rules that can never "
        "fire. With a verb or a kind, only what bears on it; with neither, the "
        "whole report.",
        tb.params({
            "verb": {"type": "string",
                     "description": "Optional. Only what bears on this verb"},
            "kind": {"type": "string",
                     "description": "Optional. Only what bears on this sort of "
                                    "thing"},
        }),
        tb.answering(world_faults), doing="reading this world's faults",
        looks=True, available=lambda ctx: ctx.world_root is not None)]
