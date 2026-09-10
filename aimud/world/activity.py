"""
When NPCs are allowed to act.

NPCs cost money every time they think, so the question is not only "is this
interesting?" but "is anyone around to see it?". Three rules answer that, and
everything that wakes an NPC goes through them so they cannot disagree:

* A world with no active player in it is asleep. Nothing in it thinks at all.
  This is the brake that stops an unattended game quietly spending money.

* A player who has not typed for a while is scenery, not an audience. They
  stop counting as present, so a room with someone AFK in it goes as quiet as
  an empty one.

* An NPC that was recently with a player keeps acting for a while after they
  leave. This is what makes a world feel inhabited rather than motion-
  activated: the corridor a player just walked out of is still busy behind
  them, and NPCs there can move, talk to each other and change things.

Idle is measured with `cmd_last_visible`, the same field Evennia's own `who`
uses, so keepalives and other invisible traffic do not count as activity.

The second and third rules have a release: a world put into `always` mode
keeps thinking wherever its player is standing and however long since they
typed. The first does not, and cannot -- a world with nobody logged in goes
back to normal on its own, because that brake is the one stopping an
unattended game spending money forever.
"""

import time

#: How long an NPC goes on acting after it was last with an active player.
NEAR_PLAYER_WINDOW = 300

#: How long a player can go without typing before they stop counting as
#: present. Also how long a world goes without any command before it sleeps.
IDLE_LIMIT = 300

#: Minimum gap between writes of the "last near a player" stamp. The value is
#: also held in memory at full precision; this only decides how much of it
#: survives a reload, against how often we touch the database.
_STAMP_THROTTLE = 30


def _idle_seconds(character):
    """
    Seconds since this character's player last typed. None if unpuppeted.

    Several sessions may share one account, so the most recent one wins.
    """
    account = getattr(character, "account", None)
    if account is None:
        return None
    sessions = account.sessions.all()
    if not sessions:
        return None
    return time.time() - max(session.cmd_last_visible for session in sessions)


def is_active_player(obj):
    """True for a player character whose player is connected and not idle."""
    idle = _idle_seconds(obj)
    return idle is not None and idle < IDLE_LIMIT


def active_players_in(room):
    """The player characters in `room` who are actually paying attention."""
    from evennia.objects.objects import DefaultCharacter

    if room is None:
        return []
    return [
        obj for obj in room.contents
        if isinstance(obj, DefaultCharacter) and is_active_player(obj)
    ]


def world_has_active_player(world_root):
    """
    True when someone is awake somewhere in this world.

    Walks the connected sessions rather than the world's rooms: there are a
    handful of the former and possibly hundreds of the latter, and this is
    asked once per NPC per tick.
    """
    if world_root is None:
        return False
    from evennia.server.sessionhandler import SESSIONS

    now = time.time()
    for session in SESSIONS.get_sessions():
        if now - session.cmd_last_visible >= IDLE_LIMIT:
            continue
        puppet = getattr(session, "puppet", None)
        location = getattr(puppet, "location", None) if puppet else None
        if location is None:
            continue
        if location.db.world_root == world_root:
            return True
    return False


#: How long the game must have been quiet before heavy background work runs.
#:
#: Longer than IDLE_LIMIT on purpose. A player who has stopped typing for five
#: minutes has stopped being an audience, which is reason enough to let the
#: NPCs around them go still -- but it is not reason to start a job that will
#: hold the memory lock and run a model over every character in the game. That
#: waits until somebody has plainly put the game down.
QUIET_FOR_HEAVY_WORK = 900


def quiet_seconds():
    """
    How long since anybody last typed anything, across every session.

    Returns a very large number when nobody is connected at all, which is the
    quietest the game ever gets and should count as such.
    """
    from evennia.server.sessionhandler import SESSIONS

    sessions = SESSIONS.get_sessions()
    if not sessions:
        return float("inf")
    return time.time() - max(
        session.cmd_last_visible for session in sessions
    )


def quiet_enough_for_heavy_work(threshold=None):
    """
    True when background work may run without anybody noticing the pause.

    This is a single-player game: there is no moment that is convenient for
    everyone, only a moment that is convenient for the one person playing. So
    the question is simply whether they are still at the keyboard.
    """
    limit = QUIET_FOR_HEAVY_WORK if threshold is None else threshold
    return quiet_seconds() >= limit


