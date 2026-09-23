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

import json
import re
import threading
from collections import namedtuple
from datetime import datetime

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
             metadata=None, addressed=()):
    """
    Record something into a character's memory. Fire-and-forget.

    kind is a coarse label ("moved", "said", "witnessed", "did") kept as the
    memory's source so recall can be biased later if we want it.
    importance is 0..1; the things a character did themselves matter more to
    them than things they merely saw.

    `about` is (name, dbref) for everything the memory concerns, and is the
    half of this that no extractor could supply: we know who was involved
    because binding resolved them. A third field is how sure that is -- 1.0
    for a bound role, less for a name `world.recognition` found in speech.
    `addressed` is the same shape, for whoever was spoken to. `metadata` rides
    along unread, so a recalled memory can be re-rendered with today's names
    rather than replayed as the sentence it was written as.

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
                           about=about, metadata=metadata, addressed=addressed)
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
        # Past tense and a comma, the way the narration's own "said" reads, so
        # a memory of speech and a memory of an action are one voice.
        return f'{actor_name} said, "{text}"'
    # Some callers hand over text that already opens with the actor's name --
    # a pose, or an action narrated as a whole sentence. Prefixing it again
    # gives "Aria Delacroix Aria Delacroix lights the candle."
    if actor_name and text.startswith(actor_name):
        return text
    if event_type == "emote":
        return f"{actor_name} {text}"
    return f"{actor_name}: {text}"


def record_room_event(room, event_type, actor_name, text, actor=None,
                      about=(), addressed=(), line=None, metadata=None):
    """
    Write an event to the memory of every player character in the room.

    NPCs record through their own history hook instead, so they are skipped
    here to avoid remembering the same moment twice.  The actor remembers
    doing it; everyone else remembers seeing it. `about` and `addressed` are
    as `remember` takes them, and every copy of the memory carries them.

    `line` is the memory already written -- an episode, in the past tense,
    from `episode_of` -- and `metadata` what lets it be rendered again later.
    Without a line the event is described from its type and text.
    """
    if not room or not available():
        return
    from evennia.objects.objects import DefaultCharacter

    line = line or describe_event(event_type, actor_name, text)
    extra = {name: list(value) for name, value in
             (("about", about), ("addressed", addressed)) if value}
    if metadata:
        extra["metadata"] = dict(metadata)
    for obj in room.contents:
        if not isinstance(obj, DefaultCharacter):
            continue
        if obj is actor:
            remember(obj, line, kind="did", importance=0.6, **extra)
        else:
            remember(obj, line, kind="witnessed", importance=0.4, **extra)


# ---------------------------------------------------------------------------
# Episodes: what happened, as it will be remembered
#
# See docs/tokens-and-phrases.md, phase 6. An episode is an event's narration
# rendered in the past tense for nobody -- names throughout, no pronouns, no
# "I" -- so it is the same sentence for whoever did it and whoever watched,
# and it stays true for ever because it happened. What an event changed is not
# in it: "the candle is now lit" is a state, and states can stop being true.
# They are written as triples instead, by `effects`, which close themselves
# when something else becomes true.
# ---------------------------------------------------------------------------

#: The shape a memory is written in. A recalled memory whose metadata carries
#: this is rendered again with the names things have now; anything else --
#: a world written before phase 6, a line with no event behind it -- is shown
#: as it was stored.
SHAPE = 2

#: The word a verb wants before its object when there is no narration to say
#: it: "looked at the lantern", not "looked the lantern".
_OBJECT_PREPOSITION = {"look": "at"}

#: The other roles, and the word that introduces each, for the same fallback.
_ROLE_WORDS = (("instrument", "with"), ("target", "to"),
               ("container", "in"), ("source", "from"))


def _plain_template(event):
    """A narration for an event that brought none: "{actor} $pconj(hug) {direct}."."""
    verb = str(event.verb or "").strip() or "act"
    template = "{actor} $pconj(" + verb + ")"
    roles = event.roles or {}
    if roles.get("direct") is not None:
        word = _OBJECT_PREPOSITION.get(verb)
        template += f" {word} {{direct}}" if word else " {direct}"
    for role, word in _ROLE_WORDS:
        if roles.get(role) is not None:
            template += f" {word} {{{role}}}"
    return template + "."


def episode_line(event):
    """
    (the sentence, the template it came from) for an event, in the past tense.

    The narration when there is one, repaired, without the effect lines that
    follow it -- and a plain one from the verb and its roles when there is not,
    which is every look and every mechanic. A contested action says how it
    went, because "attacked the guard" on its own reads as a victory.
    """
    from world import checks, events

    template = events.repair(event.room_template) or _plain_template(event)
    line = events.render(template, None, event, tense="past").strip()
    if event.contested:
        line = line.rstrip(".!") + (", and succeeded." if event.outcome in checks.GOOD
                                    else ", and failed.")
    return line, template


def episode_of(event):
    """
    (line, about, metadata) for an event: what to remember, who it concerned,
    and what lets it be rendered again with tomorrow's names.

    `about` is every participant at full confidence, because binding resolved
    them. `metadata` is the template, the verb, the outcome, and every
    participant by id -- the quotes too, so that what somebody said survives a
    re-rendering word for word.
    """
    line, template = episode_line(event)
    about = [(str(obj.key), f"#{obj.id}")
             for obj in event.participants() if getattr(obj, "id", None)]
    metadata = {
        "shape": SHAPE,
        "template": template,
        "verb": event.verb,
        "outcome": event.outcome,
        "contested": bool(event.contested),
        "actor": getattr(event.actor, "id", None),
        "roles": {role: obj.id for role, obj in (event.roles or {}).items()
                  if getattr(obj, "id", None)},
        "quotes": {str(key): str(value)
                   for key, value in (event.quotes or {}).items()},
    }
    return line, about, metadata


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
    """Relevant memories as strings, best match first. See `recall_rows_sync`."""
    return [row["content"]
            for row in recall_rows_sync(where, query, top_k, already_known)]


def recall_rows_sync(where, query, top_k=6, already_known=()):
    """
    Fetch relevant memories as rows, best match first.

    A row is {"id", "content", "timestamp", "metadata"}: the stored sentence,
    when it was written, and what lets `rerender` say it again with today's
    names. MUST be called from inside a thread -- never the reactor -- and
    whatever renders the rows must not be, since rendering reads the game's
    own database.

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

    found, seen = [], set()
    for variant in _query_variants(query):
        try:
            hits = _recall_sync(where.bank, where.session, variant, wanted)
        except Exception as exc:
            logger.log_info(f"memory recall failed: {exc}")
            return found[:top_k]
        for hit in hits:
            said = hit.get("content", "")
            if said in seen or said in skip:
                continue
            seen.add(said)
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


