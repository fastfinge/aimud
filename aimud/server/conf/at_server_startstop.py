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
    _collect_orphan_rows()
    _start_npc_idle_scripts()
    _place_unmapped_worlds()
    _ensure_quest_deadline_script()
    _ensure_memory_sleep_script()
    _claim_unowned_worlds()
    _normalise_world_modes()
    _warm_lexicon()

    from world.memory import consolidate, sweep_orphans, warm_up

    # Sweep first, before anything has opened a bank. A bank is a directory of
    # SQLite files, and an open file cannot be deleted on Windows -- so this is
    # the one moment in a server's life when every dead character's memories
    # are certain to come away cleanly.
    stranded = sweep_orphans()
    if stranded:
        from evennia.utils import logger

        logger.log_info(
            f"memory: {len(stranded)} bank(s) belong to nothing this game can "
            f"read -- a world that is gone, or the per-character naming that "
            f"came before one bank per world; clearing them up"
        )

    # Load the memory backend off the reactor now, rather than making the
    # first remembered event wait seconds for the embedding stack to import.
    warm_up()

    # Worth doing once a run as well as on the clock: a server restarted more
    # often than the sleep interval would otherwise never consolidate at all,
    # and unconsolidated memories are the ones that get deleted.
    consolidate()


def _warm_lexicon():
    """
    Read the dictionary in before anybody needs a word from it.

    Two reasons, and neither is about the second and a half it takes. The
    corpus builds its indices on first use, and does it without a lock: two
    players typing at once on the threadpool would build them twice, over each
    other. And the command that paid for the loading would be some player's
    first, which is the worst moment in the game to spend it.

    A world without a dictionary still runs -- `world.lexicon` answers
    neutrally and every caller is written for that answer -- so this reports
    what happened and never stands in the way of a server starting.
    """
    from world import lexicon

    if not lexicon.warm():
        from evennia.utils import logger

        logger.log_info(
            "lexicon: no WordNet corpus; word endings, kinds and senses will "
            "be guessed rather than looked up"
        )


def _claim_unowned_worlds():
    """
    Write the creator back-link onto worlds made before there was one.

    An account has always listed the worlds it made; a world has never said
    who made it, and that is the direction a room needs in order to find out
    whose key pays for what happens in it. One pass over accounts, and only
    worlds with no answer yet are touched, so this costs nothing on every
    subsequent boot. See world.sponsor.
    """
    from world.sponsor import backfill

    claimed = backfill()
    if claimed:
        from evennia.utils import logger

        logger.log_info(f"sponsor: claimed {claimed} world(s) for their makers")


def _normalise_world_modes():
    """
    Take every world out of `always`, because nobody is logged in yet.

    The mode is stored on the world and so outlives the session that asked
    for it. It is meant to: a reload should not interrupt somebody watching a
    world run. But a server coming up has nobody in it by definition, and a
    world left in always would start spending money before anyone connected.
    """
    from world.activity import normalise_unwatched

    changed = normalise_unwatched()
    if changed:
        from evennia.utils import logger

        logger.log_info(
            f"activity: {len(changed)} world(s) were left running always; "
            f"back to normal until somebody asks again"
        )

def _collect_orphan_rows():
    """
    Delete the tag and attribute rows left behind by deleted things.

    First, before anything else here has had a chance to make one: a tag is
    created and then attached, and a sweep that runs while something else is
    between those two steps would delete a row that is about to be used. See
    world.housekeeping.
    """
    from evennia.utils import logger
    from world.housekeeping import collect_orphans

    tags, attributes = collect_orphans()
    if tags or attributes:
        logger.log_info(
            f"housekeeping: cleared {tags} tag row(s) and {attributes} "
            f"attribute row(s) that nothing refers to"
        )


def _ensure_memory_sleep_script():
    """
    Make sure the one global consolidation clock is running.

    Without it, memories that are never consolidated are deleted once they
    pass mnemosyne's retention window. See MemorySleepScript.
    """
    from evennia import ScriptDB, create_script
    from evennia.utils import logger

    existing = ScriptDB.objects.filter(db_key="memory_sleep")
    running = [s for s in existing if s.db_is_active and s.interval > 0]
    if running:
        return
    for stale in existing:
        stale.stop()
        stale.delete()
    create_script("typeclasses.scripts.MemorySleepScript")
    logger.log_info("Started the memory consolidation clock.")


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
