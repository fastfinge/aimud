"""
Summarising a character's memories through the game's own model.

Sleep -- mnemosyne's consolidation -- turns a run of remembered events into a
summary, and it was doing that on a **local model running on the CPU**. On a
live server that cost 5.7 CPU-hours in one afternoon and never finished: the
pass runs over every bank, a restart starts a fresh one, and each pass took
longer than the gap between restarts, so the work simply accumulated. A player
walking east waited four minutes for a room while it ground away.

The same objection was already made about the other half of this pipeline and
acted on. `world.memory`'s note above `distillable` says mnemosyne can extract
facts itself but "must not be used that way here: it runs a local model per
line, measured at about eighty times the cost of a plain write ... so the work
is done here instead, in batches, out of hours, against the model the game is
already configured with." Distilling moved to OpenRouter; consolidation never
did. This is that same move, for sleep.

**A MUD server should not need a fast CPU to remember anything.** The game
already has a key, a service, a ledger and a model per job, and summarising is
a job like any other -- so it is `summaries` in `settings models`, separate
from `memory`, because a bulk background summariser wants a cheap fast model
while answering `remember` is a player waiting on an answer.

mnemosyne is asked through its host-backend registry, which exists for this:
one method, a prompt in and text or None out, consulted before its own
remote/local chain. That maps exactly onto `llm.ask`, which is synchronous and
thread-only, and consolidation already runs in a thread.

Two things about it are intrusive enough to say out loud:

* **Its settings are read at import.** `HOST_LLM_ENABLED` and friends are
  module constants filled from the environment when `local_llm` is first
  imported, so setting `os.environ` afterwards does nothing. `install` sets
  the attributes instead, which is order-independent and does not depend on
  being called before anything else touches mnemosyne.

* **A failed host call falls straight back to the local model.** That is
  mnemosyne's documented precedence and there is no setting that turns it off
  -- `MNEMOSYNE_FORCE_LOCAL` governs a different branch, `MNEMOSYNE_LLM_ENABLED`
  switches the host off along with the local model, and the model cache path is
  not configurable at all. Left alone, one refused request would put the CPU
  back to work for twenty minutes. So the local loader is stubbed out, and a
  host failure becomes no summary this pass -- which is what
  `world.memory`'s first rule asks for anyway: memory is never allowed to
  break the game, and a summary not written is a no-op that the next sleep
  will find again.
"""

from evennia.utils import logger

from world import llm

#: What the backend calls itself in mnemosyne's registry.
BACKEND_NAME = "aimud"

#: The model job. Its own, not `memory`: see the module docstring.
JOB = "summaries"

#: How long one summary may take. Longer than a chat turn, because nobody is
#: waiting on it -- sleep only runs when the game has gone quiet -- and a
#: summary of thirty events is a long answer.
TIMEOUT = llm.SLOW_TIMEOUT

#: Who pays for the bank being slept right now, and which model does it.
#:
#: A module-level pair rather than an argument, because nothing can be passed:
#: mnemosyne calls the backend from inside its own summariser, several frames
#: below anything of ours, and hands it a prompt and nothing else.
#:
#: Safe despite being global, for a reason worth writing down: `memory._lock`
#: is held for the whole of `_consolidate_sync`, so exactly one bank is ever
#: being slept at a time. The lock that made the CPU problem so visible is the
#: same lock that makes this correct.
_paying = {"sponsor": None, "model": None}


def paying_for(sponsor, model):
    """
    A context manager naming who pays for the summaries made inside it.

    Both are resolved on the main thread by the caller -- a sponsor reaches
    the database -- and only used in the thread, which is the same division
    `fact_gen` makes for distilling.
    """
    import contextlib

    @contextlib.contextmanager
    def held():
        before = dict(_paying)
        _paying["sponsor"], _paying["model"] = sponsor, model
        try:
            yield
        finally:
            _paying.update(before)

    return held()


