"""
What every model call cost, and who caused it.

Nothing in this game has ever counted a model call. `world.llm` makes all of
them and records none, and OpenRouter returns a `usage` block in every single
reply that is read past and thrown away. So "how much has this world cost" is
answerable by looking at a bank statement and nowhere else, and the roadmap's
security audit -- "make sure money can't be spent unexpectedly" -- has no data
to examine.

That is uncomfortable now and impossible later. Once a world can be visited by
somebody who did not build it, the question stops being *how much* and becomes
**whose action spent whose money**, and that can only be answered if the actor
and the payer were both still in scope when the request was built. They are,
exactly once, in a `world.sponsor.Sponsor` -- which is why this module exists
beside that one and takes a sponsor rather than an account.

**Two shapes, because two questions get asked.** A running total answers "what
has this cost me", which is the one a player asks and the one that has to stay
cheap to keep -- so it is a handful of integers that are added to, never a list
that is scanned. A short tail of recent calls answers "what just happened",
which is the one somebody asks when a number surprises them, and which is
useless in aggregate. Keeping only the totals would make a surprise
un-investigable; keeping only the log would make the total a scan.

**Written on the account that pays**, not the world, because the account is
what survives a `worldreset` and is what a bill arrives for. The world is
recorded on each entry instead, so a per-world figure is still there for
anybody who wants one.

Never raises. A ledger that can break a turn is worse than no ledger: the call
has already been made and the money has already been spent, so failing to write
it down must not also lose the answer the player was waiting for.
"""

import time

from evennia.utils import logger

#: How many individual calls are kept. Enough to see what a surprising total
#: was made of; short enough that the attribute stays small and cheap to write.
#: A player who needs more than this wants the totals, which are exact.
RECENT = 60

#: The fields a usage block is read out of. OpenRouter follows OpenAI's naming
#: here, and a provider that does not is read as zero rather than crashing --
#: which is the right trade for a number nobody is waiting on.
_PROMPT = ("prompt_tokens", "input_tokens")
_COMPLETION = ("completion_tokens", "output_tokens")


def _count(usage, names):
    for name in names:
        try:
            value = usage.get(name)
        except AttributeError:
            return 0
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0
    return 0


def note(sponsor, model, usage, seconds=None):
    """
    Record one model call. Main thread only; never raises.

    Takes the whole sponsor rather than an account because the three facts
    that make an entry worth having -- who paid, who acted, which world -- are
    only together on that object.

    `seconds` is how long the request took, when it was timed. A call without
    it still counts as a call, but adds no time and is not counted as timed:
    an average is the seconds over the timed calls, and an untimed call
    counted as zero would make every figure look faster than it was.
    """
    try:
        _note(sponsor, model, usage, seconds)
    except Exception as exc:
        logger.log_info(f"ledger: could not record a call: {exc}")


def _seconds(value):
    """How long a call took, as a number no smaller than zero, or None."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    # NaN fails this comparison too, which is the answer wanted for it.
    return seconds if seconds >= 0 else None


def _note(sponsor, model, usage, seconds=None):
    account = getattr(sponsor, "account", None)
    if account is None:
        return      # nobody paid: a call that never went out

    prompt = _count(usage or {}, _PROMPT)
    completion = _count(usage or {}, _COMPLETION)
    seconds = _seconds(seconds)
    job = str(getattr(model, "job", "") or "unknown")
    world = getattr(getattr(sponsor, "world_root", None), "id", None)

    _add_totals(account, job, world, prompt, completion, seconds)
    _add_recent(account, sponsor, model, job, world, prompt, completion,
                seconds)


def _blank():
    return {"calls": 0, "prompt": 0, "completion": 0, "seconds": 0.0,
            "timed": 0}


def _add(row, prompt, completion, seconds):
    """One call's figures, added to a row of running totals in place."""
    row["calls"] = row.get("calls", 0) + 1
    row["prompt"] = row.get("prompt", 0) + prompt
    row["completion"] = row.get("completion", 0) + completion
    if seconds is not None:
        row["seconds"] = round(row.get("seconds", 0.0) + seconds, 3)
        row["timed"] = row.get("timed", 0) + 1


def _bump(into, key, prompt, completion, seconds=None):
    row = dict(into.get(key) or _blank())
    _add(row, prompt, completion, seconds)
    into[key] = row


def _add_totals(account, job, world, prompt, completion, seconds=None):
    """
    The running figures. Read far more often than any one entry, and written
    on every call, so this is deliberately a few numbers rather than anything
    that has to be walked.
    """
    totals = dict(account.db.spend_totals or {})
    _add(totals, prompt, completion, seconds)

    by_job = dict(totals.get("by_job") or {})
    _bump(by_job, job, prompt, completion, seconds)
    totals["by_job"] = by_job

    if world is not None:
        by_world = dict(totals.get("by_world") or {})
        _bump(by_world, str(world), prompt, completion, seconds)
        totals["by_world"] = by_world

    account.db.spend_totals = totals


def _add_recent(account, sponsor, model, job, world, prompt, completion,
                seconds=None):
    """The short tail, newest last, trimmed to RECENT."""
    actor = getattr(sponsor, "actor", None)
    entry = {
        "when": int(time.time()),
        "job": job,
        "model": str(model or ""),
        "world": world,
        "actor": getattr(actor, "key", "") if actor is not None else "",
        "prompt": prompt,
        "completion": completion,
        "seconds": round(seconds, 3) if seconds is not None else None,
    }
    recent = list(account.db.spend_recent or [])
    recent.append(entry)
    account.db.spend_recent = recent[-RECENT:]


