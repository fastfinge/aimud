"""
Looking after the game rather than playing in it, as subjects.

  view commonsense                 whether the second lexicon is here
  import commonsense [yes]         download and index it
  view memory                      what memory upkeep would do
  edit memory [sleep|sweep|distil|all] [yes]
  view rounds [<job>] [world <n>]  how many rounds model conversations take
  reset rounds [yes]               start counting them again

These were `commonsense`, `memcheck` and `rounds`. The lexicon and memory are
builders' business, as they were; round counts are every account's own.
"""

from commands.subjects import (Subject, Use, account_of, answered, asking,
                               builder, require_builder)
from world import menus


def _caller(ctx):
    return ctx.character or ctx.caller


# ---------------------------------------------------------------------------
# The second lexicon
# ---------------------------------------------------------------------------

def commonsense_report():
    """
    What the second lexicon knows, or that it is not here.

    Nothing depends on it. Every lookup answers neutrally when it is absent,
    which is the ordinary state of a fresh install.
    """
    from world import commonsense

    if not commonsense.available():
        return ("|wNo second lexicon.|n Nothing is wrong: state groups, body "
                "parts and anchor suggestions are guessed rather than looked "
                "up, which is how this game has always worked.\n"
                "|wimport commonsense|n downloads it. It is large.\n"
                f"|x{commonsense.ATTRIBUTION}|n")

    edges, megabytes = commonsense.size()
    lines = [f"|w{edges} edges|n, {megabytes} MB, at |w{commonsense.PATH}|n.",
             "A few things it knows, as a sanity check:"]
    for word in ("open", "bird", "chest"):
        opposite = commonsense.opposites(word, limit=3)
        parts = commonsense.parts_of(word, limit=3)
        sorts = commonsense.kinds_of(word, limit=3)
        known = []
        if opposite:
            known.append("not also " + ", ".join(opposite))
        if parts:
            known.append("has " + ", ".join(parts))
        if sorts:
            known.append("is a " + ", ".join(sorts))
        lines.append(f"  {word}: {'; '.join(known) or 'nothing'}")
    lines.append(f"|x{commonsense.ATTRIBUTION}|n")
    return "\n".join(lines)


def fetch_commonsense(caller):
    """Download and index the corpus in the background. Returns what to say."""
    from world import busy, commonsense, llm

    if commonsense.available():
        return (f"It is already here. Delete |w{commonsense.PATH}|n and import "
                f"it again to rebuild it.")
    caller.msg("Fetching the second lexicon. This is a large download and will "
               "take a while; carry on playing.\n"
               f"|x{commonsense.ATTRIBUTION}|n")
    # No lifetime: a large download can honestly take longer than any model
    # call, and stopping the notices would say it had stopped.
    wait = busy.start(caller, "fetching the second lexicon", lifetime=None)
    llm.fetch(
        commonsense.download,
        on_success=busy.closing(wait, lambda kept: caller.msg(
            f"|wSecond lexicon ready.|n {kept} edges indexed. Nothing in the "
            f"game needed it; it is a little better informed now.")),
        on_error=busy.closing(wait, lambda failure: caller.msg(
            f"|rCould not fetch it: {failure.getErrorMessage()}|n\n"
            f"|xNothing is broken. The game runs without it.|n")))
    return None


DOWNLOAD_QUESTION = ("Download the second lexicon? It is large and takes a "
                     "while, though the game carries on meanwhile.")


def view_commonsense_run(cmd, ctx, words):
    if require_builder(cmd.caller):
        cmd.caller.msg(commonsense_report())


def import_commonsense_run(cmd, ctx, words):
    caller = cmd.caller
    if not require_builder(caller):
        return
    _words, yes = answered(words)

    def fetch():
        said = fetch_commonsense(caller)
        if said:
            caller.msg(said)

    asking(cmd, DOWNLOAD_QUESTION, "download", "import commonsense", fetch,
           already=yes)


# ---------------------------------------------------------------------------
# Memory upkeep
# ---------------------------------------------------------------------------

def memory_report():
    from world import memory

    if not memory.available():
        return "The memory backend is not available."
    banks = memory._bank_names()
    stranded = memory.orphaned_banks()
    lines = [f"|wMemory banks:|n {len(banks)} "
             f"({len(banks) - len(stranded)} in use, {len(stranded)} orphaned)"]
    for name in stranded[:10]:
        lines.append(f"  |x{name}: character #{name.rsplit('-', 1)[1]} is gone|n")
    if len(stranded) > 10:
        lines.append(f"  |x...and {len(stranded) - 10} more|n")
    lines.append("\n|wedit memory|n consolidates, clears up and distils.")
    return "\n".join(lines)