def recall_for_cues(where, cues, top_k=6, per_cue=2, already_known=(),
                    rows=False):
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

    `rows` answers with rows rather than sentences, for a caller that will
    render them -- see `format_recalled`.
    """
    if not available():
        return []

    skip = {line for line in already_known if line}
    per_cue_hits = []
    for cue in list(cues)[:MAX_CUES]:
        if not cue:
            continue
        hits = recall_rows_sync(where, cue, top_k=per_cue, already_known=skip)
        if hits:
            per_cue_hits.append(hits)

    found, seen = [], set()
    for rank in range(per_cue):
        for hits in per_cue_hits:
            if rank >= len(hits):
                continue
            said = hits[rank].get("content", "")
            if said not in seen:
                seen.add(said)
                found.append(hits[rank])
                if len(found) >= top_k:
                    return found if rows else [row["content"] for row in found]
    return found if rows else [row["content"] for row in found]


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


def _consolidate_sync(banks, force=False, payers=None, keep_going=None):
    """
    Sleep these banks. Returns {bank: result}. Must run in a thread.

    `payers` is {bank: (sponsor, model)}, resolved by the caller on the main
    thread because a sponsor reaches the database. Summarising goes through
    the game's own model (`world.summaries`), and the pair says whose key pays
    for the bank being slept -- named around each one rather than passed,
    because mnemosyne calls the summariser from inside itself. A bank with no
    payer is still slept: everything sleep does besides summarising, it does
    without a model.

    **One bank per turn of the lock, not one per pass.** `_with_backend` holds
    `_lock`, and every recall and every write in the game takes the same lock
    -- so holding it across the whole pass meant all memory in the game was
    serialised behind however long every bank took together. The lock is there
    for one SQLite connection, and a connection is only in use for the bank
    being slept; taking it per bank lets a player's own remembering interleave
    with the sweep instead of queueing behind all of it.

    `keep_going` is asked between banks and stops the pass when it answers
    False. The same shape `fact_gen.distil` already had: a long queue costs a
    player nothing, it simply gets shorter over several quiet spells instead
    of one. Nothing is lost by stopping -- a bank that was not reached is
    found again by the next pass, unchanged.
    """
    from world import summaries

    payers = payers or {}
    done = {}

    for bank in banks:
        if keep_going is not None and not keep_going():
            logger.log_info(
                f"memory: stopped sleeping after {len(done)} of {len(banks)} "
                f"bank(s); somebody is playing, and the rest keep")
            break

        sponsor, model = payers.get(bank) or (None, None)

        def _one(backend, bank=bank, sponsor=sponsor, model=model):
            instance = None
            try:
                # Each bank is its own SQLite file, so sleeping one says
                # nothing about the others: every character has to be slept in
                # its own right. sleep_all_sessions rather than sleep, because
                # a character whose last event predates the cutoff would
                # otherwise be skipped for having no "current" session.
                instance = backend.Mnemosyne(bank=bank)
                with summaries.paying_for(sponsor, model):
                    return instance.sleep_all_sessions(force=force)
            finally:
                if instance is not None:
                    _close_quietly(instance)

        try:
            outcome = _with_backend(_one)
        except Exception as exc:
            # One bad bank has never stopped the pass and still does not.
            logger.log_info(f"memory: could not sleep {bank!r}: {exc}")
            continue
        if outcome is not None:
            done[bank] = outcome

    return done


def consolidate(force=False, on_done=None, yield_to_players=True):
    """
    Async, fire-and-forget. Sleep every living character's memories.

    Safe to call often: a bank with nothing old enough to consolidate reports
    no_op and costs one query. Nothing is destroyed -- the originals stay
    recallable beside the summary sleep writes, and become permanent by having
    been consolidated at all.

    Banks whose character is gone are skipped rather than slept. There is
    nothing to be gained by summarising the memories of somebody who no longer
    exists, and opening one is what would stop the sweep deleting it.

    `yield_to_players` stops the pass as soon as somebody is at the keyboard,
    and is the default because the callers that want it are the ones nobody
    asked for: `MemorySleepScript` checks the game is quiet before it starts
    but the pass outlives that check, and the call at server start does not
    check at all -- it fires while a player is logging in, which is how a
    player came to wait four minutes for a room behind it.

    The exception is `upkeep`, where somebody has typed `sleep` and is waiting
    to be told how many banks were done: there, being interrupted by the
    player who asked would be absurd, so it passes False.
    """
    if _closing or not available():
        return

    stranded = set(orphaned_banks())
    banks = [name for name in _bank_names() if name not in stranded]

    # Who pays for each bank's summaries, worked out here because this is the
    # main thread and a sponsor reads the database. See `world.summaries`.
    from world import summaries

    payers = summaries.payers_for(banks)

    keep_going = None
    if yield_to_players:
        from world.activity import quiet_enough_for_heavy_work

        keep_going = quiet_enough_for_heavy_work

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

    threads.deferToThread(
        _consolidate_sync, banks, force, payers, keep_going
    ).addCallbacks(_finished, _swallow)


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
# Sleep now goes the same way, and did not for a long time -- which is what
# this note should have led to and did not. Summarising was still on the local
# model, and cost one live server 9.5 CPU-hours in an afternoon without
# finishing while a player waited four minutes for a room. It is routed
# through mnemosyne's host-backend hook rather than replaced, because the rest
# of what sleep does -- marking rows consolidated, exempting them from
# retention -- is bookkeeping only it can do. See `world.summaries`.
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

    Each summary is a row -- {"content", "timestamp", "span"} -- so that
    whoever asks can say when it happened: see `dated`.

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
            summaries = []
            for row in rows:
                if not row.get("content"):
                    continue
                try:
                    span = _span_sync(instance, row["id"]) if row.get("id") else ()
                except Exception:
                    span = ()
                summaries.append({"content": row["content"],
                                  "timestamp": row.get("timestamp") or "",
                                  "span": span})
            return summaries, through
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


# ---------------------------------------------------------------------------
# Triples: what was true, and when it stopped being
#
# A second table and a second question. A fact says what is the case; a triple
# says what was the case between two moments, which is the difference between
# "the sword is Jessica's" and being able to answer who it belonged to before
# she gave it away -- or before it was destroyed. `supersede` closes the open
# triple sharing a subject and a predicate, which is exactly the semantics
# ownership wants: a transfer ends the old owner without anybody saying so.
#
# **Bank-scoped, with no session at all.** The triples table has no session
# column, so what goes in here is world history rather than one character's
# belief, and prefixing subjects with a character id to fake the difference
# would be inventing a scoping mechanism inside a column. Kept in the bank's
# own directory so that deleting a world deletes its history with it, which is
# the same bargain `bank_for` makes for everything else.
#
# **Nothing reads these into `recall`.** They are queried structurally --
# subject, predicate, as of when -- because "what does Jessica own" is a
# structured question rather than a fuzzy one. A caller asks and puts the
# answer in a prompt deliberately; nothing here is automatic.
#
# See docs/pronouns-and-ownership.md 7.5.
# ---------------------------------------------------------------------------

def _triple_store(bank):
    """The triple store for one world's bank. Must run in a thread."""
    from pathlib import Path

    from mnemosyne.core.triples import TripleStore

    home = Path(_data_dir()) / "banks" / str(bank)
    home.mkdir(parents=True, exist_ok=True)
    return TripleStore(db_path=home / "triples.db")