# ---------------------------------------------------------------------------
# Reading it back
# ---------------------------------------------------------------------------

def totals(account):
    """What this account has spent, and how long it waited, as plain numbers."""
    stored = dict((account.db.spend_totals if account else None) or {})
    stored.setdefault("calls", 0)
    stored.setdefault("prompt", 0)
    stored.setdefault("completion", 0)
    stored.setdefault("seconds", 0.0)
    stored.setdefault("timed", 0)
    stored.setdefault("by_job", {})
    stored.setdefault("by_world", {})
    return stored


def recent(account, limit=RECENT):
    """The last few calls, newest first."""
    stored = list((account.db.spend_recent if account else None) or [])
    return list(reversed(stored))[:limit]


def forget_world(account, world_id):
    """
    Drop a world's figures, because the world is gone.

    Called from `worldremove`. The totals keep the account's lifetime spend
    intact -- money spent is spent, and a figure that goes down when a world is
    deleted is a figure nobody can reconcile -- so only the per-world breakdown
    and the entries naming it are removed.
    """
    if account is None or world_id is None:
        return
    totals_now = dict(account.db.spend_totals or {})
    by_world = dict(totals_now.get("by_world") or {})
    if by_world.pop(str(world_id), None) is not None:
        totals_now["by_world"] = by_world
        account.db.spend_totals = totals_now

    kept = [e for e in (account.db.spend_recent or [])
            if e.get("world") != world_id]
    account.db.spend_recent = kept

    # Round counts are not money, so a gone world's go with it entirely.
    loops_now = dict(account.db.loop_totals or {})
    by_world_loops = dict(loops_now.get("by_world") or {})
    if by_world_loops.pop(str(world_id), None) is not None:
        loops_now["by_world"] = by_world_loops
        account.db.loop_totals = loops_now


# ---------------------------------------------------------------------------
# Tool loops
# ---------------------------------------------------------------------------
#
# How many rounds each job's conversations take, which is what the round
# budgets in docs/generator-tool-loops.md are set from. Kept apart from what
# was spent, because these figures are for tuning and may be cleared to start
# counting again after a change, and money spent may not.

def note_loop(sponsor, model, loop):
    """
    Record one tool loop, as `llm.converse` reports it. Main thread only;
    never raises.

    `loop` carries `rounds`, `limit`, `seconds`, `outcome`, `complaints`,
    `tools` ({name: calls}), and `hints_shown` / `hints_used` once there are
    hints to count.
    """
    try:
        _note_loop(sponsor, model, loop)
    except Exception as exc:
        logger.log_info(f"ledger: could not record a loop: {exc}")


def _blank_loop():
    return {"loops": 0, "rounds": 0, "most_rounds": 0, "limit": 0,
            "forced": 0, "failed": 0, "complaints": 0, "seconds": 0.0,
            "tools": {}, "hints_shown": 0, "hints_used": 0}


def _whole(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _add_loop(row, loop):
    row = {**_blank_loop(), **dict(row or {})}
    rounds = _whole(loop.get("rounds"))
    row["loops"] += 1
    row["rounds"] += rounds
    row["most_rounds"] = max(row["most_rounds"], rounds)
    row["limit"] = _whole(loop.get("limit")) or row["limit"]
    outcome = str(loop.get("outcome") or "")
    if outcome == "forced":
        row["forced"] += 1
    elif outcome in ("failed", "exhausted"):
        row["failed"] += 1
    row["complaints"] += _whole(loop.get("complaints"))
    seconds = _seconds(loop.get("seconds"))
    if seconds is not None:
        row["seconds"] = round(row["seconds"] + seconds, 3)
    tools = dict(row["tools"] or {})
    for name, calls in dict(loop.get("tools") or {}).items():
        tools[str(name)] = _whole(tools.get(str(name))) + _whole(calls)
    row["tools"] = tools
    row["hints_shown"] += _whole(loop.get("hints_shown"))
    row["hints_used"] += _whole(loop.get("hints_used"))
    return row


def _note_loop(sponsor, model, loop):
    account = getattr(sponsor, "account", None)
    if account is None:
        return
    job = str(getattr(model, "job", "") or "unknown")
    world = getattr(getattr(sponsor, "world_root", None), "id", None)

    stored = dict(account.db.loop_totals or {})
    by_job = dict(stored.get("by_job") or {})
    by_job[job] = _add_loop(by_job.get(job), loop)
    stored["by_job"] = by_job
    if world is not None:
        by_world = dict(stored.get("by_world") or {})
        here = dict(by_world.get(str(world)) or {})
        here[job] = _add_loop(here.get(job), loop)
        by_world[str(world)] = here
        stored["by_world"] = by_world
    account.db.loop_totals = stored


def loops(account, world_id=None):
    """Loop figures by job, as plain dicts: every world's, or one world's."""
    from evennia.utils.dbserialize import deserialize

    stored = deserialize((account.db.loop_totals if account else None) or {})
    if world_id is None:
        found = stored.get("by_job") or {}
    else:
        found = (stored.get("by_world") or {}).get(str(world_id)) or {}
    return {job: {**_blank_loop(), **dict(row)} for job, row in found.items()}


def forget_loops(account):
    """Start counting rounds again. What was spent is untouched."""
    if account is not None and account.attributes.has("loop_totals"):
        account.attributes.remove("loop_totals")