def tend_memory(caller, what):
    """
    Sleep, sweep, distil, or all three. Everything is sent as it happens.

    Sleeping is what makes a memory permanent. Sweeping deletes banks nothing
    can reach. Distilling asks the memory model what each character now knows,
    and is the only part that costs anything.
    """
    from world import memory

    if not memory.available():
        caller.msg("The memory backend is not available.")
        return
    banks = memory._bank_names()
    stranded = memory.orphaned_banks()

    if what in ("sleep", "all"):
        caller.msg(f"Consolidating {len(banks)} bank(s) in the background...")
        memory.consolidate(on_done=lambda result: caller.msg(
            f"Consolidated. "
            f"{sum(1 for r in result.values() if isinstance(r, dict) and r.get('status') != 'no_op')} "
            f"of {len(result)} bank(s) had anything old enough to sleep on."))

    if what in ("sweep", "all"):
        if not stranded:
            caller.msg("No orphaned banks to clear up.")
        else:
            caller.msg(f"Clearing up {len(stranded)} orphaned bank(s)...")
            memory.drop_banks(stranded, on_done=lambda removed: caller.msg(
                f"Deleted {len(removed)} bank(s)."))

    if what in ("distil", "all"):
        from world.fact_gen import distil

        caller.msg("Distilling recent summaries into facts...")
        distil(on_done=lambda tally: caller.msg(
            f"Distilled {tally['facts']} fact(s) from "
            f"{tally['characters']} character(s)."))


MEMORY_TASKS = [
    ("sleep", "Consolidate now",
     "Sleeping is what makes a memory permanent. It happens on a clock and at "
     "every server start; this is for doing it now.", None),
    ("sweep", "Delete banks nothing can read any more",
     "A world that has been removed, and anything left under an older naming. "
     "Nothing will ever ask for them again.", "sweep_memory"),
    ("distil", "Turn recent summaries into what characters know",
     "Asks the memory model what each character now knows. The only part of "
     "this that costs anything.", None),
    ("all", "All three", "Sleep, sweep and distil, in that order.",
     "sweep_memory"),
]

SWEEP_QUESTION = ("Delete every memory bank nothing can read any more? "
                  "Deleted memories are gone for good.")


EDIT_MEMORY = menus.Form(
    key="memory", title="Memory upkeep", intro=lambda ctx: memory_report(),
    items=[menus.Action(key, label,
                        run=lambda ctx, key=key: tend_memory(_caller(ctx), key),
                        confirm=confirm,
                        question=SWEEP_QUESTION if confirm else None,
                        after=menus.CLOSE, help=about,
                        command=lambda ctx, key=key: f"edit memory {key}")
           for key, label, about, confirm in MEMORY_TASKS],
)


def view_memory_run(cmd, ctx, words):
    if require_builder(cmd.caller):
        cmd.caller.msg(memory_report())


def edit_memory_run(cmd, ctx, words):
    caller = cmd.caller
    if not require_builder(caller):
        return
    words, yes = answered(words)
    if not words:
        menus.open_menu(caller, EDIT_MEMORY, session=cmd.session)
        return
    what = words[0].lower()
    task = next((task for task in MEMORY_TASKS if task[0] == what), None)
    if task is None:
        caller.msg("Memory can sleep, sweep, distil, or all: |wedit memory "
                   "sleep|n.")
        return
    if task[3]:
        asking(cmd, SWEEP_QUESTION, task[3], f"edit memory {what}",
               lambda: tend_memory(caller, what), already=yes)
        return
    tend_memory(caller, what)


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------

def _round_line(job, row):
    """One job, the count first, so it is the first thing heard."""
    loops = row["loops"]
    parts = [f"{loops} {'conversation' if loops == 1 else 'conversations'}"]
    if loops:
        parts.append(f"{row['rounds'] / loops:.1f} rounds on average")
        parts.append(f"{row['most_rounds']} at most")
    if row["limit"]:
        parts.append(f"budget {row['limit']}")
    parts.append(f"{row['forced']} made to answer")
    if row["failed"]:
        parts.append(f"{row['failed']} failed or ran out")
    if loops and row["seconds"]:
        parts.append(f"{row['seconds'] / loops:.0f} seconds on average")
    return f"{job}: " + ", ".join(parts) + "."


def _rounds_in_full(job, row):
    lines = [_round_line(job, row)]
    loops = row["loops"] or 1
    lines.append(f"{row['complaints']} answers sent back to be put right, "
                 f"{row['complaints'] / loops:.1f} a conversation.")
    tools = sorted(row["tools"].items(), key=lambda pair: (-pair[1], pair[0]))
    if tools:
        lines.append("Tools used: " + ", ".join(
            f"{name} {calls} {'time' if calls == 1 else 'times'}"
            for name, calls in tools) + ".")
    if row["hints_shown"]:
        lines.append(f"{row['hints_used']} of {row['hints_shown']} hints were "
                     f"used.")
    return "\n".join(lines)


