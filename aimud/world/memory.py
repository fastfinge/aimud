"""
Per-character memory, backed by mnemosyne.

Every world owns a mnemosyne bank, and every character in it owns a session
inside that bank. Where they have been, what they have witnessed and what they
have done is written there as it happens, and pulled back out by relevance when
they need it.

It was one bank per character, which is file-level isolation and sounds
stronger. It made three things impossible: deleting a world's memories with
the world, remembering anything about a world rather than about one person,
and two players in one world sharing anything at all. See `bank_for`.  That is what keeps an NPC's prompt small: instead of replaying the last
thirty events at the model every time, we send the handful that bear on what
is happening now, drawn from a history with no length limit.

Two rules govern everything here:

* Memory is never allowed to break the game.  If mnemosyne is missing or
  throws, every function in this module degrades to a no-op and play carries
  on without memory.
* Memory work never runs on the reactor thread.  Writes are fired into the
  thread pool; reads are done inside a thread that is already deferred, in
  the same place the OpenRouter call happens.  A synchronous recall on the
  main thread would stall every player in the game.
"""

import re
import threading
from collections import namedtuple

from twisted.internet import threads

from evennia.utils import logger

_backend = None
_state = "unknown"          # unknown | ready | missing

#: Set when the server is going down. Writes stop being accepted at that
#: point: they are serialised behind one lock at roughly a fifth of a second
#: each, so a busy world can leave a queue that Twisted then waits for while
#: shutting down its thread pool. Six seconds of that is enough for the
#: replacement server to find the webserver port still held, and the reload
#: fails outright.
_closing = False

#: Most writes that may be waiting at once. Past this the oldest events are
#: worth more than the newest ones are worth waiting for.
MAX_PENDING = 12
_pending = 0

#: mnemosyne keeps one SQLite connection, and SQLite connections are not
#: shared between threads. Every call goes through this lock, so a burst of
#: remembered events queues instead of colliding -- without it the log fills
#: with "cannot start a transaction within a transaction" and
#: "bad parameter or other API misuse", and memories are silently lost.
#: The import is held under the same lock, since it must happen exactly once.
_lock = threading.Lock()


def _load_locked():
    """Import mnemosyne. Caller must hold _lock, and must be in a thread."""
    global _backend, _state
    if _state == "unknown":
        try:
            _configure_backend()
            import mnemosyne

            _backend, _state = mnemosyne, "ready"
        except Exception as exc:
            _backend, _state = None, "missing"
            logger.log_info(
                f"mnemosyne unavailable, characters will not form memories: {exc}"
            )
    return _backend


def _with_backend(action):
    """
    Run `action(mnemosyne)` on the one connection, one caller at a time.

    MUST be called from a thread. The import alone pulls in the embedding
    stack and takes seconds, so doing any of this on the reactor would stall
    every player in the game.
    """
    with _lock:
        backend = _load_locked()
        if backend is None:
            return None
        return action(backend)


#: One Mnemosyne per (bank, session). Both are constructor arguments -- neither
#: the module functions nor the instance methods take a session per call -- so
#: the single global instance this used to keep cannot express "this
#: character, in this world" at all.
#:
#: The docstring on `_lock` still holds and now means something slightly
#: different: it is still one caller at a time, and still because SQLite
#: connections are not shared between threads, but it is no longer one
#: connection in total. It is one per bank, which is one per world.
_INSTANCES = {}


def _memory_locked(bank, session):
    """One character's view of one world's bank. Caller must hold _lock."""
    backend = _load_locked()
    if backend is None:
        return None
    key = (bank, session)
    found = _INSTANCES.get(key)
    if found is None:
        found = backend.Mnemosyne(bank=bank, session_id=session)
        _INSTANCES[key] = found
    return found


def _with_memory(bank, session, action):
    """
    Run `action(memory)` against one bank and session. MUST be in a thread.

    The same contract `_with_backend` has, and for the same reasons; what
    differs is that the thing handed over is scoped rather than global.
    """
    if not bank:
        return None
    with _lock:
        memory = _memory_locked(bank, session)
        return action(memory) if memory is not None else None


def _forget_instances(bank=None):
    """
    Let go of cached instances, so their files can be deleted.

    On Windows an open handle is what makes a directory undeletable, which is
    the whole reason `_close_quietly` exists. A bank about to be deleted has
    to be dropped here first or the sweep silently does nothing.
    """
    with _lock:
        for key in [k for k in _INSTANCES if bank is None or k[0] == bank]:
            _close_quietly(_INSTANCES.pop(key))


