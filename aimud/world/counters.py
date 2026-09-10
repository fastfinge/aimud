"""
What this world has actually been asked to do, and how it answered.

Six integers per pair, not a transcript. The rulebooks know what a world has
decided; nothing knows what it has been *asked*, and that turns out to be the
difference between a suggester that guesses and one that can cite evidence.

The case it exists for is the spaceship. `launch` typed aboard a ship with no
object named is the rule this whole design was argued from, and a world only
learns it needs that rule by somebody trying it -- eleven times, getting "launch
what?" eleven times, and nothing anywhere remembering. With a count against
`(launch, enclosure:spacecraft.n.01, no_object)` the commonest refusal in a world
becomes the best-evidenced proposal in its queue, and the rule arises by itself
rather than being anticipated. See docs/rulebooks-from-inform.md 10.1.

**Deliberately not a log.** A transcript of attempts would be the timer this
design keeps refusing, in another costume: something that grows while a world is
played, has to be read back to be useful, and is never quite small enough to
throw away. A count and a last-seen answer every question a generator asks, in a
fixed amount of space per distinct question.

**The key is the question, not the sentence.** `(action, scope, outcome)` --
what was tried, what sort of thing it was tried on or in, and how it came out.
Nothing about the words anybody typed, which means two players trying the same
thing in two rooms a week apart add up to two.
"""

import time

#: Where a world keeps them.
ATTR = "attempt_counts"

#: How an attempt came out. Four, and each marks a different exit from the
#: pipeline, because a generator wants to tell them apart:
#:
#: done         -- it worked. The baseline a refusal is interesting against.
#: refused      -- a check rule said no, and the player was told which.
#: no_object    -- a role the action requires was left unbound: "launch what?".
#:                 The redirect case, and the one the spaceship needs.
#: not_admitted -- this sort of thing does not admit this verb at all.
DONE, REFUSED, NO_OBJECT, NOT_ADMITTED = (
    "done", "refused", "no_object", "not_admitted")
OUTCOMES = (DONE, REFUSED, NO_OBJECT, NOT_ADMITTED)

#: What a scope token says when nobody named anything and there is no place
#: either -- an attempt in the void, which a test can produce and a world cannot.
NOTHING = "nothing"

#: Who tried it. Two, and they answer different questions.
#:
#: `worldmode always` buys volume without anybody typing for weeks, and it
#: exercises the planner hard -- but the distribution is biased, because a
#: character reaches for verbs the world already knows and rules that already
#: exist. **Characters do not invent vocabulary.** The verbs that stress this
#: design are the ones nobody anticipated, typed at a thing nobody expected, and
#: those come from a person playing.
#:
#: So a soak wants both, and the counts have to be told apart afterwards or the
#: run answers neither question cleanly: a refusal a character met a hundred
#: times while pathfinding is weak evidence for a rule, and one a person met
#: three times is strong.
PLAYER, CHARACTER = "player", "character"
WHO = (PLAYER, CHARACTER)

#: How many distinct questions a world may remember. Generous, because the real
#: number is bounded by verbs times kinds and settles in the low hundreds, and
#: because an eviction that throws away the evidence for a proposal is worse
#: than a few kilobytes. Least recently seen goes first when it binds.
MAX_KEYS = 2000


def scope_of(bound, actor, world_root=None):
    """
    What sort of thing an attempt was about, as one token.

    Two cases, and the difference between them is the whole point:

    * Something was named, so the token is its kind -- `kind:datapad`. Two
      datapads in two rooms count as the same question, which is what makes a
      count evidence for a rule about datapads rather than about one object.
    * Nothing was named, so the token is the sort of place the actor was
      standing in -- `enclosure:spacecraft.n.01`. This is the redirect case:
      `launch` bare aboard a ship is a different question from `launch` bare in
      a corridor, and a rule can only be proposed for the one.
    """
    from world import kinds

    named = None
    for role in ("direct", "target", "instrument", "container", "source"):
        if (bound or {}).get(role) is not None:
            named = bound[role]
            break

    if named is not None:
        found = kinds.prune(kinds.of(named), world_root)
        return f"kind:{found[0]}" if found else "kind:"

    room = getattr(actor, "location", None)
    if room is None:
        return NOTHING
    found = kinds.prune(kinds.of(room), world_root)
    return f"enclosure:{found[0]}" if found else "enclosure:"


def kind_in(scope):
    """The kind a scope token names, whichever sort of token it is."""
    token = str(scope or "")
    for prefix in ("kind:", "enclosure:"):
        if token.startswith(prefix):
            return token[len(prefix):]
    return ""


def is_enclosure(scope):
    """Whether this token is about the place rather than about a named thing."""
    return str(scope or "").startswith("enclosure:")


def who_is(actor):
    """Whether a person or a character is doing this."""
    return CHARACTER if getattr(actor, "db", None) is not None \
        and actor.db.is_npc else PLAYER


def _key(action, scope, outcome, by):
    return f"{action}|{scope}|{outcome}|{by}"


def split(key):
    """(action, scope, outcome, by) from a stored key."""
    parts = str(key or "").split("|")
    while len(parts) < 4:
        parts.append("")
    return parts[0], parts[1], parts[2], parts[3]


