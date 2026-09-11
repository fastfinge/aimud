"""
Rules a world derives about itself, offered and never installed.

`rulecheck` finds faults. This proposes fixes. The difference between the two is
the whole reason this is a queue rather than a repair: a one-way state is a fact,
and the rule that would settle it is a guess -- a good guess, drawn from the
world's own behaviour, and still a guess about meaning. So nothing here is ever
in force. A proposal is a rule with `listed: false`, which already meant "in the
book, not applying", plus a reason somebody can read and the counts that prompted
it. See docs/rulebooks-from-inform.md 10.1.

**Everything here is free.** No model, no network. That is what makes it safe to
run on a command, on a timer, or at server start: the half that costs nothing
generates, and the half that costs money judges, and judging is a command. A
model asked to judge is looking at a filled-in form with evidence attached, which
is a far smaller question than being asked to write a rule from nothing.

**Evidence from this world, or nothing.** A lexical resource may *name* a
candidate -- `closed` is the word whose verb is `close` -- but only the world's
own faults and its own refusals may justify one. That rule is the difference
between a queue worth reading and a queue of plausible nonsense, and it is
enforced in `propose` rather than trusted to each generator.

The six rails are in `propose` and `accept`, each with the failure it exists for
written beside it. The one to read is the fourth: an `instead` proposal at equal
or wider scope than the rule it means to refine would shadow it instead, and a
wrong `instead` is the worst bug this design permits -- it silently makes a verb
mean something else.
"""

from evennia.utils import logger

from world import counters, rulebooks

#: Where a world remembers what it has been offered and declined.
ATTR_DECLINED = "declined_suggestions"

#: What marks a rule as having been derived rather than decided. Permanent: an
#: accepted proposal keeps it, so an audit years later can ask what this world
#: worked out for itself and what was suggested to it.
DERIVED = "derived"

#: How many proposals a world may hold at once. The weakest evidence is evicted
#: first, so a queue that fills up loses its worst entry rather than its newest.
#: Small on purpose: a queue nobody can read through is a queue nobody reads.
MAX_QUEUE = 24

#: How often a thing must have gone wrong before it is worth proposing about.
#: Three, because two is a coincidence and one is a typo -- and because the
#: point of a counter is to tell a habit from an accident.
LEAST = 3


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------

def queue(world_root):
    """Every proposal this world is holding, best evidence first."""
    found = [r for r in rulebooks.all_rules(world_root)
             if r.get("source") == DERIVED and not r.get("listed", True)]
    return sorted(found, key=lambda r: (-_weight(r), r.get("id", "")))


def accepted(world_root):
    """Proposals this world took up. They keep the mark for good."""
    return [r for r in rulebooks.all_rules(world_root)
            if r.get("source") == DERIVED and r.get("listed", True)]


def _weight(rule):
    """How much this world's own behaviour has to say for a proposal."""
    try:
        evidence = dict(rule.get("evidence") or {})
    except (TypeError, ValueError):
        return 0
    return sum(int(v) for v in evidence.values()
               if isinstance(v, int) and not isinstance(v, bool))


def fingerprint(rule):
    """
    What makes two proposals the same proposal.

    Not the id, which changes every time one is generated, and not the whole
    record, which carries a timestamp. What a person actually declined is "this
    phase, this action, this scope, doing this" -- so that is what is remembered,
    and an identical proposal next week is recognised as the one they said no to.
    """
    try:
        scope = dict(rule.get("scope") or {})
    except (TypeError, ValueError):
        scope = {}
    where = ",".join(f"{k}={scope[k]}" for k in sorted(scope))
    doing = ";".join(sorted(
        f"{e.get('type')}:{e.get('add') or e.get('to') or e.get('action') or ''}"
        for e in (rule.get("effects") or []) if hasattr(e, "get")))
    return f"{rule.get('phase')}|{rule.get('action')}|{where}|{doing}"