def warm_up():
    """
    Load mnemosyne in the background at server start.

    Without this the first remembered event pays for the import, and it would
    pay for it wherever that happened to be.
    """
    threads.deferToThread(_with_backend, lambda _backend: None).addErrback(_swallow)


def _configure_backend():
    """
    Settle mnemosyne's environment before it is first imported.

    Anything already set explicitly is left alone, so a deployment can
    override any of this without editing code.
    """
    import os

    # Keep memories inside the game directory. mnemosyne otherwise stores them
    # under the OS user's application data, which would leave a game's
    # memories behind when the game is copied, backed up or moved.
    if not os.environ.get("MNEMOSYNE_DATA_DIR"):
        from django.conf import settings

        os.environ["MNEMOSYNE_DATA_DIR"] = os.path.join(
            settings.GAME_DIR, "server", "memory"
        )

    # The richer recall pipeline: synonym expansion, decay weighting, and a
    # re-rank that prefers a varied answer over several sittings of the same
    # one. Measured against the plain path on a small bank it returns the same
    # rows in the same time, so it costs nothing to have on -- and what it
    # adds is aimed squarely at the weak point of the cues we ask with, which
    # are often a bare name with no sentence around it.
    os.environ.setdefault("MNEMOSYNE_ENHANCED_RECALL", "1")

    # Fact recall reads the facts tables, and something fills them now: the
    # engine writes what it knows through `world.recollection`, at a veracity
    # tier that says where it came from. It was off while they were empty.
    os.environ.setdefault("MNEMOSYNE_FACT_RECALL_ENABLED", "1")

    # Four voices instead of one: vectors, the episodic graph, the facts
    # above, and time. The graph and the fact voice were already being built
    # on every write and read by nothing.
    os.environ.setdefault("MNEMOSYNE_POLYPHONIC_RECALL", "1")

    # Session isolation is a WHERE clause, and this is the switch that
    # replaces it with `(1=1)`. Pinned rather than left to a default, because
    # with one bank per world the difference between it being on and off is
    # every character in a world reading every other character's memories.
    os.environ["MNEMOSYNE_CROSS_SESSION"] = "0"


def available():
    """
    True unless we already know mnemosyne is unusable.

    Deliberately does not trigger the import: this is called from command
    code on the reactor thread, and loading there is exactly what must not
    happen. Before the first load it answers optimistically and the worker
    thread finds out for certain.
    """
    return _state != "missing"


#: Where one character's memories are: which world's file, and whose clause
#: inside it. Two values because it takes two to say it now, and a pair rather
#: than two arguments so that adding a third later does not touch every
#: signature between here and `npc_gen`.
Where = namedtuple("Where", "bank session")


def where_for(character, world_root=None):
    """The bank and session a character's memories belong to."""
    if world_root is None:
        world_root = world_of(character)
    return Where(bank_for(world_root), session_for(character))


def bank_for(world_root):
    """
    The bank a world's memories live in.

    **One bank per world, not one per character**, which is the opposite of
    what this used to be and is worth the explanation. A bank is a separate
    SQLite file; a session is a `WHERE` clause inside one. Carving by
    character meant file-level isolation and three things that could not be
    had at any price:

    * a world's memories could not be deleted with the world, so every
      `worldreset` left a database file per character behind for a sweep to
      find later;
    * nothing could be remembered about a world rather than about one person
      in it, because there was nowhere for it to live;
    * and two players in one world could not share anything, which shared
      worlds needs -- an innkeeper cannot hold one memory about both of them
      if their memories are in different files.

    It also fixes a fault nobody had noticed. A player character plays many
    worlds and had ONE bank, and recall filtered by nothing, so memories of
    the haunted school were recallable aboard the freighter.

    Keyed by dbref rather than name: worlds get renamed, and a renamed world
    should keep its past.
    """
    return f"aimud-world-{world_root.id}" if world_root is not None else ""


def session_for(character):
    """
    The session a character's own memories live under, inside their world.

    Weaker isolation than a bank -- `(session_id = ? OR scope = 'global')` is
    a clause rather than a file -- and that is the trade: it buys world-wide
    memories, deletion with the world, and two players in one room. The clause
    is defended in `_configure_backend`, which pins the toggle that would
    switch it off.
    """
    return f"char-{character.id}" if character is not None else "default"