def _with_triples(bank, action):
    """
    Run `action(store)` against one world's triples. MUST be in a thread.

    Under the same lock as everything else here, for the same reason: SQLite
    connections are not shared between threads, and a burst of writes that
    collide are writes that are silently lost.
    """
    if not bank:
        return None
    with _lock:
        store = None
        try:
            store = _triple_store(bank)
            return action(store)
        except Exception as exc:
            logger.log_info(f"memory: could not reach the triple store: {exc}")
            return None
        finally:
            # Its own connection and nothing else. Not `_close_quietly`, which
            # also drops the caches the ordinary memory path keeps -- a triple
            # written here must not cost the next remembered event a
            # reconnect, and a triple store holds one plain handle anyway.
            conn = getattr(store, "conn", None)
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


def note_triple(where, subject, predicate, object_, supersede=True):
    """
    Record that this became true. Fire-and-forget.

    `supersede` closes whatever was true of the same subject and predicate
    before it, which is right for anything single-valued -- an owner, a
    placement, an exclusive state -- and wrong for anything a subject may
    hold several of at once.
    """
    if _closing or not available() or not (subject and predicate):
        return

    def _write(store):
        return store.add(str(subject), str(predicate), str(object_),
                         source="engine", supersede=bool(supersede))

    threads.deferToThread(_with_triples, where.bank, _write).addErrback(_swallow)