def declined(world_root):
    """Fingerprints this world has said no to."""
    if not world_root:
        return set()
    return set(getattr(world_root.db, ATTR_DECLINED, None) or [])


# ---------------------------------------------------------------------------
# Offering one
# ---------------------------------------------------------------------------

def propose(world_root, rule, why, evidence, overrides=None):
    """
    Put one proposal in the queue, or refuse to. Answers with it, or None.

    Every rail that can be checked from the proposal itself is checked here
    rather than in each generator, so a new generator cannot forget one.
    """
    if not world_root:
        return None

    # RAIL 1: no evidence, no proposal. A count from this world or nothing --
    # which is what stops a lexical resource from filling the queue with things
    # that are true of English and untrue of this world.
    if not evidence or not _weight({"evidence": evidence}):
        logger.log_info(f"suggest: refused, no evidence -- {why}")
        return None

    record = dict(rule)
    record["source"] = DERIVED
    record["listed"] = False
    record["why"] = str(why or "")
    record["evidence"] = dict(evidence)
    record["overrides"] = overrides

    # RAIL 2: a proposal already declined is not offered again. Without this the
    # queue re-offers everything it has ever thought of, every time it runs,
    # forever, and becomes unreadable on its second use.
    mark = fingerprint(record)
    if mark in declined(world_root):
        return None

    # And one nobody has answered yet is not offered twice either.
    for standing in queue(world_root) + accepted(world_root):
        if fingerprint(standing) == mark:
            return None

    # RAIL 4: an `instead` proposal must be strictly more specific than the rule
    # it would override, and must name it. An instead rule at equal or wider
    # scope shadows the thing it was meant to refine, and a wrong one silently
    # changes what a verb means -- the worst bug this design allows.
    if record.get("phase") == rulebooks.INSTEAD and overrides:
        beaten = rulebooks.get(world_root, overrides)
        if beaten is None:
            return None
        if rulebooks.tier_of(record) >= rulebooks.tier_of(beaten):
            logger.log_info(
                f"suggest: refused, {overrides} is not less specific -- {why}")
            return None
        if str(overrides) not in record["why"]:
            record["why"] = f"{record['why']} (overrides {overrides})"

    stored = rulebooks.add(world_root, record)
    if stored is None:
        return None
    # `add` keeps only the fields `blank` declares, and these three are now
    # among them -- asserted rather than assumed, because a proposal that lost
    # its evidence on the way into storage would fail rail 1 from then on.
    _evict(world_root)
    logger.log_info(f"suggest: {stored['id']} {stored['phase']} "
                    f"{stored.get('action')} -- {why}")
    return stored


def _evict(world_root):
    """
    Keep the queue to its cap, dropping the weakest evidence first.

    RAIL 5. A suggester that can grow without bound is a second drift problem,
    and the thing worth dropping is the proposal this world has least reason to
    make -- not the newest, which is as likely to be the best one.
    """
    standing = queue(world_root)
    for rule in standing[MAX_QUEUE:]:
        store = dict(getattr(world_root.db, rulebooks.ATTR, None) or {})
        store.pop(rule.get("id"), None)
        setattr(world_root.db, rulebooks.ATTR, store)


# ---------------------------------------------------------------------------
# Answering one
# ---------------------------------------------------------------------------

def accept(world_root, rule_id):
    """
    Put a proposal into force. Answers with it, or None.

    RAIL 6: the `derived` mark stays. An accepted proposal is in force and still
    says where it came from, because the question "what did this world decide for
    itself" is worth being able to ask years later.
    """
    rule = rulebooks.get(world_root, rule_id)
    if rule is None or rule.get("source") != DERIVED:
        return None
    if rule.get("listed", True):
        return rule                      # already in force; nothing to do
    return rulebooks.set_listed(world_root, rule_id, True)