def world_of(character):
    """The world a character is standing in, for naming their bank."""
    room = getattr(character, "location", None)
    return getattr(room.db, "world_root", None) if room is not None else None


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def remember(character, text, kind="event", importance=0.5, about=(),
             metadata=None):
    """
    Record something into a character's memory. Fire-and-forget.

    kind is a coarse label ("moved", "said", "witnessed", "did") kept as the
    memory's source so recall can be biased later if we want it.
    importance is 0..1; the things a character did themselves matter more to
    them than things they merely saw.

    `about` is (name, dbref) for everything the memory concerns, and is the
    half of this that no extractor could supply: we know who was involved
    because binding resolved them. `metadata` rides along unread, so a
    recalled memory can be re-rendered with today's names rather than replayed
    as the sentence it was written as.

    Dropped rather than queued when the server is closing or the backlog is
    already long. A memory is worth having; it is not worth holding a shutdown
    open for, and a queue that outlives the process helps nobody.

    Deliberately does not ask mnemosyne to extract facts. It is offered as
    extract=True and it is a trap here: extraction runs a local model on every
    single line, which measured at twenty-five seconds a write against a third
    of a second without -- about eighty times slower. Writes are serialised
    behind one lock and dropped past MAX_PENDING, so one remark in a room of
    three would fill the queue and characters would stop remembering anything
    at all. What it produced was not usable either: the model's working-out
    arrived verbatim in the facts table.
    """
    global _pending

    if not text or _closing or not available():
        return
    if _pending >= MAX_PENDING:
        logger.log_info(
            f"memory: {_pending} writes already waiting, dropping one for "
            f"{character.key}"
        )
        return

    where = where_for(character)
    if not where.bank:
        return          # not in a world: nowhere for this to belong

    def _write():
        try:
            _remember_sync(where.bank, where.session, text, kind, importance,
                           about=about, metadata=metadata)
        finally:
            _finished()

    _pending += 1
    threads.deferToThread(_write).addErrback(_swallow)


def _finished():
    global _pending
    _pending = max(0, _pending - 1)


def stop():
    """
    Stop accepting memories, because the server is going down.

    Anything already running finishes; nothing new is queued behind it.
    """
    global _closing
    _closing = True


def _swallow(failure):
    """A memory that fails to save must not surface as a player-facing error."""
    logger.log_info(f"memory write failed: {failure.getErrorMessage()}")


def describe_event(event_type, actor_name, text):
    """
    One line of plain English for an event, as a character would recall it.

    Emote text already begins with the actor's name at some call sites and not
    at others, so the name is only prefixed when it is actually missing --
    otherwise events read as "Bob Bob smiles".
    """
    if event_type == "say":
        return f'{actor_name} said: "{text}"'
    # Some callers hand over text that already opens with the actor's name --
    # a pose, or an action narrated as a whole sentence. Prefixing it again
    # gives "Aria Delacroix Aria Delacroix lights the candle."
    if actor_name and text.startswith(actor_name):
        return text
    if event_type == "emote":
        return f"{actor_name} {text}"
    return f"{actor_name}: {text}"


def record_room_event(room, event_type, actor_name, text, actor=None):
    """
    Write an event to the memory of every player character in the room.

    NPCs record through their own history hook instead, so they are skipped
    here to avoid remembering the same moment twice.  The actor remembers
    doing it; everyone else remembers seeing it.
    """
    if not room or not available():
        return
    from evennia.objects.objects import DefaultCharacter

    line = describe_event(event_type, actor_name, text)
    for obj in room.contents:
        if not isinstance(obj, DefaultCharacter):
            continue
        if obj is actor:
            remember(obj, line, kind="did", importance=0.6)
        else:
            remember(obj, line, kind="witnessed", importance=0.4)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

#: Words that carry no memory of their own.  A player asks "have I met Cherrie
#: before?", and everything but "met Cherrie" only dilutes the match.
_QUESTION_WORDS = frozenset("""
    a an and the is are was were be been am do did does done have has had
    i me my mine myself you your yours we us our they them their it its
    what when where who whom whose which why how that this these those
    of in on at to for from with about into over after before again
    ever before any some there here can could shall should will would
    tell remember recall know knew say said ask asked
""".split())


