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
    if not world_has_active_player(room.db.world_root):
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