def rounds_report(account, job="", root=None):
    """
    How many rounds each job's conversations take, or one job in full.

    When the game asks a model something, the model may look things up before
    it answers, and every look is a round: another call, and more waiting.
    """
    from world import ledger, lore

    figures = ledger.loops(account, root.id) if root is not None \
        else ledger.loops(account)
    where = f" in {lore.title(root)}" if root is not None else ""
    if job:
        row = figures.get(job)
        if not row or not row["loops"]:
            return f"No conversations have been counted for {job} yet."
        return _rounds_in_full(job, row)
    if not figures:
        return f"No conversations with tools have been counted{where} yet."
    ordered = sorted(figures.items(), key=lambda pair: (-pair[1]["loops"],
                                                        pair[0]))
    return "\n".join(_round_line(job, row) for job, row in ordered)


def view_rounds_run(cmd, ctx, words):
    from commands.world_subject import resolve_worlds

    caller = cmd.caller
    account = account_of(caller)
    job, root = "", None
    lowered = [word.lower() for word in words]
    if "world" in lowered:
        at = lowered.index("world")
        number = words[at + 1] if at + 1 < len(words) else ""
        worlds = resolve_worlds(account)
        try:
            root = worlds[int(number) - 1][0]
        except (ValueError, IndexError):
            caller.msg("Give a world's number, as |wview worlds|n lists them: "
                       "|wview rounds world 1|n.")
            return
        lowered = lowered[:at] + lowered[at + 2:]
    job = " ".join(lowered)
    caller.msg(rounds_report(account, job, root))


RESET_QUESTION = ("Clear every round count? What has been spent is kept, but "
                  "what was measured is discarded.")


def reset_rounds(caller):
    from world import ledger

    ledger.forget_loops(account_of(caller))
    return "Round counts cleared. What has been spent is kept."


def reset_rounds_run(cmd, ctx, words):
    caller = cmd.caller
    _words, yes = answered(words)
    asking(cmd, RESET_QUESTION, "reset_rounds", "reset rounds",
           lambda: caller.msg(reset_rounds(caller)), already=yes)


# ---------------------------------------------------------------------------
# The subjects
# ---------------------------------------------------------------------------

def _has_account(ctx):
    return account_of(_caller(ctx)) is not None


SUBJECTS = [
    Subject(
        "commonsense", ("commonsense", "lexicon"),
        uses={
            "view": Use(view_commonsense_run, lambda ctx: [menus.Action(
                "commonsense", "The second lexicon",
                run=lambda ctx: commonsense_report(), after=menus.CLOSE,
                command=lambda ctx: "view commonsense",
                help="Whether the commonsense lexicon is here, and a sample "
                     "of what it knows.")], offered=builder),
            "import": Use(import_commonsense_run, lambda ctx: [menus.Action(
                "commonsense", "The second lexicon",
                run=lambda ctx: fetch_commonsense(_caller(ctx)),
                confirm="download", question=DOWNLOAD_QUESTION,
                after=menus.CLOSE, command=lambda ctx: "import commonsense",
                help="Downloads the commonsense corpus and indexes it. It is "
                     "large.")], offered=builder),
        },
        help="The commonsense lexicon beside WordNet. For builders.",
    ),
    Subject(
        "memory", ("memory", "memories"),
        uses={
            "view": Use(view_memory_run, lambda ctx: [menus.Action(
                "memory", "Memory banks", run=lambda ctx: memory_report(),
                after=menus.CLOSE, command=lambda ctx: "view memory",
                help="How many memory banks there are, and how many are "
                     "orphaned.")], offered=builder),
            "edit": Use(edit_memory_run, lambda ctx: [menus.Submenu(
                "memory", "Memory upkeep", EDIT_MEMORY,
                help="Consolidate, clear up and distil memories now.")],
                offered=builder),
        },
        help="Characters' memory banks, and their upkeep. For builders.",
    ),
    Subject(
        "rounds", ("rounds", "round"),
        uses={
            "view": Use(view_rounds_run, lambda ctx: [menus.Action(
                "rounds", "Rounds model conversations take",
                run=lambda ctx: rounds_report(account_of(_caller(ctx))),
                after=menus.CLOSE, command=lambda ctx: "view rounds",
                help="For each job, how many rounds its conversations took and "
                     "how often the model had to be made to answer.")],
                offered=_has_account),
            "reset": Use(reset_rounds_run, lambda ctx: [menus.Action(
                "rounds", "Round counts",
                run=lambda ctx: reset_rounds(_caller(ctx)),
                confirm="reset_rounds", question=RESET_QUESTION,
                after=menus.CLOSE, command=lambda ctx: "reset rounds",
                help="Start counting rounds again, after a change worth "
                     "measuring.")], offered=_has_account),
        },
        help="How many rounds the game's conversations with models take.",
    ),
]