def _query_variants(query):
    """
    The query, then a keyword-only version of it.

    Recall is scored against the whole query, so a natural question can fall
    below the relevance threshold on the strength of its filler alone -- the
    memory is there, but "have I met Cherrie before?" finds nothing while
    "met Cherrie" finds it.  Trying the question first keeps phrasing that
    does work working, and the reduction catches the rest.
    """
    variants = [query]
    keywords = " ".join(
        word for word in re.findall(r"[\w']+", query.lower())
        if word not in _QUESTION_WORDS
    )
    if keywords and keywords != query.lower():
        variants.append(keywords)
    return variants


def recall_sync(where, query, top_k=6, already_known=()):
    """
    Fetch relevant memories as a list of strings, best match first.

    MUST be called from inside a thread -- never the reactor.  Callers already
    running in a deferred fetch (the NPC dialogue call, the remember command)
    should call this directly there rather than paying for a second hop.

    `already_known` is anything the caller is going to show anyway. Those
    lines are dropped from the result, because a memory is only worth the
    space if it says something the prompt does not already say.

    That matters more than it sounds. A character remembers an event in the
    same words its working memory holds it in, and asks for memories using
    the last thing that happened -- so the closest match to the query is
    reliably the query itself. Left in, the last couple of events arrive
    twice: once as what just happened and again as what the character most
    strongly remembers, which reads as insistence and is a good way to talk
    a model into doing the same thing again. Extra hits are fetched to make
    up for the ones dropped, so filtering costs no recall depth.
    """
    if not query or not available():
        return []

    skip = {line for line in already_known if line}
    wanted = top_k + len(skip)

    found = []
    for variant in _query_variants(query):
        try:
            hits = _recall_sync(where.bank, where.session, variant, wanted)
        except Exception as exc:
            logger.log_info(f"memory recall failed: {exc}")
            return found[:top_k]
        for hit in hits:
            if hit not in found and hit not in skip:
                found.append(hit)
        if len(found) >= top_k:
            break
    return found[:top_k]


#: Most cues one recall will ask about.
#:
#: Each cue is its own search, so this is what stops a crowded room turning
#: one turn into a dozen lookups. The cues are given in priority order, so
#: trimming to this drops the least useful ones.
MAX_CUES = 6


def recall_for_cues(where, cues, top_k=6, per_cue=2, already_known=()):
    """
    Recall against several cues at once, taking a little from each.

    Asking one question built out of everything at once does not work. An
    embedding of "the Records Office, Cherrie, Aria, a brass key, wanting to
    find the ledger" is a little bit about five things and precisely about
    none of them, and it matches memories that are vaguely about everything.
    The rest of this module already knows that -- _query_variants exists
    because filler in a question buries the two words that carry it.

    So each cue is asked separately and the answers are interleaved, one from
    each in turn. That is deliberately breadth rather than depth: a character
    standing with three people should arrive with something about each of
    them, not six memories about whichever of them is most memorable.

    Cues are given best-first and honoured in that order, so when the budget
    runs out it is the weakest cue that goes without.
    """
    if not available():
        return []

    skip = {line for line in already_known if line}
    per_cue_hits = []
    for cue in list(cues)[:MAX_CUES]:
        if not cue:
            continue
        hits = recall_sync(where, cue, top_k=per_cue, already_known=skip)
        if hits:
            per_cue_hits.append(hits)

    found = []
    for rank in range(per_cue):
        for hits in per_cue_hits:
            if rank >= len(hits):
                continue
            if hits[rank] not in found:
                found.append(hits[rank])
                if len(found) >= top_k:
                    return found
    return found


# ---------------------------------------------------------------------------
# Sleeping
#
# Not an optimisation. mnemosyne trims working memory on every write, deleting
# anything older than MNEMOSYNE_WM_TTL_HOURS (a week by default) or past the
# most recent MNEMOSYNE_WM_MAX_ITEMS -- but only where consolidated_at IS NULL.
# Rows that have been through a sleep cycle are exempt and stay for good.
#
# So a character that never sleeps forgets everything after a week, and the
# claim at the top of this module -- a history with no length limit -- is only
# true of a game that runs one. Sleeping is what makes memory permanent.
#
# It costs nothing outside: consolidation uses a small local model where one is
# installed and falls back to compression where one is not, so no request
# leaves the machine and no API key is spent.
# ---------------------------------------------------------------------------

def _banks_sync():
    """A bank manager and every bank it knows. Must run in a thread."""
    import os
    from pathlib import Path

    from mnemosyne.core.banks import BankManager

    data_dir = os.environ.get("MNEMOSYNE_DATA_DIR")
    manager = BankManager(data_dir=Path(data_dir) if data_dir else None)
    return manager, list(manager.list_banks())


