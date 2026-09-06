"""
Per-character memory, backed by mnemosyne.

Every character -- player or NPC -- owns a mnemosyne bank keyed by its dbref.
Where they have been, what they have witnessed and what they have done is
written there as it happens, and pulled back out by relevance when they need
it.  That is what keeps an NPC's prompt small: instead of replaying the last
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

from twisted.internet import threads

from evennia.utils import logger

_backend = None
_state = "unknown"          # unknown | ready | missing

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
            _set_data_dir()
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


def warm_up():
    """
    Load mnemosyne in the background at server start.

    Without this the first remembered event pays for the import, and it would
    pay for it wherever that happened to be.
    """
    threads.deferToThread(_with_backend, lambda _backend: None).addErrback(_swallow)


def _set_data_dir():
    """
    Keep memories inside the game directory.

    mnemosyne otherwise stores them under the OS user's application data,
    which would leave a game's memories behind when the game is copied,
    backed up or moved.  Must be set before mnemosyne is first imported.
    """
    import os

    if os.environ.get("MNEMOSYNE_DATA_DIR"):
        return  # an explicit setting wins
    from django.conf import settings

    os.environ["MNEMOSYNE_DATA_DIR"] = os.path.join(
        settings.GAME_DIR, "server", "memory"
    )


def available():
    """
    True unless we already know mnemosyne is unusable.

    Deliberately does not trigger the import: this is called from command
    code on the reactor thread, and loading there is exactly what must not
    happen. Before the first load it answers optimistically and the worker
    thread finds out for certain.
    """
    return _state != "missing"


def bank_for(character):
    """
    The bank name owning this character's memories.

    Keyed by dbref rather than name: characters get renamed, and a renamed
    character should keep its past.
    """
    return f"aimud-char-{character.id}"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def remember(character, text, kind="event", importance=0.5):
    """
    Record something into a character's memory. Fire-and-forget.

    kind is a coarse label ("moved", "said", "witnessed", "did") kept as the
    memory's source so recall can be biased later if we want it.
    importance is 0..1; the things a character did themselves matter more to
    them than things they merely saw.
    """
    if not text or not available():
        return
    bank = bank_for(character)

    def _write():
        _remember_sync(bank, text, kind, importance)

    threads.deferToThread(_write).addErrback(_swallow)


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
    if event_type == "emote":
        if text.startswith(actor_name):
            return text
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


def recall_sync(bank, query, top_k=6):
    """
    Fetch relevant memories as a list of strings, best match first.

    MUST be called from inside a thread -- never the reactor.  Callers already
    running in a deferred fetch (the NPC dialogue call, the remember command)
    should call this directly there rather than paying for a second hop.
    """
    if not query or not available():
        return []

    found = []
    for variant in _query_variants(query):
        try:
            hits = _recall_sync(bank, variant, top_k)
        except Exception as exc:
            logger.log_info(f"memory recall failed: {exc}")
            return found
        for hit in hits:
            if hit not in found:
                found.append(hit)
        if len(found) >= top_k:
            break
    return found[:top_k]


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

def _remember_sync(bank, text, kind, importance):
    """Store one memory. Runs in a thread; mnemosyne keeps its own SQLite."""
    _with_backend(
        lambda backend: backend.remember(
            text, bank=bank, source=kind, importance=importance
        )
    )


def _recall_sync(bank, query, top_k):
    """
    Retrieve memories most relevant to `query`, best match first.

    Each bank is a separate database file, so a character can only ever recall
    what they themselves experienced.
    """
    results = _with_backend(
        lambda backend: backend.recall(query, top_k=top_k, bank=bank)
    ) or []
    return [r["content"] for r in results if r.get("content")]