def end_triples(where, subject, predicate, object_=None):
    """
    Record that this stopped being true, without anything replacing it.

    What destruction needs, and the reason a memory is never deleted because
    its subject is gone: the triple is closed rather than removed, so `as_of`
    still answers who the sword belonged to while there was a sword.
    """
    if _closing or not available() or not (subject and predicate):
        return

    def _write(store):
        return store.end(str(subject), str(predicate),
                         str(object_) if object_ else None)

    threads.deferToThread(_with_triples, where.bank, _write).addErrback(_swallow)


def note_whereabouts(obj, world_root=None):
    """
    Record where a thing is now, closing where it was. Fire-and-forget.

    Called for every story move of a thing -- taken, dropped, put on a table,
    handed over, sent somewhere by an effect -- from `ObjectParent.at_post_move`.
    The predicate is `located` and supersedes, so "where was the sword before
    Raldor took it" is an `as_of` question the triples can answer.
    """
    if obj is None:
        return
    if world_root is None:
        from world import tokens

        world_root = tokens.world_root_of(obj)
    where = Where(bank_for(world_root), "")
    if not where.bank:
        return
    note_triple(where, f"#{obj.id}", "located", _whereabouts(obj),
                supersede=True)


def note_destroyed(obj, world_root=None):
    """
    Record that a thing stopped existing. Fire-and-forget.

    Its location is closed rather than replaced -- nothing is where it went --
    and `is destroyed` is written beside whatever else was true of it, which is
    what somebody asking after a sword that is not there wants to learn. Called
    before the thing is deleted, while its world can still be found from where
    it is.
    """
    if obj is None:
        return
    if world_root is None:
        from world import tokens

        world_root = tokens.world_root_of(obj)
    where = Where(bank_for(world_root), "")
    if not where.bank:
        return
    end_triples(where, f"#{obj.id}", "located")
    note_triple(where, f"#{obj.id}", "is", "destroyed", supersede=False)


