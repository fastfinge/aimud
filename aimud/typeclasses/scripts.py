"""
Scripts

Scripts are powerful jacks-of-all-trades. They have no in-game
existence and can be used to represent persistent game systems in some
circumstances. Scripts can also have a time component that allows them
to "fire" regularly or a limited number of times.

There is generally no "tree" of Scripts inheriting from each other.
Rather, each script tends to inherit from the base Script class and
just overloads its hooks to have it perform its function.

"""

import random

from evennia.scripts.scripts import DefaultScript


class Script(DefaultScript):
    """
    This is the base TypeClass for all Scripts. Scripts describe
    all entities/systems without a physical existence in the game world
    that require database storage (like an economic system or
    combat tracker). They
    can also have a timer/ticker component.

    A script type is customized by redefining some or all of its hook
    methods and variables.

    * available properties (check docs for full listing, this could be
      outdated).

     key (string) - name of object
     name (string)- same as key
     aliases (list of strings) - aliases to the object. Will be saved
              to database as AliasDB entries but returned as strings.
     dbref (int, read-only) - unique #id-number. Also "id" can be used.
     date_created (string) - time stamp of object creation
     permissions (list of strings) - list of permission strings

     desc (string)      - optional description of script, shown in listings
     obj (Object)       - optional object that this script is connected to
                          and acts on (set automatically by obj.scripts.add())
     interval (int)     - how often script should run, in seconds. <0 turns
                          off ticker
     start_delay (bool) - if the script should start repeating right away or
                          wait self.interval seconds
     repeats (int)      - how many times the script should repeat before
                          stopping. 0 means infinite repeats
     persistent (bool)  - if script should survive a server shutdown or not
     is_active (bool)   - if script is currently running

    * Handlers

     locks - lock-handler: use locks.add() to add new lock strings
     db - attribute-handler: store/retrieve database attributes on this
                        self.db.myattr=val, val=self.db.myattr
     ndb - non-persistent attribute handler: same as db but does not
                        create a database entry when storing data

    * Helper methods

     create(key, **kwargs)
     start() - start script (this usually happens automatically at creation
               and obj.script.add() etc)
     stop()  - stop script, and delete it
     pause() - put the script on hold, until unpause() is called. If script
               is persistent, the pause state will survive a shutdown.
     unpause() - restart a previously paused script. The script will continue
                 from the paused timer (but at_start() will be called).
     time_until_next_repeat() - if a timed script (interval>0), returns time
                 until next tick

    * Hook methods (should also include self as the first argument):

     at_script_creation() - called only once, when an object of this
                            class is first created.
     is_valid() - is called to check if the script is valid to be running
                  at the current time. If is_valid() returns False, the running
                  script is stopped and removed from the game. You can use this
                  to check state changes (i.e. an script tracking some combat
                  stats at regular intervals is only valid to run while there is
                  actual combat going on).
      at_start() - Called every time the script is started, which for persistent
                  scripts is at least once every server start. Note that this is
                  unaffected by self.delay_start, which only delays the first
                  call to at_repeat().
      at_repeat() - Called every self.interval seconds. It will be called
                  immediately upon launch unless self.delay_start is True, which
                  will delay the first call of this method by self.interval
                  seconds. If self.interval==0, this method will never
                  be called.
      at_pause()
      at_stop() - Called as the script object is stopped and is about to be
                  removed from the game, e.g. because is_valid() returned False.
      at_script_delete()
      at_server_reload() - Called when server reloads. Can be used to
                  save temporary variables you want should survive a reload.
      at_server_shutdown() - called at a full server shutdown.
      at_server_start()

    """

    pass


class NPCIdleScript(DefaultScript):
    """
    Attached to each NPC at creation. Fires every second and, when at least
    one player is in the room, increments the NPC's idle probability by 1%.
    When the probability roll succeeds the NPC takes a spontaneous action and
    the probability resets to 0.

    The probability also resets to 0 whenever the NPC acts for any reason
    (reaction to dialogue/emotes/actions or another idle trigger).
    Probability does not increase and no action is taken while no player is
    present, or while the NPC is already processing a reaction.
    """

    # These must be assigned in at_script_creation(), not as class attributes:
    # `interval` and friends are properties backed by db fields, and a plain
    # class attribute shadows the property so the db field keeps its default
    # (interval -1 = never ticks).
    def at_script_creation(self):
        self.key = "npc_idle"
        self.interval = 1
        self.persistent = True
        self.repeats = 0          # run forever
        self.start_delay = True   # wait one full second before the first tick

    def at_repeat(self):
        npc = self.obj
        if not npc or not npc.pk:
            self.stop()
            return

        # Skip the tick while a reaction is already in flight.
        if npc.ndb.reacting:
            return

        room = npc.location
        if not room:
            return

        # Only tick while a logged-in player is present.
        has_player = any(
            getattr(obj, "account", None) and obj.account.sessions.count() > 0
            for obj in room.contents
        )
        if not has_player:
            return

        # Increment probability (capped at 100 so it doesn't spiral past certainty).
        prob = min((npc.ndb.idle_probability or 0) + 1, 100)
        npc.ndb.idle_probability = prob

        # Roll — random() in [0, 1), so random() * 100 in [0, 100).
        # At prob == 100 this always fires; at prob == 1 it fires 1% of the time.
        if random.random() * 100 < prob:
            npc.ndb.idle_probability = 0
            npc.trigger_idle_action()
