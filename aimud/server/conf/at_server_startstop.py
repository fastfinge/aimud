"""
Server startstop hooks

This module contains functions called by Evennia at various
points during its startup, reload and shutdown sequence. It
allows for customizing the server operation as desired.

This module must contain at least these global functions:

at_server_init()
at_server_start()
at_server_stop()
at_server_reload_start()
at_server_reload_stop()
at_server_cold_start()
at_server_cold_stop()

"""


def at_server_init():
    """
    This is called first as the server is starting up, regardless of how.
    """
    pass


def at_server_start():
    """
    This is called every time the server starts up, regardless of
    how it was shut down.
    """
    _start_npc_idle_scripts()
    _place_unmapped_worlds()
    _ensure_quest_deadline_script()


def _ensure_quest_deadline_script():
    """
    Make sure the one global quest-deadline clock is running.

    Global rather than per-character: there is nothing character-specific
    about noticing that a minute has passed.
    """
    from evennia import ScriptDB, create_script
    from evennia.utils import logger

    existing = ScriptDB.objects.filter(db_key="quest_deadlines")
    running = [s for s in existing if s.db_is_active and s.interval > 0]
    if running:
        return
    for stale in existing:
        stale.stop()
        stale.delete()
    create_script("typeclasses.scripts.QuestDeadlineScript")
    logger.log_info("Started the quest deadline clock.")


def _place_unmapped_worlds():
    """
    Give coordinates to worlds generated before the coordinate index existed.

    Runs once per world -- a root that already has an index is skipped -- so
    this costs nothing on later starts.
    """
    from evennia.objects.models import ObjectDB
    from evennia.utils import logger

    roots = [
        o for o in ObjectDB.objects.all()
        if o.db_destination is None and o.db.is_world_root and not o.db.room_coords
    ]
    if not roots:
        return

    from world import coord_backfill
    from world import coords

    placed = collided = 0
    for root in roots:
        for room, coord, clash in coord_backfill._walk(root):
            if clash is not None:
                collided += 1
                continue
            coords.place(root, room, coord)
            placed += 1
    logger.log_info(
        f"Mapped {placed} room(s) across {len(roots)} world(s); "
        f"{collided} left unplaced where the old layout overlapped itself."
    )


def _start_npc_idle_scripts():
    """
    Make sure every NPC has a running idle script.

    Timers do not restart by themselves unless they were paused by a reload,
    so an NPC whose script is missing or stopped would otherwise never act
    again on its own.
    """
    from evennia.utils import logger
    from typeclasses.npcs import NPC

    repaired = 0
    for npc in NPC.objects.all_family():
        scripts = npc.scripts.get("npc_idle")
        if not scripts or any(not s.db_is_active or s.interval <= 0 for s in scripts):
            npc.ensure_idle_script()
            repaired += 1
    if repaired:
        logger.log_info(f"Started idle scripts for {repaired} NPC(s).")


def at_server_stop():
    """
    This is called just before the server is shut down, regardless
    of it is for a reload, reset or shutdown.
    """
    pass


def at_server_reload_start():
    """
    This is called only when server starts back up after a reload.
    """
    pass


def at_server_reload_stop():
    """
    This is called only time the server stops before a reload.
    """
    pass


def at_server_cold_start():
    """
    This is called only when the server starts "cold", i.e. after a
    shutdown or a reset.
    """
    pass


def at_server_cold_stop():
    """
    This is called only when the server goes down due to a shutdown or
    reset.
    """
    pass