def _close_quietly(instance):
    """
    Let go of a bank's file handles, and let mnemosyne know they are gone.

    Opening a bank opens about five SQLite connections, not one: the beam
    connection plus one per substore. They are released when the instance is,
    but not until then -- and on Windows an open handle is what makes a
    directory undeletable, so a pass that left them open is what would stop
    the sweep working.

    Clearing the thread-local afterwards is not tidiness, it is the whole
    thing working at all. mnemosyne caches one connection per thread per
    path. Its beam cache checks the cached connection is alive and reconnects
    if not; the legacy cache in mnemosyne.core.memory only reconnects when the
    *path* changes, so a connection closed underneath it is handed straight
    back to the next caller, and every write for the rest of that thread's
    life fails with "Cannot operate on a closed database". Dropping the cache
    entry makes the next open a real one.
    """
    for holder in (instance, getattr(instance, "beam", None)):
        conn = getattr(holder, "conn", None)
        if conn is None:
            continue
        try:
            conn.close()
        except Exception:
            pass

    import sys

    for module in ("mnemosyne.core.memory", "mnemosyne.core.beam"):
        try:
            cache = getattr(sys.modules[module], "_thread_local", None)
            if cache is not None:
                cache.conn = None
                cache.db_path = None
        except Exception:
            pass

    # And the module-level instance mnemosyne keeps for its own remember() and
    # recall(): it holds the connection object directly rather than asking for
    # one each time, so it would go on using the closed handle no matter how
    # clean the caches behind it are. Dropping it costs one reconnect on the
    # next write and is the difference between memory working afterwards and
    # not.
    try:
        core = sys.modules.get("mnemosyne.core.memory")
        if core is not None:
            core._default_instance = None
    except Exception:
        pass


def _consolidate_sync(banks, force=False):
    """Sleep these banks. Returns {bank: result}. Must run in a thread."""
    def _run(backend):
        done = {}
        for bank in banks:
            instance = None
            try:
                # Each bank is its own SQLite file, so sleeping one says
                # nothing about the others: every character has to be slept in
                # its own right. sleep_all_sessions rather than sleep, because
                # a character whose last event predates the cutoff would
                # otherwise be skipped for having no "current" session.
                instance = backend.Mnemosyne(bank=bank)
                done[bank] = instance.sleep_all_sessions(force=force)
            except Exception as exc:
                logger.log_info(f"memory: could not sleep {bank!r}: {exc}")
            finally:
                if instance is not None:
                    _close_quietly(instance)
        return done

    return _with_backend(_run) or {}


def consolidate(force=False, on_done=None):
    """
    Async, fire-and-forget. Sleep every living character's memories.

    Safe to call often: a bank with nothing old enough to consolidate reports
    no_op and costs one query. Nothing is destroyed -- the originals stay
    recallable beside the summary sleep writes, and become permanent by having
    been consolidated at all.

    Banks whose character is gone are skipped rather than slept. There is
    nothing to be gained by summarising the memories of somebody who no longer
    exists, and opening one is what would stop the sweep deleting it.
    """
    if _closing or not available():
        return

    stranded = set(orphaned_banks())
    banks = [name for name in _bank_names() if name not in stranded]

    def _finished(result):
        slept = sum(
            1 for outcome in result.values()
            if isinstance(outcome, dict) and outcome.get("status") != "no_op"
        )
        if slept:
            logger.log_info(
                f"memory: consolidated {slept} of {len(result)} memory bank(s)"
            )
        if on_done:
            on_done(result)

    threads.deferToThread(_consolidate_sync, banks, force).addCallbacks(
        _finished, _swallow)


# ---------------------------------------------------------------------------
# Distilling
#
# Sleep turns a run of events into a summary. Distilling turns summaries into
# the handful of things that are simply true afterwards -- that Bram owes you a
# favour, that the ledger went missing in the winter -- which is what a
# character should still know when the events themselves have gone hazy.
#
# mnemosyne can do this itself, with extract=True on every write. It must not
# be used that way here: it runs a local model per line, measured at about
# eighty times the cost of a plain write, and what it produced was the model's
# own working-out rather than any fact. So the work is done here instead, in
# batches, out of hours, against the model the game is already configured with.
#
# The results are written back as ordinary memories rather than into
# mnemosyne's facts table. They are then recalled by exactly the machinery
# every other memory goes through, and made permanent by the next sleep, with
# nothing reaching into private APIs to make it work.
# ---------------------------------------------------------------------------