def reject(world_root, rule_id):
    """
    Decline a proposal, and remember that it was declined.

    RAIL 2 in its other half. The rule is deleted -- an unlisted rule nobody
    will ever accept is clutter -- but its fingerprint is kept, so the generator
    that thought of it will recognise its own idea and say nothing.
    """
    rule = rulebooks.get(world_root, rule_id)
    if rule is None or rule.get("source") != DERIVED:
        return None

    marks = set(declined(world_root))
    marks.add(fingerprint(rule))
    setattr(world_root.db, ATTR_DECLINED, sorted(marks))

    store = dict(getattr(world_root.db, rulebooks.ATTR, None) or {})
    store.pop(str(rule_id), None)
    setattr(world_root.db, rulebooks.ATTR, store)
    logger.log_info(f"suggest: {rule_id} declined")
    return rule


# ---------------------------------------------------------------------------
# Where proposals come from
# ---------------------------------------------------------------------------

def generate(world_root):
    """
    Every proposal this world's own behaviour supports, newly offered.

    Free to call. Returns what was added, which is usually nothing: a world has
    only so many faults, and each is offered once until it is answered.
    """
    if not world_root:
        return []
    made = []
    for generator in (from_pairs, from_unbound_refusals, from_siblings):
        try:
            made += [r for r in generator(world_root) if r is not None]
        except Exception:
            logger.log_trace(f"suggest: {generator.__name__} failed")
    return made


def _world_rules(world_root):
    """
    The rules a proposal may be derived FROM.

    RAIL 3: no chains. A derived rule is excluded whether or not it was accepted,
    because a world that may reason from its own guesses reasons its way into
    fiction -- and the second derivation always looks as well evidenced as the
    first.
    """
    return [r for r in rulebooks.all_rules(world_root)
            if r.get("source") != DERIVED]


def _verb_for_state(state):
    """
    The verb that would bring a state about, or "".

    The one lexical step in here, and it is allowed to be lexical because it only
    *names* a candidate: `closed` is the word whose verb is `close`. Whether this
    world needs a rule about closing is decided entirely by this world's faults.
    """
    from world import lexicon, verbs

    word = str(state or "").strip().lower()
    if not word:
        return ""
    # `lemma` answers with the word itself when it has never heard of it, so the
    # answer has to be checked rather than trusted: `unlit` lemmatises to
    # `unlit`, and proposing that a world needs a rule about "unlitting" things
    # would be exactly the plausible nonsense rail 1 exists to keep out.
    found = lexicon.lemma(word, "v") or ""
    if not found or "v" not in lexicon.parts_of_speech(found):
        return ""
    return verbs.canonical_verb(found)


def from_pairs(world_root):
    """
    A state that can be set and never unset, beside its opposite that nothing
    can bring about. One missing rule, seen from both ends.

    The evidence is the world's own grouping: it said those two states answer one
    question, and then wrote a rule that only ever moves it one way. 45 one-way
    states and 7 unreachable ones across the development corpus, and five such
    pairs.
    """
    from world import rulecheck

    made = []
    registers = rulecheck.of_world(world_root)
    # Derived rules are kept out of the scan this reads, so that a proposal is
    # never evidence for the next proposal.
    registers["rules"] = {
        r["id"]: r for r in _world_rules(world_root) if r.get("id")}
    found = rulecheck.scan(registers)

    for stuck, missing, group in found.get("pairs") or []:
        action = _verb_for_state(missing)
        if not action:
            continue
        scope, cited = _where_state_is_set(world_root, stuck)
        if scope is None:
            continue
        wanted = sum(1 for rule in _world_rules(world_root)
                     for condition in (rule.get("conditions") or [])
                     if missing in [str(s).lower() for s in
                                    (condition.get("is") or [])])
        made.append(propose(
            world_root,
            rulebooks.blank(
                action=action, phase=rulebooks.CARRY_OUT, scope=scope,
                about="direct",
                # No inflection. "closeing" is what gluing "ing" onto a verb
                # gets you, and a proposal a person has to read is exactly the
                # wrong place to guess at English morphology.
                name=f"{action} makes a thing {missing}",
                effects=[{"type": "set_state", "role": "direct",
                          "add": [missing], "remove": [stuck]}]),
            why=(f"nothing in this world can make anything {missing}, and "
                 f"{stuck} and {missing} are one condition ({group}); "
                 f"{cited} sets {stuck}"),
            evidence={"one_way_state": 1, "rules_wanting_it": wanted,
                      "pair": 1}))
    return made


