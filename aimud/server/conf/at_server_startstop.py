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

    # Load the memory backend off the reactor now, rather than making the
    # first remembered event wait seconds for the embedding stack to import.
    from world.memory import warm_up

    warm_up()


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


def _release_webserver_ports():
    """
    Stop listening on the internal webserver port before the reactor does.

    A reload does not wait for the old server to exit.  The portal launches
    the replacement the moment the AMP connection drops, and the old process
    then spends a further second or three finishing its shutdown -- during
    which it is still holding 127.0.0.1:4005.  The new server reaches for
    that port, cannot have it, and dies on the spot:

        CannotListenError: Couldn't listen on 127.0.0.1:4005 [WinError 10048]

    Nothing is wrong with the code when this happens; the two processes
    simply overlap.  On Linux the bind would be allowed anyway, because
    Twisted sets SO_REUSEADDR there and not on Windows, which is why this
    only ever bites here.

    Handing the port back at the start of our own shutdown, rather than at
    the end of Twisted's, is what closes the gap.  Twisted's own stopService
    is safe to run afterwards: it checks whether the port is still open.
    """
    import evennia
    from django.conf import settings
    from evennia.utils import logger

    service = getattr(evennia, "EVENNIA_SERVER_SERVICE", None)
    if service is None:
        return

    for _proxy_port, server_port in getattr(settings, "WEBSERVER_PORTS", []):
        try:
            child = service.getServiceNamed(f"EvenniaWebServer{server_port}")
        except KeyError:
            continue  # webserver disabled, or already gone
        if not child.running:
            continue  # already handed back, on the reload path
        try:
            child.stopService()
            logger.log_info(f"Released webserver port {server_port} early.")
        except Exception as err:
            logger.log_info(f"Could not release webserver port {server_port}: {err}")


def at_server_stop():
    """
    This is called just before the server is shut down, regardless
    of it is for a reload, reset or shutdown.
    """
    # Memory writes are serialised, so a busy world can leave a queue behind,
    # and Twisted waits for its thread pool while shutting down. Every second
    # of that is a second the replacement server is waiting on our ports.
    from world.memory import stop

    stop()
    _release_webserver_ports()


def at_server_reload_start():
    """
    This is called only when server starts back up after a reload.
    """
    pass


def at_server_reload_stop():
    """
    This is called only time the server stops before a reload.
    """
    # The earliest hook we get on the reload path, and the replacement server
    # is already starting by the time it runs -- so the port goes back here
    # rather than waiting for at_server_stop a few hundred milliseconds later.
    _release_webserver_ports()


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
