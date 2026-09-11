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


def note(sponsor, model, usage):
    """
    Record one model call. Main thread only; never raises.

    Takes the whole sponsor rather than an account because the three facts
    that make an entry worth having -- who paid, who acted, which world -- are
    only together on that object.
    """
    try:
        _note(sponsor, model, usage)
    except Exception as exc:
        logger.log_info(f"ledger: could not record a call: {exc}")


def _note(sponsor, model, usage):
    account = getattr(sponsor, "account", None)
    if account is None:
        return      # nobody paid: a call that never went out

    prompt = _count(usage or {}, _PROMPT)
    completion = _count(usage or {}, _COMPLETION)
    job = str(getattr(model, "job", "") or "unknown")
    world = getattr(getattr(sponsor, "world_root", None), "id", None)

    _add_totals(account, job, world, prompt, completion)
    _add_recent(account, sponsor, model, job, world, prompt, completion)


def _blank():
    return {"calls": 0, "prompt": 0, "completion": 0}


def _bump(into, key, prompt, completion):
    row = dict(into.get(key) or _blank())
    row["calls"] = row.get("calls", 0) + 1
    row["prompt"] = row.get("prompt", 0) + prompt
    row["completion"] = row.get("completion", 0) + completion
    into[key] = row


def _add_totals(account, job, world, prompt, completion):
    """
    The running figures. Read far more often than any one entry, and written
    on every call, so this is deliberately a few integers rather than anything
    that has to be walked.
    """
    totals = dict(account.db.spend_totals or {})
    totals["calls"] = totals.get("calls", 0) + 1
    totals["prompt"] = totals.get("prompt", 0) + prompt
    totals["completion"] = totals.get("completion", 0) + completion

    by_job = dict(totals.get("by_job") or {})
    _bump(by_job, job, prompt, completion)
    totals["by_job"] = by_job

    if world is not None:
        by_world = dict(totals.get("by_world") or {})
        _bump(by_world, str(world), prompt, completion)
        totals["by_world"] = by_world

    account.db.spend_totals = totals


def _add_recent(account, sponsor, model, job, world, prompt, completion):
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
    }
    recent = list(account.db.spend_recent or [])
    recent.append(entry)
    account.db.spend_recent = recent[-RECENT:]


# ---------------------------------------------------------------------------
# Reading it back
# ---------------------------------------------------------------------------

def totals(account):
    """What this account has spent, as plain integers."""
    stored = dict((account.db.spend_totals if account else None) or {})
    stored.setdefault("calls", 0)
    stored.setdefault("prompt", 0)
    stored.setdefault("completion", 0)
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