def _whereabouts(obj):
    """
    Where a thing is, as a triple's object: "carried_by #5", "in #1", "on #7".

    By dbref, as ownership's triples are, because a triple is a structured
    record queried by identity: two swords share a name, and a room renamed
    is still the room. Names belong in the facts and in the memories.
    """
    from evennia.objects.objects import DefaultRoom

    from world import relations
    from world.quests import is_person

    holder = getattr(obj, "location", None)
    if holder is None:
        return "nowhere"
    if is_person(holder):
        return f"carried_by #{holder.id}"
    if isinstance(holder, DefaultRoom):
        return f"in #{holder.id}"
    return f"{relations.preposition_of(obj)} #{holder.id}"


def triples_sync(where, subject=None, predicate=None, object_=None, as_of=None):
    """
    What was true, as of a moment or as of now. MUST run in a thread.

    Synchronous and said so in the name, because every caller of this is
    already inside one -- a prompt being built, a goal being tested -- and a
    query that opened SQLite on the reactor would stall the whole game for the
    length of it.
    """
    if not available():
        return []

    def _read(store):
        return store.query(subject=subject, predicate=predicate,
                           object=object_, as_of=as_of)

    return _with_triples(where.bank, _read) or []


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

    Called from `reset world` and `delete world`. This is the whole practical
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
# A bank is a world now, and `reset world` and `delete world` delete it outright
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
    Banks nothing can read any more. Main thread -- it reads the DB.

    Two sorts: a world that has been deleted, and anything under the old
    per-character naming, which is orphaned by definition because what is in
    it was written against a carving this game no longer uses.

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


def _data_dir():
    """Where memories are kept, as configured or as defaulted."""
    import os

    data_dir = os.environ.get("MNEMOSYNE_DATA_DIR")
    if not data_dir:
        from django.conf import settings

        data_dir = os.path.join(settings.GAME_DIR, "server", "memory")
    return data_dir


def _bank_names():
    """
    Every bank on disk, read straight off the directory. Main thread safe.

    Deliberately does not go through mnemosyne: this is called to decide what
    to delete, and it must not be the thing that imports the embedding stack
    onto the reactor.
    """
    from pathlib import Path

    banks = Path(_data_dir()) / "banks"
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
                f"memory: deleted {len(removed)} unreadable memory bank(s)"
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


#: Most things a present-state line speaks for.
MOST_NOW = 3


def format_recalled(rows, now=None, world_root=None):
    """
    Recalled rows as a prompt reads them: oldest first, each with its age,
    then what is true now of the things they name. Main thread only.

    Chosen by relevance and shown in order, because a character remembering
    three things wants to know which came first -- and aged, because nothing
    else in the prompt says whether "Raldor handed Jessica the sword" was a
    minute ago or a week. The present-state line is what lets an old memory
    sit beside the truth without contradicting it.

    Aged in `world_root`'s own time. A summary is aged by the memories it
    summarises, not by when sleep wrote it, and a distilled fact is not aged
    at all: it is simply still true.
    """
    if not rows:
        return "(nothing comes to mind)"
    ordered = sorted(rows, key=_when_it_happened)
    lines = []
    for row in ordered:
        said = rerender(row) or row.get("content", "")
        age = _age_of_row(row, now, world_root)
        lines.append(f"- {age}: {said}" if age else f"- {said}")
    state = present_state(rows)
    if state:
        lines.append(state)
    return "\n".join(lines)