def _where_state_is_set(world_root, state):
    """(the scope of the rule that sets this state, that rule's id), or (None, "")."""
    wanted = str(state or "").lower()
    for rule in _world_rules(world_root):
        for effect in (rule.get("effects") or []):
            try:
                adds = [str(s).lower() for s in (effect.get("add") or [])]
            except AttributeError:
                continue
            if wanted in adds:
                return dict(rule.get("scope") or {}), str(rule.get("id") or "")
    return None, ""


def from_unbound_refusals(world_root):
    """
    A verb typed with nothing named, refused again and again, always in the same
    sort of place. The `power`-aboard-a-ship case arising by itself.

    This is the row the whole of 10.1 was written for, and the one that needs
    counters: without them the proposal is a guess, and with them it is the
    best-evidenced thing in the queue.
    """
    made = []
    for row in counters.refusals(world_root, outcome=counters.NO_OBJECT,
                                 least=LEAST):
        if not counters.is_enclosure(row["scope"]):
            continue
        kind = counters.kind_in(row["scope"])
        if not kind:
            continue
        action = row["action"]
        made.append(propose(
            world_root,
            rulebooks.blank(
                action=action, phase=rulebooks.INSTEAD,
                scope={rulebooks.KIND: kind},
                # ENCLOSURE, not "direct". The rule is about the place the
                # actor is standing in, and `about` is what decides which of
                # those a kind scope means -- a rule about `spacecraft.n.01`
                # filed against `direct` is about a model ship on a shelf, and
                # would never gather for an attempt that named nothing at all.
                about=rulebooks.ENCLOSURE,
                name=f"{action} aboard a {kind} means the {kind}",
                when=[{"subject": "direct", "unbound": True}],
                effects=[{"type": "try", "action": action,
                          "roles": {"direct": {"enclosure": kind}}}]),
            why=(f"{action} was typed with nothing named {row['count']} times "
                 f"inside a {kind}, and refused every time"),
            evidence={"attempts_refused": row["count"]},
            overrides=_instead_to_beat(world_root, action, kind)))
    return made


def _instead_to_beat(world_root, action, kind):
    """
    The `instead` rule a redirect at this kind would have to outrank, or None.

    Usually None: most verbs have no instead rule at all, and a proposal that
    overrides nothing is not shadowing anything. When there is one, rail 4 in
    `propose` insists the proposal be strictly more specific than it.
    """
    for rule in _world_rules(world_root):
        if rule.get("phase") != rulebooks.INSTEAD:
            continue
        if rule.get("action") not in (None, action):
            continue
        scope = dict(rule.get("scope") or {})
        if rulebooks.WORLD in scope or scope.get(rulebooks.KIND) == kind:
            return str(rule.get("id") or "") or None
    return None