#: What a distilled memory is stored as, so it can be told from an event and
#: kept out of the next round's input.
FACT_SOURCE = "distilled"

#: How the high-water mark is kept, per bank, in mnemosyne's own scratchpad.
#: Held there rather than on the character because this is read and written
#: from a worker thread, where touching the game database is not allowed.
_MARK = "aimud-distilled-through:"

#: Most summaries handed to one extraction call.
MAX_DISTIL_INPUT = 40


def _distillable_sync(where):
    """
    (summaries, through) for one character. Must run in a thread.

    Only what sleep has already condensed is offered: raw events are many and
    repetitive, and summarising a summary is both cheaper and better than
    asking a model to read a week of somebody's afternoons.
    """
    def _run(instance):
        try:
            marker = ""
            for entry in (instance.scratchpad_read() or []):
                content = entry.get("content", "") if isinstance(entry, dict) else str(entry)
                if content.startswith(_MARK):
                    marker = max(marker, content[len(_MARK):])

            rows = [
                row for row in instance.get_all_memories()
                if row.get("source") == "sleep_consolidation"
                and str(row.get("timestamp") or "") > marker
            ]
            rows.sort(key=lambda row: str(row.get("timestamp") or ""))
            rows = rows[-MAX_DISTIL_INPUT:]
            if not rows:
                return [], marker
            through = str(rows[-1].get("timestamp") or "")
            return [row["content"] for row in rows if row.get("content")], through
        except Exception:
            return [], ""

    return _with_memory(where.bank, where.session, _run) or ([], "")


#: What a fact's veracity says about where it came from. mnemosyne's own
#: vocabulary, and it already draws the distinction this game needs.
#:
#: `tool` is for what the engine knows by construction -- who owns a thing,
#: where it is, what state it is in. `inferred` is for what a model read out
#: of somebody's afternoon: "Bram owes me a favour" is not derivable from any
#: event record and is exactly what the distillation is for.
#:
#: Writing both in is what makes the consolidator useful rather than decorative:
#: it does Bayesian confidence and records conflicts, so a distillation that
#: hallucinates an owner against an engine fact becomes a recorded disagreement
#: at differing tiers instead of pollution nobody notices.
FROM_ENGINE = "tool"
FROM_MODEL = "inferred"


def note_fact(where, subject, predicate, object_, veracity=FROM_ENGINE):
    """
    Record one structured fact, where recall can actually find it.

    The distinction from `remember` is the one mnemosyne draws between
    episodic and semantic memory, and it is worth keeping: an event is true
    for ever because it happened, while a fact can stop being true. This is
    the second sort.
    """
    if _closing or not available() or not (subject and predicate):
        return
    threads.deferToThread(
        _note_fact_sync, where, str(subject), str(predicate), str(object_),
        veracity).addErrback(_swallow)


def _note_fact_sync(where, subject, predicate, object_, veracity):
    """Runs in a thread. Never raises: a fact is not worth losing a turn for."""
    def _run(_memory):
        from mnemosyne.core.veracity_consolidation import VeracityConsolidator

        consolidator = VeracityConsolidator()
        try:
            consolidator.consolidate_fact(subject=subject, predicate=predicate,
                                          object=object_, veracity=veracity)
        finally:
            _close_quietly(consolidator)

    try:
        return _with_memory(where.bank, where.session, _run)
    except Exception as exc:
        logger.log_info(f"memory: could not record a fact: {exc}")
        return None


def _store_facts_sync(where, facts, through):
    """Write distilled facts back, and move the mark. Must run in a thread."""
    def _run(instance):
        if True:
            for fact in facts:
                instance.remember(
                    fact,
                    source=FACT_SOURCE,
                    # Higher than anything witnessed: a thing that is simply
                    # true outranks any single evening it was learned on.
                    importance=0.8,
                    # What it is, said where the fact voice reads. Stored as an
                    # ordinary memory too, because the sentence is the useful
                    # form for a prompt and the tier is the useful form for
                    # weighing it against what the engine knows.
                    veracity=FROM_MODEL,
                )
            if through:
                instance.scratchpad_write(f"{_MARK}{through}")
            return len(facts)

    return _with_memory(where.bank, where.session, _run) or 0


def distillable(where, on_done):
    """Async. Hand `on_done(summaries, through)` what is worth distilling."""
    if _closing or not available():
        on_done([], "")
        return
    threads.deferToThread(_distillable_sync, where).addCallbacks(
        lambda result: on_done(*result), lambda _f: on_done([], ""))