def rerender(row):
    """
    A recalled episode said again with the names things have now, or "".

    "" when the row was not written as an episode, or when anybody in it no
    longer exists -- in which case the stored sentence is what is shown, since
    a memory is never retired because its subject is gone. Main thread only:
    it reads the game's database.
    """
    metadata = row.get("metadata") or {}
    if metadata.get("shape") != SHAPE or not metadata.get("template"):
        return ""
    from world import events

    actor = _object(metadata.get("actor"))
    if actor is None:
        return ""
    roles = {}
    for role, ref in (metadata.get("roles") or {}).items():
        obj = _object(ref)
        if obj is None:
            return ""
        roles[role] = obj
    event = events.Event(
        actor=actor, room=getattr(actor, "location", None),
        verb=metadata.get("verb", ""), roles=roles,
        outcome=metadata.get("outcome", "success"),
        contested=bool(metadata.get("contested")),
        room_template=metadata["template"],
        quotes=metadata.get("quotes") or {})
    return episode_line(event)[0]


def _object(ref):
    from evennia.objects.models import ObjectDB

    try:
        return ObjectDB.objects.filter(id=int(ref)).first()
    except (TypeError, ValueError):
        return None


def _when_it_happened(row):
    """What a row is ordered by: the newest thing a summary summarises."""
    span = row.get("span") or ()
    return str((span[-1] if span else None) or row.get("timestamp") or "")


def _age_of_row(row, now=None, world_root=None):
    """The age a recalled row is shown with, or "" for none."""
    if row.get("source") == FACT_SOURCE:
        return ""
    span = row.get("span") or ()
    if len(span) == 2 and span[0] and span[1]:
        older = age_of(span[0], now, world_root)
        newer = age_of(span[1], now, world_root)
        if older and newer and older != newer:
            return f"between {older} and {newer}"
        return newer or older
    return age_of(row.get("timestamp"), now, world_root)


def real_seconds(timestamp):
    """
    A timestamp as real seconds since the epoch, or None when it does not read.

    Two shapes reach here: mnemosyne's, an ISO string in the server's local
    time, and working memory's, the number itself.
    """
    if timestamp is None or timestamp == "":
        return None
    if isinstance(timestamp, (int, float)):
        return float(timestamp)
    try:
        return datetime.fromisoformat(str(timestamp)).timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def age_of(timestamp, now=None, world_root=None):
    """
    How long ago, in the words a person would use: "moments ago", "earlier
    today", "yesterday", "3 days ago", "2 weeks ago", "a year ago". "" for a
    timestamp that does not read.

    In the world's own time. The real seconds since, at the world's speed,
    counted back from the world's now, so "yesterday" falls on the world's
    midnight and a conversation ten real minutes old in a world whose day is
    an hour long is hours old, which is what it is there. `now` is the real
    moment to measure from, for a test; the world's clock is read as it was
    then. See docs/becoming-and-time.md 8.7.
    """
    then = real_seconds(timestamp)
    if then is None:
        return ""
    from world import clock

    if now is not None:
        with clock.pinned(now.timestamp()):
            return _age(then, world_root)
    return _age(then, world_root)


def _age(then, world_root):
    from world import clock

    world_now = clock.now(world_root)
    world_then = clock.at_real(world_root, then)
    seconds = max((world_now - world_then).total_seconds(), 0)
    if seconds < 600:
        return "moments ago"
    if seconds < 7200:
        return "a little while ago"
    days = (world_now.date() - world_then.date()).days
    if days <= 0:
        return "earlier today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 14:
        return "a week ago"
    if days < 30:
        return f"{days // 7} weeks ago"
    if days < 60:
        return "a month ago"
    if days < 365:
        return f"{days // 30} months ago"
    if days < 730:
        return "a year ago"
    return f"{days // 365} years ago"


