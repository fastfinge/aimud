"""
NPC typeclass.

NPCs witness events in their room (dialogue, emotes, actions, gifts) and react
via the dialogue model using OpenRouter tool-calling. Reactions are async; the
tool calls they return are executed in the main thread.

NPC-to-NPC awareness is implemented with a chain-depth cap: an NPC can react to
another NPC's action, but the resulting reaction cannot trigger yet another NPC
reaction (depth > MAX_NPC_CHAIN is silently dropped). This prevents runaway
conversation loops while still allowing natural cross-NPC interaction.
NPCs only react to each other when at least one player is in the room.
"""

from evennia.objects.objects import DefaultObject

from .objects import ObjectParent

MAX_HISTORY = 30    # events older than this are dropped
MAX_NPC_CHAIN = 1   # how many NPC→NPC hops are allowed per player event


class NPC(ObjectParent, DefaultObject):
    """
    An AI-driven non-player character.

    Key db attributes:
      db.desc              — physical description
      db.world_description — cached world theme
      db.is_npc            — True (used as a quick type check)
      db.action_history    — list of {"type", "actor", "text"} event dicts
    """

    def at_object_creation(self):
        super().at_object_creation()
        self.db.is_npc = True
        self.db.action_history = []
        self.ensure_idle_script()

    def ensure_idle_script(self):
        """
        Attach the idle script if missing and make sure its timer is running.

        Called at creation and again for every NPC at server start, so an NPC
        that predates the script — or whose timer was left stopped — starts
        acting again rather than staying inert for good.
        """
        from typeclasses.scripts import NPCIdleScript

        existing = self.scripts.get("npc_idle")
        if not existing:
            self.scripts.add(NPCIdleScript)
            return
        for script in existing:
            if not script.db_is_active or script.interval <= 0:
                script.start(interval=1, start_delay=True, repeats=0)

    # ------------------------------------------------------------------ #
    # Public API — called by room event hooks, notify_npcs(), and the script
    # ------------------------------------------------------------------ #

    def witness(self, event_type, actor_name, text, _depth=0):
        """
        Record an event and (if not already reacting and within chain depth)
        trigger an AI reaction.

        event_type : "say" | "action" | "emote"
        actor_name : display name of the actor
        text       : what was said / what happened
        _depth     : NPC-to-NPC hop count; events with _depth > MAX_NPC_CHAIN
                     are recorded in history but do not trigger a new reaction.
        """
        self._add_to_history(event_type, actor_name, text)
        if not self.ndb.reacting and _depth <= MAX_NPC_CHAIN:
            self._trigger_reaction(_depth)

    # ------------------------------------------------------------------ #
    def trigger_idle_action(self):
        """Called by NPCIdleScript when the probability roll succeeds."""
        if self.ndb.reacting:
            return
        room = self.location
        if not room:
            return
        account = self._find_account(room)
        if not account:
            return
        self.ndb.reacting = True
        from world.npc_gen import generate_npc_idle
        generate_npc_idle(
            account=account,
            npc=self,
            room=room,
            on_success=self._execute_tool_calls,
            on_error=self._on_react_error,
        )

    # ------------------------------------------------------------------ #
    # Evennia hooks
    # ------------------------------------------------------------------ #

    def at_post_move(self, source_location, move_type="move", **kwargs):
        """Walking into a room where a player is counts as coming into company."""
        super().at_post_move(source_location, move_type=move_type, **kwargs)
        from world.activity import active_players_in, note_player_nearby

        if active_players_in(self.location):
            note_player_nearby(self)

    def at_object_receive(self, moved_obj, source_location, move_type="move", **kwargs):
        """React when a player gives this NPC an object."""
        super().at_object_receive(moved_obj, source_location,
                                  move_type=move_type, **kwargs)
        # Only react to items given by characters (not picked up by self from room)
        if source_location and hasattr(source_location, "account"):
            giver_name = source_location.get_display_name(self)
            item_name = moved_obj.get_display_name(self)
            self.witness("action", giver_name,
                         f"gave {item_name} to {self.key}", _depth=0)

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _add_to_history(self, event_type, actor_name, text):
        """
        Record an event this NPC perceived or performed.

        action_history is the NPC's working memory: a short tail sent verbatim
        so the immediate exchange stays coherent.  The same event also goes to
        the NPC's memory bank, which has no length limit and is what lets them
        recall something from an hour ago that matters again now.
        """
        history = self.db.action_history or []
        history.append({"type": event_type, "actor": actor_name, "text": text})
        if len(history) > MAX_HISTORY:
            history = history[-MAX_HISTORY:]
        self.db.action_history = history

        from world.memory import describe_event, remember

        mine = actor_name == self.key
        remember(
            self,
            describe_event(event_type, actor_name, text),
            kind="did" if mine else "witnessed",
            importance=0.6 if mine else 0.4,
        )

    def _trigger_reaction(self, _depth=0):
        room = self.location
        if not room:
            return
        from world.activity import npc_may_act

        if not npc_may_act(self):
            return
        account = self._find_account(room)
        if not account:
            return
        self.ndb.reacting = True
        from world.npc_gen import generate_npc_reaction
        generate_npc_reaction(
            account=account,
            npc=self,
            room=room,
            on_success=lambda calls: self._execute_tool_calls(calls, _depth),
            on_error=self._on_react_error,
        )

    def _on_react_error(self, _err):
        self.ndb.reacting = False

    def _find_account(self, room):
        """Return an account with an API key — prefer players currently in the room."""
        for obj in room.contents:
            account = getattr(obj, "account", None)
            if account and account.db.openrouter_api_key:
                return account
        world_root = room.db.world_root
        if world_root:
            return world_root.db.world_creator
        return None

    def _execute_tool_calls(self, tool_calls, _depth=0):
        """Apply a list of {"name": ..., "args": ...} dicts. Runs in main thread."""
        self.ndb.reacting = False
        # Reset idle probability whenever the NPC actually does something.
        if tool_calls:
            self.ndb.idle_probability = 0
        room = self.location
        if not room:
            return
        for call in tool_calls:
            self._execute_one(call.get("name", ""), call.get("args", {}), room, _depth)

    def _notify_other_npcs(self, room, event_type, text, _depth):
        """
        Notify other NPCs in the room of this NPC's action.

        Respects MAX_NPC_CHAIN, and each recipient decides for itself whether
        it is currently allowed to act -- which is what lets two NPCs hold a
        conversation in a room the players have just left, while a world
        nobody is watching stays silent.
        """
        from world.activity import npc_may_act

        next_depth = _depth + 1
        if next_depth > MAX_NPC_CHAIN:
            return
        for obj in room.contents:
            if obj is not self and obj.db.is_npc and npc_may_act(obj):
                obj.witness(event_type, self.key, text, _depth=next_depth)

    def _offer_quest(self, args, room):
        """
        Ask a player present to do something, with terms attached.

        The offer sits in their quest list until they answer it, so an NPC
        cannot commit anyone to anything by talking at them.
        """
        from evennia.objects.objects import DefaultCharacter

        from world import quests

        wanted = str(args.get("player", "")).strip().lower()
        target = None
        for obj in room.contents:
            if not isinstance(obj, DefaultCharacter):
                continue
            if not wanted or wanted in obj.key.lower():
                target = obj
                break
        if target is None:
            return

        quest = quests.offer(
            self, target,
            title=args.get("title"),
            description=args.get("description"),
            conditions=args.get("goal"),
            reward=args.get("reward"),
            punishment=args.get("punishment"),
            time_limit=args.get("time_limit_seconds"),
        )
        if quest is None:
            return

        target.msg(
            f'{self.key} says, "|w{quest["description"]}|n"\n'
            f"|y{self.key} is asking something of you: |w{quest['title']}|y. "
            f"Type |wquests|y to see the terms.|n"
        )
        room.msg_contents(f"{self.key} asks {target.key} for a favour.",
                          exclude=[target])
        self._add_to_history("action", self.key,
                             f"asked {target.key} to {quest['title']}")

    def _attempt_verb(self, action, room, _depth=0):
        """
        Try a verb through the same pipeline a player's command uses.

        This is what lets an NPC actually light the lamp rather than say it
        did: identical parsing, preconditions and effects.  The narrower
        effect set reflects that nobody chose to let the NPC act -- it may
        change objects, but not rewrite the room or walk the player around.
        """
        from world.attempt import NPC_FORBIDDEN_EFFECTS, attempt

        account = self._find_account(room)
        if not account:
            return

        allowed = {
            "create_object", "destroy_object", "move_object",
            "modify_object", "set_state",
        } - NPC_FORBIDDEN_EFFECTS

        def deliver(actor_text, room_text=""):
            visible = room_text or actor_text
            if not visible:
                return
            room.msg_contents(f"{self.key}: {visible}")
            # The NPC's own record; _add_to_history also writes to its memory.
            self._add_to_history("action", self.key, visible)
            # Others present witness it too, through the depth-capped path so
            # one NPC acting cannot set off an endless chain of reactions.
            self._notify_other_npcs(room, "action", visible, _depth)
            from world.memory import record_room_event
            record_room_event(room, "action", self.key, visible, actor=self)

        # Fuzzy binding, because an NPC names things from memory in its own
        # words: "the blackboard" should find the chalkboard already on the
        # wall. It may still conjure a fixture nothing resembles, which is how
        # a described-but-unmodelled thing becomes real.
        attempt(self, action, account, deliver, allow_effects=allowed,
                fuzzy=True)

    def _execute_one(self, tool_name, args, room, _depth=0):
        from commands.look_take_cmds import _find_one

        if tool_name == "say":
            msg = str(args.get("message", "")).strip()
            if msg:
                room.msg_contents(f'{self.key} says, "|w{msg}|n"')
                self._add_to_history("say", self.key, msg)
                self._notify_other_npcs(room, "say", msg, _depth)

        elif tool_name == "emote":
            action = str(args.get("action", "")).strip()
            if action:
                room.msg_contents(f"{self.key} {action}")
                self._add_to_history("emote", self.key, action)
                self._notify_other_npcs(room, "emote", f"{self.key} {action}", _depth)

        elif tool_name == "offer_quest":
            self._offer_quest(args, room)

        elif tool_name == "attempt":
            action = str(args.get("action", "")).strip()
            if action:
                self._attempt_verb(action, room, _depth)

        elif tool_name == "move":
            direction = str(args.get("direction", "")).strip()
            if direction:
                exit_obj, _ = _find_one(self, direction, location=room)
                if exit_obj and getattr(exit_obj, "destination", None) is not None:
                    destination = exit_obj.destination
                    if self.move_to(destination, quiet=False):
                        from world.memory import remember

                        where = destination.db.room_title or destination.key
                        remember(self, f"I walked {direction} to {where}",
                                 kind="moved", importance=0.3)

        elif tool_name == "get":
            obj_name = str(args.get("object_name", "")).strip()
            if obj_name:
                obj, _ = _find_one(self, obj_name, location=room)
                if obj and obj is not self:
                    if obj.move_to(self, quiet=True):
                        room.msg_contents(
                            f"{self.key} picks up {obj.get_display_name(self)}."
                        )

        elif tool_name == "give":
            obj_name = str(args.get("object_name", "")).strip()
            recipient_name = str(args.get("recipient", "")).strip()
            if obj_name and recipient_name:
                obj, _ = _find_one(self, obj_name, location=self)
                recipient, _ = _find_one(self, recipient_name, location=room)
                if obj and recipient and recipient is not self:
                    if obj.move_to(recipient, quiet=True):
                        room.msg_contents(
                            f"{self.key} gives {obj.get_display_name(self)} "
                            f"to {recipient.get_display_name(self)}."
                        )

        elif tool_name == "create":
            from evennia import create_object
            from typeclasses.objects import Object
            name = str(args.get("name", "")).strip()
            description = str(args.get("description", "")).strip()
            takeable = bool(args.get("takeable", True))
            if name:
                obj = create_object(Object, key=name, location=room)
                obj.db.desc = description
                obj.db.ai_takeable = takeable
                obj.db.is_ai_item = True
                room.msg_contents(
                    f"{self.key} produces {obj.get_display_name(self)}."
                )

        elif tool_name == "destroy":
            # Routed through the effect layer so the same guards apply as to a
            # player's verb: exits and player characters are never destroyed.
            obj_name = str(args.get("object_name", "")).strip()
            if obj_name:
                from world.effects import apply as apply_effects

                said = apply_effects(
                    self, room, [{"type": "destroy_object", "name": obj_name}],
                    world_root=room.db.world_root,
                )
                for line in said:
                    room.msg_contents(f"{self.key} destroys something. {line}")

        elif tool_name == "modify":
            obj_name = str(args.get("object_name", "")).strip()
            if obj_name:
                from world.effects import apply as apply_effects

                apply_effects(
                    self, room,
                    [{
                        "type": "modify_object",
                        "name": obj_name,
                        "new_name": args.get("new_name"),
                        "new_description": args.get("new_description"),
                    }],
                    world_root=room.db.world_root,
                )