def store_facts(where, facts, through, on_done=None):
    """
    Async. Record distilled facts and remember how far we have read.

    Called with no facts as well as with some, and it still runs: a quiet
    stretch that yielded nothing has genuinely been read, and leaving the mark
    where it was would offer those same summaries up again on every pass for
    ever.
    """
    if (not facts and not through) or _closing or not available():
        if on_done:
            on_done(0)
        return
    threads.deferToThread(_store_facts_sync, where, facts, through).addCallbacks(
        on_done or (lambda _n: None), _swallow)


def forget_world(world_root, on_done=None):
    """
    Delete a world's memories, because the world is gone.

    Called from `worldreset` and `worldremove`. This is the whole practical
    argument for one bank per world: it used to be impossible -- a world's
    memories were scattered across one file per character, named for dbrefs
    that told you nothing about which world they had been in, and the only way
    to find them was a scheduled sweep looking for characters that no longer
    existed.
    """
    name = bank_for(world_root)
    if not name:
        if on_done:
            on_done(0)
        return
    _forget_instances(name)
    drop_banks([name], on_done=on_done)


def living_places():
    """
    Every (bank, session) with somebody behind it. Main thread -- reads the DB.

    A bank is a world now, so "which memories are worth working on" is no
    longer answered by listing files: one file holds every character in a
    world, and distillation is still per character. So the question is asked
    of the characters instead, which is where the answer always was.
    """
    from world.quests import is_person

    from evennia.objects.models import ObjectDB

    found = []
    for obj in ObjectDB.objects.all():
        try:
            if not is_person(obj):
                continue
            where = where_for(obj)
        except Exception:
            continue
        if where.bank:
            found.append(where)
    return found


# ---------------------------------------------------------------------------
# Clearing up after the dead
#
# This used to be a scheduled sweep with real work to do: a bank was named for
# a character, so deleting a world left one file behind per person who had
# been standing in it, and something had to come along afterwards and notice.
#
# A bank is a world now, and `worldreset` and `worldremove` delete it outright
# -- so the sweep finds nothing in the ordinary case and exists for the two it
# cannot cover: a world removed by a route that did not know to say so, and
# every bank left over from the old per-character naming.
# ---------------------------------------------------------------------------

#: The shape of a bank this game owns. Anything else in the data directory
#: belongs to something that is not us and is never touched.
#:
#: Both spellings, because the old ones are still on disk and are exactly what
#: the sweep is now for. A character bank belongs to a numbering that will not
#: be issued again, so it is orphaned by definition.
_BANK_PATTERN = re.compile(r"^aimud-world-(\d+)$")
_OLD_BANK_PATTERN = re.compile(r"^aimud-char-(\d+)$")


def _owner_id(bank):
    """The dbref a bank belongs to, or None if the name is not one of ours."""
    match = _BANK_PATTERN.match(str(bank or ""))
    return int(match.group(1)) if match else None


def _is_ours(bank):
    """Whether this game put it there, under either naming."""
    name = str(bank or "")
    return bool(_BANK_PATTERN.match(name) or _OLD_BANK_PATTERN.match(name))


def orphaned_banks():
    """
    Banks whose character no longer exists. Main thread -- it reads the DB.

    Reading the game database here rather than in the worker is the whole
    safety of this: the decision to delete is made where the answer is
    certain, and the thread is handed a list of names rather than a rule.
    """
    from evennia.objects.models import ObjectDB

    known = set(
        ObjectDB.objects.values_list("id", flat=True)
    )
    stranded = []
    for bank in _bank_names():
        if _OLD_BANK_PATTERN.match(str(bank)):
            # Named for a character, which is a scheme this game no longer
            # uses. Whatever is in it was written against the old carving and
            # cannot be read back under the new one.
            stranded.append(bank)
            continue
        owner = _owner_id(bank)
        if owner is not None and owner not in known:
            stranded.append(bank)
    return stranded


def _bank_names():
    """
    Every bank on disk, read straight off the directory. Main thread safe.

    Deliberately does not go through mnemosyne: this is called to decide what
    to delete, and it must not be the thing that imports the embedding stack
    onto the reactor.
    """
    import os
    from pathlib import Path

    data_dir = os.environ.get("MNEMOSYNE_DATA_DIR")
    if not data_dir:
        from django.conf import settings

        data_dir = os.path.join(settings.GAME_DIR, "server", "memory")
    banks = Path(data_dir) / "banks"
    if not banks.is_dir():
        return []
    return sorted(
        entry.name for entry in banks.iterdir()
        if entry.is_dir() and _is_ours(entry.name)
    )