def from_siblings(world_root):
    """
    Two kinds that afford the same things, where only one has a rule about a
    verb they both admit. Proposes *widening* the rule rather than copying it.

    The only generator here that makes a world simpler. Fewer rules is the point:
    the old design's fault was 664 rules for 151 verbs, and a suggester that only
    ever adds would be walking back towards it.
    """
    from world import kinds

    made = []
    specs = {kind: (kinds.spec(world_root, kind) or {})
             for kind in kinds.vocabulary(world_root)}

    for rule in _world_rules(world_root):
        scope = dict(rule.get("scope") or {})
        kind = scope.get(rulebooks.KIND)
        action = rule.get("action")
        if not kind or not action or kind not in specs:
            continue
        afforded = _affordances(specs[kind])
        if not afforded:
            continue

        for other, spec in sorted(specs.items()):
            if other == kind or _affordances(spec) != afforded:
                continue
            if not spec.get("affordances", {}).get(action, False):
                continue          # it does not admit the verb; nothing to widen
            if _has_rule_for(world_root, action, other):
                continue
            shared = _shared_parent(world_root, kind, other)
            if not shared:
                continue
            made.append(propose(
                world_root,
                dict(rule, id="", scope={rulebooks.KIND: shared},
                     name=f"{rule.get('name') or action} (for any {shared})"),
                why=(f"{kind} and {other} afford exactly the same things and "
                     f"both admit {action}, but only {kind} has a rule "
                     f"({rule.get('id')}); both are {shared}"),
                evidence={"sibling_kinds": 2,
                          "shared_affordances": len(afforded)}))
    return made


def _affordances(spec):
    """The set of verbs a kind admits, as a comparable thing."""
    try:
        return frozenset(verb for verb, allowed
                         in dict(spec.get("affordances") or {}).items()
                         if allowed)
    except (AttributeError, TypeError, ValueError):
        return frozenset()


def _has_rule_for(world_root, action, kind):
    """Whether any rule of this world's own is filed at that kind for that verb."""
    for rule in _world_rules(world_root):
        if rule.get("action") != action:
            continue
        if dict(rule.get("scope") or {}).get(rulebooks.KIND) == kind:
            return True
    return False


def _shared_parent(world_root, one, other):
    """
    The nearest kind both are a sort of, or "".

    Through the anchored chain, so an invented noun hanging under `device.n.01`
    shares parents with a real one. Refused above the scope ceiling, because a
    widening that files a rule near the root of the taxonomy is not a
    simplification but a rule about everything.
    """
    from world import kinds, lexicon, rule_gen

    mine = kinds.ancestors(world_root, one)
    theirs = set(kinds.ancestors(world_root, other))
    for parent in sorted(mine, key=lambda name: -len(lexicon.ancestors(name))):
        if parent in theirs and not rule_gen.too_general(
                {rulebooks.KIND: parent}):
            return parent
    return ""


# ---------------------------------------------------------------------------
# Saying it out loud
# ---------------------------------------------------------------------------

def said(rule, world_root=None):
    """One proposal as the lines somebody should read."""
    from world import conditions

    where = rulebooks.said_scope(rule.get("scope"), world_root)
    head = (f"|w{rule.get('id')}|n  {rule.get('phase', '').replace('_', ' ')}"
            f"  {where}  -- {rule.get('name') or ''}")
    lines = [head]

    for effect in (rule.get("effects") or []):
        kind = str(effect.get("type") or "")
        if kind == "set_state":
            adds = ", ".join(effect.get("add") or []) or "nothing"
            gone = ", ".join(effect.get("remove") or [])
            lines.append(f"    would add: {adds}"
                         + (f", remove: {gone}" if gone else ""))
        elif kind == "try":
            lines.append(f"    would redirect: {effect.get('action')} -> "
                         f"the enclosing place")
        else:
            lines.append(f"    would: {kind}")
    for condition in (rule.get("conditions") or []):
        lines.append(f"    would require: {conditions.describe(condition)}")
    if rule.get("overrides"):
        lines.append(f"    overrides: {rule['overrides']}")
    lines.append(f"    because  : {rule.get('why') or 'no reason recorded'}")
    return "\n".join(lines)


def report(world_root):
    """The whole queue, best evidence first."""
    standing = queue(world_root)
    if not standing:
        return ("Nothing to suggest. Either this world has no faults anything "
                "can name, or everything it has has been answered.")
    lines = [f"|w{len(standing)} suggestions|n, best evidence first. "
             f"|wrules accept <id>|n or |wrules reject <id>|n."]
    lines += [said(rule, world_root) for rule in standing]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Asking somebody else to judge