def all_counts(world_root):
    """Everything this world has been asked, as {key: {count, last}}."""
    from evennia.utils.dbserialize import deserialize

    if not world_root:
        return {}
    return dict(deserialize(getattr(world_root.db, ATTR, None)) or {})


def note(world_root, action, bound, actor, outcome):
    """
    Record one attempt and how it came out. Answers with the new count.

    Called from `attempt.py` at each way out, and cheap enough to be: one dict
    read, one increment, one write. Nothing here can refuse an attempt or change
    one, which is the property that lets it sit on every exit path.
    """
    if not world_root or outcome not in OUTCOMES:
        return 0
    action = str(action or "").strip().lower()
    if not action:
        return 0

    scope = scope_of(bound, actor, world_root)
    store = all_counts(world_root)
    key = _key(action, scope, outcome, who_is(actor))
    entry = dict(store.get(key) or {})
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["last"] = time.time()
    store[key] = entry

    if len(store) > MAX_KEYS:
        store = _evicted(store)
    setattr(world_root.db, ATTR, store)
    return entry["count"]


def _evicted(store):
    """The store with the least recently asked questions dropped."""
    ordered = sorted(store.items(),
                     key=lambda pair: (pair[1].get("last", 0),
                                       pair[1].get("count", 0)))
    return dict(ordered[len(ordered) - MAX_KEYS:])


def count(world_root, action, scope, outcome, by=None):
    """
    How often that exact question has come out that way.

    `by` of None sums both, which is what a suggester wants: a refusal is a
    refusal whoever met it. Naming one is for the measurement afterwards, where
    the difference between a person and a pathfinder is the whole point.
    """
    wanted = (by,) if by else WHO
    total = 0
    counts = all_counts(world_root)
    for one in wanted:
        entry = counts.get(_key(action, scope, outcome, one)) or {}
        try:
            total += int(entry.get("count", 0))
        except (TypeError, ValueError):
            continue
    return total


def last_seen(world_root, action, scope, outcome, by=None):
    """When it last did, as a timestamp, or 0."""
    wanted = (by,) if by else WHO
    counts = all_counts(world_root)
    latest = 0.0
    for one in wanted:
        entry = counts.get(_key(action, scope, outcome, one)) or {}
        try:
            latest = max(latest, float(entry.get("last", 0)))
        except (TypeError, ValueError):
            continue
    return latest


def refusals(world_root, outcome=None, least=1):
    """
    Every question that has come out badly at least `least` times, worst first.

    What a suggester reads. Sorted by count so that a queue built from this is
    in evidence order without anybody sorting it again, and so that a cap on the
    queue evicts the weakest evidence rather than the newest.
    """
    wanted = (outcome,) if outcome else (REFUSED, NO_OBJECT, NOT_ADMITTED)
    # Summed across who met it, because a refusal is a refusal whoever met it
    # and a proposal wants all the evidence there is. `by` is kept alongside so
    # that the measurement afterwards can still take the two apart.
    rolled = {}
    for key, entry in all_counts(world_root).items():
        action, scope, how, by = split(key)
        if how not in wanted:
            continue
        try:
            times = int(entry.get("count", 0))
        except (TypeError, ValueError):
            continue
        row = rolled.setdefault((action, scope, how), {
            "action": action, "scope": scope, "outcome": how,
            "count": 0, "last": 0.0, "by": {}})
        row["count"] += times
        row["by"][by] = row["by"].get(by, 0) + times
        try:
            row["last"] = max(row["last"], float(entry.get("last", 0) or 0))
        except (TypeError, ValueError):
            pass
    found = [row for row in rolled.values() if row["count"] >= least]
    return sorted(found, key=lambda row: (-row["count"], row["action"],
                                          row["scope"]))


def report(world_root, limit=12):
    """The counts as prose, commonest first. For `worldcheck` and for reading."""
    rows = all_counts(world_root)
    if not rows:
        return "Nothing has been attempted in this world yet."

    total = sum(int((e or {}).get("count", 0)) for e in rows.values())
    done = sum(int((e or {}).get("count", 0)) for key, e in rows.items()
               if split(key)[2] == DONE)
    by_people = sum(int((e or {}).get("count", 0)) for key, e in rows.items()
                    if split(key)[3] == PLAYER)
    lines = [f"|w{total} attempts|n over {len(rows)} distinct questions: "
             f"{done} worked, {total - done} did not.",
             f"  {by_people} by people, {total - by_people} by characters. "
             f"|xThe two answer different questions: characters reach for what "
             f"the world already knows, people invent vocabulary.|n"]

    worst = refusals(world_root)[:limit]
    if not worst:
        lines.append("  Nothing has been refused.")
        return "\n".join(lines)

    lines.append("  Refused most often:")
    for row in worst:
        said = {NO_OBJECT: "with nothing named",
                NOT_ADMITTED: "not admitted at all",
                REFUSED: "refused"}.get(row["outcome"], row["outcome"])
        where = kind_in(row["scope"]) or "anything"
        aboard = "aboard" if is_enclosure(row["scope"]) else "on"
        people = row["by"].get(PLAYER, 0)
        lines.append(f"    {row['count']:4} x {row['action']} {aboard} "
                     f"{where} -- {said}"
                     + (f" ({people} by a person)" if people else ""))
    return "\n".join(lines)