def note_player_nearby(npc, now=None):
    """Record that an active player is with this NPC right now."""
    now = now or time.time()
    npc.ndb.last_near_player = now
    if now - (npc.db.last_near_player or 0) >= _STAMP_THROTTLE:
        npc.db.last_near_player = now


def recently_near_player(npc):
    """True if this NPC was with an active player inside the window."""
    last = max(npc.ndb.last_near_player or 0, npc.db.last_near_player or 0)
    return (time.time() - last) < NEAR_PLAYER_WINDOW


# ---------------------------------------------------------------------------
# What a world does about all of that
# ---------------------------------------------------------------------------

#: normal -- every rule above applies. A world thinks while it is watched.
#: always -- the world keeps thinking as long as anybody is logged in, wherever
#:           they are standing and however long since they last typed. Both
#:           brakes come off: the idle limit and the near-a-player window.
NORMAL = "normal"
ALWAYS = "always"
MODES = (NORMAL, ALWAYS)


def anybody_logged_in():
    """True while at least one session is connected and logged in."""
    from evennia.server.sessionhandler import SESSIONS

    return bool(SESSIONS.get_sessions())


def mode(world_root):
    """This world's mode. A world with no say in the matter runs normally."""
    if world_root is None:
        return NORMAL
    stored = str(world_root.db.world_mode or NORMAL).strip().lower()
    return stored if stored in MODES else NORMAL


def set_mode(world_root, wanted):
    """Put a world into a mode. Returns the mode it is in afterwards."""
    if world_root is None:
        return NORMAL
    wanted = str(wanted or "").strip().lower()
    if wanted not in MODES:
        return mode(world_root)
    world_root.db.world_mode = wanted
    return wanted


def normalise_unwatched():
    """
    Put every world back to normal, because nobody is logged in to watch.

    `always` is the one setting here that can spend money with nobody in the
    room, so it is not allowed to outlive the session that asked for it.

    The flag lives on the world and survives a restart, which is exactly why
    this is checked rather than left to a disconnect hook: a crash, a reload
    or a dropped connection would otherwise leave a world talking to itself
    all night. Called at server start, and again by the gate below the moment
    a world in always is asked to act with nobody there.

    Returns the worlds it changed.
    """
    from evennia.objects.models import ObjectDB

    changed = []
    for root in ObjectDB.objects.get_by_attribute(key="world_mode",
                                                  value=ALWAYS):
        root.db.world_mode = NORMAL
        changed.append(root)
    return changed


def always_on(world_root):
    """
    True when this world runs regardless of who is watching -- and somebody
    is still logged in to have asked it to.
    """
    if mode(world_root) != ALWAYS:
        return False
    if anybody_logged_in():
        return True
    normalise_unwatched()
    return False

def npc_may_act(npc):
    """
    The single question every NPC wake-up has to pass.

    Also refreshes the NPC's window as a side effect when a player is present,
    so simply being in the room with someone keeps an NPC live without any
    separate bookkeeping.
    """
    room = npc.location
    if room is None:
        return False

    world_root = room.db.world_root

    # Before either brake, and before the "always on" override: a state that
    # stops its holder acting stops it thinking too. `attempt` refuses the
    # action anyway, but an NPC that reaches that point has already spent a
    # dialogue call deciding what a corpse would like to do next.
    from world import verbs

    if verbs.blocked(npc, "prevents_acting", world_root):
        return False

    # A world set to always skips both brakes at once: how long since anybody
    # typed, and whether anybody is anywhere near this character. The window
    # is still stamped, so that turning the mode off afterwards leaves
    # everybody live for the usual few minutes and the world winds down
    # rather than stopping mid-sentence.
    if always_on(world_root):
        note_player_nearby(npc)
        return True

    if not world_has_active_player(world_root):
        return False
    if active_players_in(room):
        note_player_nearby(npc)
        return True
    return recently_near_player(npc)


def refresh_npcs_near(room):
    """
    Mark every NPC in `room` as having just been with a player.

    Called when a player arrives, and when an NPC arrives somewhere a player
    already is -- the two ways an NPC can come into company.
    """
    if room is None or not active_players_in(room):
        return
    now = time.time()
    for obj in room.contents:
        if obj.db.is_npc:
            note_player_nearby(obj, now)