def dated(row, world_root=None):
    """
    When a row happened, as dates that stay true: "on 14 June 1852", or "from
    14 June 1852 to 18 June 1852" for a summary. "" when it cannot be told.

    For distillation, whose facts are kept for good. "Last week" written into
    a fact is wrong a week later; a date is not.
    """
    from world import clock

    span = [real_seconds(stamp) for stamp in (row.get("span") or ())]
    span = [stamp for stamp in span if stamp is not None]
    if not span:
        stamp = real_seconds(row.get("timestamp"))
        span = [stamp] if stamp is not None else []
    if not span:
        return ""
    first = clock.date_words(clock.at_real(world_root, min(span)))
    last = clock.date_words(clock.at_real(world_root, max(span)))
    return f"on {last}" if first == last else f"from {first} to {last}"


def present_state(rows, limit=MOST_NOW):
    """
    "Now: the sword is Raldor's and carried by Raldor." for the things the
    recalled memories name, read from the world rather than from memory.
    Capped, and people are left out: what matters about a person is in the room
    or in the memories already. Main thread only.
    """
    from world import english, ownership
    from world.quests import is_person

    seen, parts = set(), []
    for row in rows or ():
        metadata = row.get("metadata") or {}
        for ref in (metadata.get("roles") or {}).values():
            if ref in seen or len(parts) >= limit:
                continue
            seen.add(ref)
            obj = _object(ref)
            if obj is None or is_person(obj):
                continue
            bits = []
            owner = ownership.owner_name(obj)
            if owner:
                bits.append(f"{owner}'s")
            where = getattr(obj, "location", None)
            if where is not None:
                if is_person(where):
                    bits.append(f"carried by {where.key}")
                else:
                    bits.append(f"in {where.db.room_title or where.key}")
            if bits:
                parts.append(f"{english.with_article(obj.key, obj, definite=True)}"
                             f" is {' and '.join(bits)}")
    return ("Now: " + "; ".join(parts) + ".") if parts else ""


# ---------------------------------------------------------------------------
# The mnemosyne boundary
#
# Everything above is game logic; only these two functions know what the
# library looks like, so a change there is contained here.
# ---------------------------------------------------------------------------

def _remember_sync(bank, session, text, kind, importance, about=(),
                   metadata=None, addressed=()):
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
        if memory_id and (about or addressed):
            _annotate(memory_id, about, addressed)
        return memory_id

    return _with_memory(bank, session, _write)


def _annotate(memory_id, about, addressed=()):
    """
    File what a memory was about, so a cue can find it by name or by id.

    Three kinds: `mentions` by name and `dbref` by id for everything it was
    about, and `addressed` by id for whoever was spoken to. Each is written at
    the confidence it arrived with, since `add_many` takes one confidence per
    call -- a bound role at 1.0 and a name heard in speech below it.
    """
    from mnemosyne.core.annotations import AnnotationStore

    store = AnnotationStore()
    concerned = list(_confident(about))
    spoken_to = list(_confident(addressed))
    for kind, rows in (
            ("mentions", [(name, sure) for name, _ref, sure in concerned]),
            ("dbref", [(ref, sure) for _name, ref, sure in concerned]),
            ("addressed", [(ref, sure) for _name, ref, sure in spoken_to])):
        by_confidence = {}
        for value, sure in rows:
            if value:
                by_confidence.setdefault(sure, set()).add(str(value))
        for sure, values in sorted(by_confidence.items()):
            store.add_many(memory_id=memory_id, kind=kind,
                           values=sorted(values), source="aimud",
                           confidence=sure)


def _confident(pairs):
    """(name, ref, confidence) from (name, ref) or (name, ref, confidence)."""
    for item in pairs or ():
        try:
            item = tuple(item)
        except TypeError:
            continue
        if len(item) < 2:
            continue
        try:
            sure = float(item[2]) if len(item) > 2 else 1.0
        except (TypeError, ValueError):
            sure = 1.0
        yield item[0], item[1], sure


