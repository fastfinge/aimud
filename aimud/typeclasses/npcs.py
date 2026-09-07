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

from evennia.contrib.rpg.traits import TraitHandler
from evennia.objects.objects import DefaultObject
from evennia.utils import lazy_property

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

    #: An NPC is a person, not a thing.  Without this they inherit
    #: DefaultObject's "object" content type, and a room lists them among the
    #: litter -- "You see: an Attendant Min-su and a stray pink flip-flop" --
    #: article and all, with no Characters line at all.  That is a very good
    #: way for a player to walk straight past somebody.
    _content_types = ("character",)

    #: Idle turns a goal may yield no plannable step before it is given up.
    #: A goal can name a room that was never built or an object that exists
    #: nowhere, and the planner has nothing to say about either.  Left alone
    #: the character wants it forever, and every idle turn falls through to a
    #: model call that cannot possibly fix it.
    GOAL_STALL_LIMIT = 10

    #: Everything _execute_one implements. A call outside this set means the
    #: model invented a tool, which is worth knowing about rather than
    #: dropping in silence.
    KNOWN_TOOLS = frozenset([
        "say", "emote", "move", "get", "give", "attempt", "offer_quest",
        "answer_quest", "set_goal", "check_traits", "create", "destroy",
        "modify",
    ])

    @lazy_property
    def traits(self):
        """What is measurably true of this character. See world.traits."""
        return TraitHandler(self)

    def at_object_creation(self):
        super().at_object_creation()
        self.db.is_npc = True
        self.db.action_history = []
        self.ensure_idle_script()

    def get_display_desc(self, looker, **kwargs):
        """
        How the character looks: their body, and then what they have on.

        The stored description is only what is permanently true of them, so
        this is where an NPC that changed its coat starts looking different.
        """
        from world import clothing

        base = super().get_display_desc(looker, **kwargs)
        return clothing.appearance(self, base, looker)

    def get_display_things(self, looker, **kwargs):
        """What the character is visibly carrying -- never what they have on."""
        from world import clothing

        return clothing.display_things(self, looker, **kwargs)

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

        # An errand finished or run out of time is noticed here, and that is
        # also what releases the goal the planner has been working at. It costs
        # no model call -- these are the same condition tests the planner runs.
        from world import quests, traits

        quests.review(self)
        quests.lapse_offers(self)
        # Anything that drifted since the last turn reaches this character's
        # working memory now, in time to be part of what it does next.
        traits.notice_changes(self)

        account = self._find_account(room)
        if not account:
            return

        # Working at a goal costs nothing: the world already knows what its
        # verbs do, and that is the same thing a planner needs. Only when
        # there is no useful step to take is the dialogue model asked what
        # this character would do with itself.
        if self._pursue_goal(room):
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
        from world.following import move_followers

        move_followers(self, source_location)
        from world.verbs import clear_on_move

        room = self.location
        clear_on_move(self, room.db.world_root if room else None)
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

    def _note_to_self(self, text):
        """
        Put something in working memory without remembering it for good.

        A refusal has to reach the next prompt -- otherwise the model asks for
        the same impossible thing every turn and is silently turned back every
        turn -- but it is not an event anybody witnessed, and writing it to the
        memory bank would fill that bank with the character's own thwarted
        intentions.  Repeats are dropped so one blocked exit cannot crowd the
        history out.
        """
        history = self.db.action_history or []
        if history:
            last = history[-1]
            if last.get("actor") == self.key and last.get("text") == text:
                return
        history.append({"type": "action", "actor": self.key, "text": text})
        if len(history) > MAX_HISTORY:
            history = history[-MAX_HISTORY:]
        self.db.action_history = history

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

    def _set_goal(self, want, room):
        """
        Take on something to work towards, said in the character's own words.

        Turned into testable conditions by a separate call, for the same
        reason quests are: a small dialogue model cannot produce typed
        conditions in the middle of speaking in character. Rare enough not to
        matter -- one call buys a purpose the planner then pursues for free.
        """
        from evennia.utils import logger

        if not want:
            return
        account = self._find_account(room)
        if not account:
            return

        def ready(conditions):
            from world import goals

            clean = goals.sanitise(conditions)
            if not clean:
                logger.log_info(
                    f"{self.key}: wanted {want!r}, but it made no testable goal"
                )
                return
            self.db.goal = clean
            self.db.goal_stalls = 0
            logger.log_info(f"{self.key} now wants: {goals.describe(clean, self)}")

        from world.quest_gen import formalise_goal

        formalise_goal(
            account, self, want,
            on_success=ready,
            on_error=lambda err: logger.log_info(
                f"{self.key}: could not turn {want!r} into a goal: {err}"
            ),
        )

    def _check_traits(self, who, room):
        """
        Size somebody up, and remember what was found.

        A tool here acts; it cannot hand an answer back to the model that
        called it. So what this finds goes into working memory instead, which
        is the same route a refusal takes -- the character has noticed
        something, and it is there in front of them on their next turn.
        """
        from world import traits

        target = self
        if who and who.lower() not in (self.key.lower(), "me", "myself"):
            from commands.look_take_cmds import _find_one

            target, _ = _find_one(self, who, location=room)
            if target is None or not traits.has_traits(target):
                self._note_to_self(f"there is no {who} here to take stock of")
                return

        described = traits.describe(target)
        name = "I" if target is self else target.get_display_name(self)
        if not described:
            self._note_to_self(f"there is nothing measurable about {name}")
            return
        self._note_to_self(
            f"taking stock of {name}: {described}" if target is not self
            else f"taking stock of myself: {described}"
        )

    def _offer_quest(self, args, room):
        """
        Ask a player present to do something, in this NPC's own words.

        The words are turned into a checkable quest by a separate call, so the
        dialogue model is never asked to produce a typed goal schema in the
        middle of speaking in character -- which it never once managed.
        """
        from evennia.utils import logger

        from world import quests

        # "person" is what the tool asks for now; "player" is what it used to
        # ask for, and the model still reaches for it.
        wanted = str(args.get("person") or args.get("player") or "").strip().lower()
        request = str(args.get("request", "")).strip()
        if not request:
            logger.log_info(f"{self.key}: quest offer with no request, dropped")
            return

        # Only people with a free slot. An errand pressed on somebody already
        # running one is worse than no errand at all: it cannot be taken, and
        # it is what made the world feel like a queue of requests.
        target = None
        for obj in quests.candidates(room, exclude=self):
            known = [obj.key.lower(), obj.get_display_name(self).lower()]
            if not wanted or any(wanted in name for name in known):
                target = obj
                break
        if target is None:
            logger.log_info(
                f"{self.key}: wanted to ask {wanted!r} for something, but "
                f"nobody here is free to take it on"
            )
            return

        account = self._find_account(room)
        if not account:
            return

        offer = str(args.get("offer", "")).strip()
        consequence = str(args.get("consequence", "")).strip()
        time_limit = args.get("time_limit_seconds")

        def ready(spec):
            from world import quests

            quest = quests.offer(
                self, target,
                title=spec["title"],
                description=request,
                conditions=spec["goal"],
                reward=spec["reward"],
                punishment=spec["punishment"],
                time_limit=time_limit,
            )
            if quest is None:
                logger.log_info(
                    f"{self.key}: quest {spec['title']!r} produced no testable "
                    f"goal from {spec['goal']!r}, dropped"
                )
                return

            if target.db.is_npc:
                # Asked out loud, so the room sees the arrangement being made.
                # The offer now sits in their quest list, and they answer it on
                # their own next turn.
                room.msg_contents(f'{self.key} says, "{request}"')
                target.witness("say", self.key, request)
            else:
                target.msg(f'{self.key} says, "|w{request}|n"')
                target.msg(
                    f"|y{self.key} is asking something of you: |w{quest['title']}|y. "
                    f"Type |wquests|y to see the terms, then |wquests accept|y "
                    f"or |wquests decline|y to answer.|n"
                )
                room.msg_contents(
                    f"{self.key} asks {target.get_display_name(self)} for a favour.",
                    exclude=[target])
            self._add_to_history("action", self.key,
                                 f"asked {target.get_display_name(self)} to {quest['title']}")

        def failed(err):
            logger.log_info(f"{self.key}: could not turn a request into a quest: {err}")

        from world.quest_gen import formalise

        formalise(account, self, target, request, offer, consequence,
                  on_success=ready, on_error=failed)

    def _answer_quest(self, args, room):
        """
        Say yes or no to what somebody has asked of this character.

        Accepting is what ties a quest to the planner: quests.accept makes the
        errand this character's goal, and the planner then works at it exactly
        as it works at a goal the character set itself.
        """
        from evennia.utils import logger

        from world import quests

        if quests.offered_to(self) is None:
            logger.log_info(f"{self.key}: answered a request nobody had made")
            return

        if bool(args.get("accept", True)):
            quest, _message = quests.accept(self)
            if quest is None:
                return
            said = f"{self.key} agrees to {quest['giver']}'s request: {quest['title']}."
        else:
            quest, _message = quests.decline(self)
            if quest is None:
                return
            said = f"{self.key} turns down {quest['giver']}'s request."

        room.msg_contents(said)
        self._add_to_history("action", self.key, said)

        from world.npc_gen import notify_npcs

        notify_npcs(room, "action", self.key, said, exclude=self, actor=self)

        # It may already be satisfied by what this character happens to carry.
        quests.review(self)

    def _walk(self, direction, room):
        """
        Leave by an exit. True if the character actually went somewhere.

        Goes through at_traverse rather than moving straight to the exit's
        destination: an exit that has never been used points at its own room
        until the far side is built, so moving to its destination walks a
        character into the room it is already standing in -- which is what
        produced "leaving X, heading for X" in the log.

        An unexplored exit is walked like any other, and builds the room
        behind it. It costs three model calls, but the room is only ever built
        once and a player will stand in it sooner or later -- whereas a world
        whose characters may only tread ground a player has already covered
        feels small, and pens them in.
        """
        from commands.look_take_cmds import _find_one
        from evennia.utils import logger

        exit_obj, _ = _find_one(self, direction, location=room)
        if exit_obj is None or getattr(exit_obj, "destination", None) is None:
            logger.log_info(f"{self.key}: no exit {direction!r} to take from {room.key}")
            self._note_to_self(f"there is no way {direction} from here")
            return False

        destination = exit_obj.destination
        unbuilt = bool(exit_obj.db.pending_generation)
        if not unbuilt and destination is room:
            # Pointing at its own room without being marked pending: there is
            # nothing on the other side and nothing on its way either.
            logger.log_info(f"{self.key}: {direction!r} from {room.key} goes nowhere")
            self._note_to_self(f"the way {direction} from here is not open")
            return False

        exit_obj.at_traverse(self, destination)

        if unbuilt:
            # Either the far side is being built with this character waiting on
            # it, or the world's one build is already under way somewhere else
            # and this turn is spent waiting for a go. Nothing further to
            # decide this turn in either case, so the idle model is not asked.
            if self not in (exit_obj.ndb.waiting_travelers or []):
                return True

            from world.memory import remember

            remember(self, f"I went {direction} to see what was there",
                     kind="moved", importance=0.3)
            return True

        if self.location is destination:
            from world.memory import remember

            where = destination.db.room_title or destination.key
            remember(self, f"I walked {direction} to {where}",
                     kind="moved", importance=0.3)
            return True
        return False

    def _pursue_goal(self, room):
        """
        Take one step towards this character's goal. True if something was done.

        One step at a time, checked afterwards: effects are model-written and
        sometimes describe more than they do, so a rule that fails to bring
        about what it promised is set aside rather than tried forever.
        """
        from world import goals
        from world.planner import check_outcome, plan_step

        world_root = room.db.world_root

        # A goal that has been reached is done with. Leaving it set would
        # leave the character permanently satisfied and unable to want
        # anything else, because the planner would keep finding nothing to do.
        goal = list(self.db.goal or [])
        if goal and goals.satisfied(goal, self, world_root):
            from evennia.utils import logger

            self._add_to_history("action", self.key,
                                 f"got what {self.key} wanted: "
                                 f"{goals.describe(goal, self, world_root)}")
            logger.log_info(f"{self.key} reached its goal; wanting nothing for now")
            self.db.goal = []
            self.db.goal_stalls = 0
            self.db.goal_from_quest = None
            return False

        action, rule_key, condition = plan_step(self, world_root)
        if not action:
            self._give_up_eventually(goal, world_root)
            return False
        self.db.goal_stalls = 0

        from world.worldgen import canonical_direction

        if canonical_direction(action):
            # The step is a way out; walking is not a verb attempt.
            return self._walk(action, room)

        self._attempt_verb(action, room)
        check_outcome(self, world_root, condition, rule_key)
        return True

    def _give_up_eventually(self, goal, world_root):
        """
        Count an idle turn the planner could make no move on, and eventually
        stop wanting the thing.

        Some goals cannot be worked towards at all: one that names a room
        nobody ever built, or an object that exists in no room in the world.
        The planner correctly finds no step, and the character then falls
        through to the dialogue model on every idle turn for the rest of its
        life -- a model call each time, spent on a want that no answer can
        satisfy.  After enough turns of that the goal is dropped, and the
        character is free to want something it can actually do.
        """
        if not goal:
            return
        stalls = (self.db.goal_stalls or 0) + 1
        self.db.goal_stalls = stalls
        if stalls < self.GOAL_STALL_LIMIT:
            return

        from evennia.utils import logger
        from world import goals

        logger.log_info(
            f"{self.key}: no way to make progress towards "
            f"{goals.describe(goal, self, world_root)} in {stalls} turns; "
            f"giving up on it"
        )

        # If somebody set this errand, they should not be left waiting on it.
        if self.db.goal_from_quest is not None:
            from world import quests

            quest, _message = quests.abandon(self, self.db.goal_from_quest)
            if quest is not None and self.location:
                self.location.msg_contents(
                    f"{self.key} gives up on {quest['giver']}'s errand: "
                    f"{quest['title']}.")

        self.db.goal = []
        self.db.goal_stalls = 0
        self.db.goal_from_quest = None

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
            # Only the third-person line is usable here. The actor line is
            # written to whoever acted ("You touch a match to the wick"), and
            # broadcasting that would tell the room it had done the thing.
            visible = room_text
            if not visible:
                return
            room.msg_contents(visible)
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

        if tool_name not in self.KNOWN_TOOLS:
            # Silently ignoring these is how a model quietly doing the wrong
            # thing stays invisible.
            from evennia.utils import logger

            logger.log_info(f"{self.key}: unknown tool call {tool_name!r} ignored")
            return

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

        elif tool_name == "set_goal":
            self._set_goal(str(args.get("want", "")).strip(), room)

        elif tool_name == "check_traits":
            self._check_traits(str(args.get("person", "")).strip(), room)

        elif tool_name == "offer_quest":
            self._offer_quest(args, room)

        elif tool_name == "answer_quest":
            self._answer_quest(args, room)

        elif tool_name == "attempt":
            action = str(args.get("action", "")).strip()
            if action:
                self._attempt_verb(action, room, _depth)

        elif tool_name == "move":
            direction = str(args.get("direction", "")).strip()
            if direction:
                self._walk(direction, room)

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