def _complete(prompt, *, max_tokens, temperature, timeout,
              provider=None, model=None):
    """
    One summary, as mnemosyne's host backend wants it: text, or None.

    None is a real answer here and not an error to shout about. A world whose
    creator has no key cannot have its memories summarised, and saying so once
    per pass in the log is worth more than a traceback per bank.

    `provider` and `model` are mnemosyne's own overrides and are ignored: which
    model answers for a job belongs to whoever pays, and that is what
    `settings models` is for.
    """
    sponsor, chosen = _paying["sponsor"], _paying["model"]
    if sponsor is None or not chosen:
        return None
    messages = [
        {"role": "system",
         "content": "You summarise what a character in a story remembers. "
                    "Answer with the summary and nothing else."},
        {"role": "user", "content": prompt},
    ]
    try:
        return llm.ask(sponsor, chosen, messages,
                       timeout=timeout or TIMEOUT) or None
    except llm.MODEL_ERRORS as refused:
        # Not a raise: mnemosyne takes None as "no summary", which is the
        # degradation `world.memory` promises. Raising here would abandon the
        # rest of the pass over one bad bank.
        logger.log_info(f"summaries: {chosen} would not summarise a bank "
                        f"({refused})")
        return None


def install():
    """
    Point mnemosyne's summariser at this game's model. Idempotent.

    Called once at server start. Answers True when the host backend is in
    place, False when mnemosyne is not installed -- in which case there is
    nothing to route and memory is already a no-op.
    """
    try:
        from mnemosyne.core import llm_backends, local_llm
    except Exception as missing:
        logger.log_info(f"summaries: no mnemosyne to configure ({missing})")
        return False

    # Set on the module, not the environment: these are read at import time.
    local_llm.HOST_LLM_ENABLED = True
    local_llm.HOST_LLM_TIMEOUT = TIMEOUT
    # Left unset so `_complete` answers with the job's model rather than
    # whatever an environment variable happens to say.
    local_llm.HOST_LLM_PROVIDER = None
    local_llm.HOST_LLM_MODEL = None

    # The local model, stubbed rather than configured, because it cannot be
    # configured -- see the module docstring. `_call_local_llm` asks
    # `_load_llm` for an instance and gives up quietly when there is none.
    local_llm._load_llm = lambda: None

    llm_backends.set_host_llm_backend(
        llm_backends.CallableLLMBackend(BACKEND_NAME, _complete))
    return True


def installed():
    """Whether this game's backend is the one mnemosyne would ask."""
    try:
        from mnemosyne.core import llm_backends

        backend = llm_backends.get_host_llm_backend()
    except Exception:
        return False
    return getattr(backend, "name", "") == BACKEND_NAME


def payer_for(bank):
    """
    Whoever pays to summarise one bank, and the model they chose. Main thread.

    `(sponsor, model)`, or `(None, None)` for a bank nobody can pay for. The
    same answer `fact_gen._account_for` gives: a bank is named for its world,
    and the world's creator pays, through `sponsor.for_upkeep` -- which lets
    an unshared world be slept with its creator logged out and a shared one
    not (docs/archived/shared-worlds.md 5.4).

    There used to be a stand-in: any account with a key paid for a world
    whose maker had gone, so that its memories were still thought about. On
    a server where worlds are shared that spends a stranger's key on
    somebody else's world, so it is gone. A bank with no payer is still
    slept, without a summary, as `memory._consolidate_sync` already allows.
    """
    from evennia.objects.models import ObjectDB

    from world import memory, sponsor as sponsor_mod

    owner = memory._owner_id(bank)
    if owner is None:
        return None, None
    world_root = ObjectDB.objects.filter(id=owner).first()
    if world_root is None:
        return None, None
    sponsor = sponsor_mod.for_upkeep(world_root)
    if not sponsor.answers:
        return None, None
    return sponsor, sponsor.model_for(JOB, "memory")


def payers_for(banks):
    """{bank: (sponsor, model)} for a whole pass. Main thread."""
    return {bank: payer_for(bank) for bank in banks}
