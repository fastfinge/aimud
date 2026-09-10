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
#: it, and so a third -- for the rulebook shape, when it exists -- has a target.
REGISTERS = ("verb_rules", "state_vocabulary", "state_groups", "kind_specs")


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
    rules = registers.get("verb_rules") or {}
    vocabulary = registers.get("state_vocabulary") or {}
    groups = registers.get("state_groups") or {}

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
        if not effects:
            inert.append(key)
        for effect in effects:
            if effect.get("type") == "set_state":
                added |= _states(effect, "add")
                removed |= _states(effect, "remove")
        wanted |= _required(rule, "is")
        forbidden |= _required(rule, "lacks")
        by_verb.setdefault(verb_of(key), []).append((key, rule))

    one_way = added - removed
    unsettable = wanted - added
    touched = added | removed | wanted | forbidden

    return {
        "one_way": sorted(one_way),
        "unsettable": sorted(unsettable),
        "dead_vocabulary": sorted(set(vocabulary) - touched),
        "pairs": pairs(one_way, unsettable, vocabulary, groups),
        "inert": sorted(inert),
        "refusals": {kind: sorted(verbs) for kind, verbs in refusals.items()},
        "forked": forked(by_verb),
        "counts": {
            "rules": len(rules),
            "accepted": accepted,
            "refused": len(rules) - accepted,
            "contested": contested,
            "verbs": len(by_verb),
            "states_set": len(added),
            "states_unset": len(removed),
            "vocabulary": len(vocabulary),
        },
    }


def refusal_kind(rule):
    """Which of REFUSAL_KINDS a refusal's own sentence puts it in."""
    said = str(rule.get("reason") or "")
    if _ENGINE.search(said):
        return REFUSAL_KINDS[0]
    if _PLACE.search(said):
        return REFUSAL_KINDS[1]
    return REFUSAL_KINDS[2]


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

    trouble = []
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