# ---------------------------------------------------------------------------

_JUDGE = """You are shown rules a text MUD has derived about itself, and you say
yes or no to each. You are NOT writing rules: every one below is already filled
in, and every one cites what the world's own behaviour says for it.

Respond with a single JSON object -- no other text:
{"verdicts": [{"id": "r7", "accept": true, "because": "one short sentence"}]}

One verdict per suggestion, using the id exactly as given. Say `accept: false`
when a rule would be wrong rather than merely dull -- a world with a few plain
rules is in better shape than one with a clever wrong one. In particular refuse
anything that:

  * would make a verb mean something the evidence does not support;
  * is filed against a sort of thing so general that it would apply to
    everything in the world;
  * undoes something the world has clearly decided on purpose.

Accept freely otherwise. These are drawn from faults the world actually has --
conditions nothing can undo, verbs refused over and over -- so the usual answer
to a well-evidenced suggestion is yes.
"""


def judgement_prompt(world_root):
    """Everything a judge is shown: the queue, and what stands against it."""
    standing = queue(world_root)
    if not standing:
        return ""
    lines = ["These are the suggestions waiting, with the evidence for each."]
    for rule in standing:
        lines.append("")
        lines.append(said(rule, world_root).replace("|w", "").replace("|n", "")
                     .replace("|x", ""))
        if rule.get("overrides"):
            beaten = rulebooks.get(world_root, rule["overrides"])
            if beaten:
                lines.append(f"    the rule it would override: "
                             f"{beaten.get('name') or beaten['id']} at "
                             f"{rulebooks.said_scope(beaten.get('scope'), world_root)}")
    return "\n".join(lines)


def judge(account, world_root, on_success, on_error):
    """
    Async. One call, the whole queue, a verdict per entry.

    The economy is the point. A model asked to *write* a rule has to invent a
    scope, conditions and effects out of nothing, and it is charged for every
    rule separately. A model asked to *judge* is looking at a filled-in form with
    this world's own counts attached, and several ride in one call -- so the cost
    is per batch rather than per rule, and the question is the one a model is
    actually good at.

    Applies the verdicts and answers with (accepted, rejected) as lists of ids.
    Nothing here can write a rule: a verdict may only take up or decline one
    already in the queue, so the worst a bad answer can do is accept something a
    person would have refused, which `rules` then shows marked `derived`.
    """
    from world import llm, model_json

    standing = queue(world_root)
    if not standing:
        on_success([], [])
        return
    try:
        api_key = account.get_openrouter_key()
    except (AttributeError, ValueError) as err:
        on_error(str(err))
        return

    messages = [
        {"role": "system", "content": _JUDGE},
        {"role": "user", "content": judgement_prompt(world_root)},
    ]

    def answered(content):
        try:
            reply = model_json.parse_object(content)
            verdicts = list(reply.get("verdicts") or [])
        except Exception as exc:
            on_error(str(exc))
            return

        waiting = {rule["id"] for rule in standing}
        taken, declined_now = [], []
        for verdict in verdicts:
            try:
                rule_id = str(verdict.get("id") or "").strip()
                yes = bool(verdict.get("accept"))
            except AttributeError:
                continue
            # Only what was actually offered. A verdict naming a rule that is not
            # in the queue is the one way this call could reach a rule a world
            # decided for itself, and it is refused here rather than trusted.
            if rule_id not in waiting:
                logger.log_info(f"suggest: verdict for {rule_id!r} ignored, "
                                f"not in the queue")
                continue
            if yes:
                if accept(world_root, rule_id) is not None:
                    taken.append(rule_id)
            elif reject(world_root, rule_id) is not None:
                declined_now.append(rule_id)
        on_success(taken, declined_now)

    llm.fetch(llm.ask, api_key, account.model_for("commands"), messages,
              on_success=answered,
              on_error=lambda failure: on_error(failure.getErrorMessage()))