def _recall_sync(bank, session, query, top_k):
    """
    Retrieve memories most relevant to `query`, best match first.

    A character sees their own session and anything the world recorded
    globally, and nothing belonging to anybody else -- which is one clause
    rather than one file, and is why `_configure_backend` pins the toggle that
    would remove it.
    """
    def _read(memory):
        found = []
        for result in memory.recall(query, top_k=top_k) or []:
            if not result.get("content"):
                continue
            row = {"id": result.get("id"), "content": result["content"],
                   "timestamp": result.get("timestamp") or "", "metadata": {}}
            # Recall answers without metadata; `get` has it, by id, and is a
            # plain read in the same connection.
            try:
                stored = memory.get(result["id"]) if result.get("id") else None
                raw = (stored or {}).get("metadata")
                row["metadata"] = (json.loads(raw) if isinstance(raw, str) and raw
                                   else dict(raw or {}))
                row["source"] = (stored or {}).get("source") or ""
                if (stored or {}).get("memory_store") == "episodic":
                    row["span"] = _span_sync(memory, result["id"])
            except Exception:
                pass
            found.append(row)
        return found

    return _with_memory(bank, session, _read) or []


def _span_sync(memory, memory_id):
    """
    (oldest, newest) timestamps of what an episodic summary summarises, or ().

    Sleep stamps a summary with when it ran, which is days after anything in
    it happened: it only condenses what is older than half of mnemosyne's
    working-memory lifetime. The rows it condensed keep their own stamps, and
    `summary_of` names them. Read with SQL because no public call answers it;
    kept here, at the boundary, with the other two that know the library.
    """
    cursor = memory.conn.cursor()
    cursor.execute("SELECT summary_of FROM episodic_memory WHERE id = ?",
                   (memory_id,))
    found = cursor.fetchone()
    ids = [part for part in str((found[0] if found else "") or "").split(",")
           if part]
    if not ids:
        return ()
    marks = ",".join("?" * len(ids))
    cursor.execute(f"SELECT MIN(timestamp), MAX(timestamp) FROM working_memory "
                   f"WHERE id IN ({marks})", ids)
    oldest, newest = cursor.fetchone() or (None, None)
    return (oldest, newest) if oldest and newest else ()


# ---------------------------------------------------------------------------
# Lookups (docs/generator-tool-loops.md §5)
# ---------------------------------------------------------------------------

def lookup_tools():
    """`recall`: a character searching its own memory, in its own words."""
    from world import llm
    from world import toolbox as tb

    def recalling(ctx, args, answer):
        query = str(args.get("query") or "").strip()
        if not query:
            return answer("Remember what? Give some words to search for.")
        # Which bank is a database question, so it is asked here, on the
        # reactor; searching it is slow, so that goes off it.
        where = where_for(ctx.actor, ctx.world_root)

        def found(rows):
            # Back on the main thread, where saying a memory again with
            # today's names may read the game's database: aged and said the
            # way the prompt says them, so a memory found by asking reads
            # like one that came to mind.
            if not rows:
                return answer(f"Nothing comes to mind about {query}.")
            answer(format_recalled(rows, world_root=ctx.world_root))

        def lost(failure):
            # The character says the same thing either way, and should: an NPC
            # mid-conversation cannot tell somebody the database is locked.
            # But the log can, and nothing else here would -- this goes through
            # `fetch` rather than `converse`, so there is no loop line to carry
            # the reason (see `llm._loop_measured`, which exists for exactly
            # the generators that swallow theirs). Without this, a bank that
            # will not open is indistinguishable from a character who simply
            # remembers nothing, for as long as it lasts.
            logger.log_info(f"memory: could not recall {query!r} for "
                            f"{getattr(ctx.actor, 'key', '?')}: "
                            f"{failure.getErrorMessage()}")
            answer("Nothing comes to mind.")

        llm.fetch(recall_rows_sync, where, query, 6,
                  on_success=found, on_error=lost)

    return [tb.Tool(
        "recall",
        "Search your own memory for something older than what is in front of "
        "you: a person, a place, a promise.",
        tb.params({"query": {"type": "string",
                             "description": "What to remember, in a few "
                                            "words"}}, ["query"]),
        recalling, doing="remembering", looks=True,
        available=lambda ctx: ctx.actor is not None and available())]