def drop_banks(names, on_done=None):
    """
    Async, fire-and-forget. Delete these banks for good.

    Takes names rather than characters, because the characters are gone by the
    time anybody asks. Whatever the caller hands over is deleted, so the
    caller is the one that has to be sure -- see orphaned_banks.
    """
    names = [n for n in names if _is_ours(n)]
    if not names or not available():
        if on_done:
            on_done([])
        return

    def _run(backend):
        manager, existing = _banks_sync()
        removed = []
        for name in names:
            if name not in existing:
                continue
            try:
                manager.delete_bank(name, force=True)
                removed.append(name)
            except PermissionError:
                # Windows will not unlink a file something still has open.
                # Nothing opens a dead character's bank on purpose, so this
                # means one was read before it was known to be orphaned. The
                # sweep at the next server start runs before anything opens a
                # bank at all, and will get it then.
                logger.log_info(
                    f"memory: {name!r} is still open; leaving it for the "
                    f"sweep at next startup"
                )
            except Exception as exc:
                logger.log_info(f"memory: could not delete {name!r}: {exc}")
        return removed

    def _finished(removed):
        if removed:
            logger.log_info(
                f"memory: deleted {len(removed)} memory bank(s) whose "
                f"character no longer exists"
            )
        if on_done:
            on_done(removed)

    threads.deferToThread(_with_backend, _run).addCallbacks(_finished, _swallow)


def forget_character(character):
    """Drop one character's memories, because it is being deleted."""
    if character is None:
        return
    drop_banks([bank_for(character)])


def sweep_orphans(on_done=None):
    """Delete every bank whose character is gone. Main thread."""
    stranded = orphaned_banks()
    drop_banks(stranded, on_done=on_done)
    return stranded


def format_memories(memories):
    """Render recalled memories for a prompt."""
    if not memories:
        return "(nothing comes to mind)"
    return "\n".join(f"- {m}" for m in memories)


# ---------------------------------------------------------------------------
# The mnemosyne boundary
#
# Everything above is game logic; only these two functions know what the
# library looks like, so a change there is contained here.
# ---------------------------------------------------------------------------

def _remember_sync(bank, session, text, kind, importance, about=(),
                   metadata=None):
    """
    Store one memory, and say what it was about. Runs in a thread.

    The `memory_id` that `remember` returns was thrown away until now, and it
    is the handle everything else needs: it is what an annotation hangs on.

    **Entities are written rather than extracted.** mnemosyne's own extractor
    is a capitalised-word regex against a stop list, and the stop list is
    `he she it they him her them his its their` -- so a memory that says "her"
    contributes no entity at all, which is exactly the sort this game is now
    full of. We know who was involved: binding resolved them. Two kinds are
    written, because they answer different questions -- the key, which the
    existing fuzzy recall path matches against, and the dbref, which is exact
    and survives both a rename and the object's deletion.
    """
    def _write(memory):
        memory_id = memory.remember(
            text, source=kind, importance=importance,
            metadata=dict(metadata or {}) or None)
        if memory_id and about:
            _annotate(memory_id, about)
        return memory_id

    return _with_memory(bank, session, _write)


def _annotate(memory_id, about):
    """File what a memory was about, so a cue can find it by name or by id."""
    from mnemosyne.core.annotations import AnnotationStore

    store = AnnotationStore()
    names = sorted({str(name) for name, _ref in about if name})
    refs = sorted({str(ref) for _name, ref in about if ref})
    if names:
        store.add_many(memory_id=memory_id, kind="mentions", values=names,
                       source="aimud", confidence=1.0)
    if refs:
        store.add_many(memory_id=memory_id, kind="dbref", values=refs,
                       source="aimud", confidence=1.0)


def _recall_sync(bank, session, query, top_k):
    """
    Retrieve memories most relevant to `query`, best match first.

    A character sees their own session and anything the world recorded
    globally, and nothing belonging to anybody else -- which is one clause
    rather than one file, and is why `_configure_backend` pins the toggle that
    would remove it.
    """
    results = _with_memory(
        bank, session, lambda memory: memory.recall(query, top_k=top_k)
    ) or []
    return [r["content"] for r in results if r.get("content")]
