"""
Quests: a goal, a reward, and someone who asked.

A quest is the goal layer with three things bolted on -- who offered it, what
happens when it is met, and what happens if it is not in time. Nothing here
plans anything: the player does the planning, and the system only has to
notice when they are done. That is why quests are cheap where NPC planning
would not be.

Rewards and punishments are ordinary verb effects, so they run through the
same guarded applier: a punishment cannot delete a player or an exit, however
sore the NPC who set it.
"""

import time

from evennia.utils import logger

from world import goals

#: Effects a quest may hand out or exact. Deliberately narrower than what a
#: verb can do: a quest is a transaction between two characters, not a licence
#: to rewrite the room it was agreed in.
QUEST_EFFECTS = frozenset([
    "create_object", "destroy_object", "move_object", "modify_object", "set_state",
])

#: Longest a quest may run, whatever an NPC asks for. An hour of real time is
#: already a long errand in a MUD.
MAX_TIME_LIMIT = 3600
MIN_TIME_LIMIT = 60

OFFERED = "offered"
ACTIVE = "active"
DONE = "done"
FAILED = "failed"
DECLINED = "declined"
ABANDONED = "abandoned"

#: How long an offer waits for an answer before it quietly lapses.
#:
#: Something has to, or one unanswered request holds the character's single
#: quest slot shut for good and nobody can ever ask them anything again. An
#: NPC either replies on its next turn or was never going to; a player may
#: reasonably be doing something else, walk away from the keyboard, or simply
#: want to think about it, so they are given far longer.
OFFER_LAPSES_AFTER = 180
OFFER_LAPSES_AFTER_PLAYER = 900


def is_person(obj):
    """
    True for anything that can be asked to do something.

    NPCs are not DefaultCharacter subclasses here, so the obvious isinstance
    test quietly excludes exactly the characters this module now exists to
    include.
    """
    from evennia.objects.objects import DefaultCharacter

    return bool(obj.db.is_npc) or isinstance(obj, DefaultCharacter)


def current(character):
    """The one quest this character has underway, or None."""
    for quest in _quests(character):
        if quest.get("status") == ACTIVE:
            return quest
    return None


def offered_to(character):
    """The one offer waiting on this character's answer, or None."""
    for quest in _quests(character):
        if quest.get("status") == OFFERED:
            return quest
    return None


def can_accept(character):
    """
    True when this character is free to be asked something.

    One errand at a time, and one offer outstanding at a time. Without this a
    character -- a player especially -- collects errands faster than anybody
    could run them, and the world starts to look like a queue of requests
    rather than a place.
    """
    return current(character) is None and offered_to(character) is None


def candidates(room, exclude=None):
    """Everyone in `room` who could take on a quest right now."""
    if room is None:
        return []
    return [obj for obj in room.contents
            if obj is not exclude and is_person(obj) and can_accept(obj)]


def _quests(character):
    return list(character.db.quests or [])


def _save(character, entries):
    character.db.quests = entries


def _next_id(character):
    return max((int(q.get("id", 0)) for q in _quests(character)), default=0) + 1


def visible(character):
    """Quests worth showing a player: offered and active, newest last."""
    return [q for q in _quests(character) if q.get("status") in (OFFERED, ACTIVE)]


def offer(npc, character, title, description, conditions,
          reward=None, punishment=None, time_limit=None):
    """
    Record an offer from `npc` to `character`. Returns the quest, or None.

    An offer whose goal survives sanitising to nothing is refused here rather
    than accepted and left impossible.
    """
    if not can_accept(character):
        logger.log_info(
            f"quest offer from {npc.key} to {character.key} discarded: "
            f"they already have one"
        )
        return None

    # No owner: this errand is the player's to do, and a delivery back to
    # the character who asked for it is the commonest shape an errand has.
    clean = goals.sanitise(conditions)
    if not clean:
        logger.log_info(f"quest offer from {npc.key} discarded: no testable goal")
        return None

    limit = None
    if time_limit:
        try:
            limit = max(MIN_TIME_LIMIT, min(MAX_TIME_LIMIT, int(time_limit)))
        except (TypeError, ValueError):
            limit = None

    # Which world this was agreed in, so it can be forgotten with that world.
    room = npc.location
    root = room.db.world_root if room else None

    quest = {
        "id": _next_id(character),
        "title": str(title or "An errand").strip(),
        "description": str(description or "").strip(),
        "giver": npc.key,
        "giver_id": npc.id,
        "world_root": root.id if root else None,
        "goal": clean,
        "reward": _clean_effects(reward),
        "punishment": _clean_effects(punishment),
        "time_limit": limit,
        "status": OFFERED,
        "offered_at": time.time(),
        "accepted_at": None,
    }
    entries = _quests(character)
    entries.append(quest)
    _save(character, entries)
    return quest


def forget_world(character, root_id, giver_ids=()):
    """
    Drop every quest that belonged to a world being deleted. Returns how many.

    A quest outlives its world unless something removes it.  The giver is
    gone, the objects its goal names are gone and the room it was agreed in
    is gone -- but the quest itself sits on the player, who is not deleted
    along with the world.  Left alone it shows in `quests` forever, can never
    be completed, and is re-tested on every deadline tick.

    Matched on the world first.  Quests recorded before they knew which world
    they came from are matched on who gave them instead, which is why the
    givers are collected before the world's NPCs are destroyed.
    """
    try:
        root_id = int(root_id)
    except (TypeError, ValueError):
        return 0
    givers = {g for g in giver_ids if g is not None}

    kept, dropped = [], 0
    for quest in _quests(character):
        theirs = quest.get("world_root")
        if theirs is None:
            belongs = quest.get("giver_id") in givers
        else:
            belongs = theirs == root_id
        if belongs:
            dropped += 1
        else:
            kept.append(quest)
    if dropped:
        _save(character, kept)
    return dropped


def _clean_effects(effects):
    """
    Keep only effect types a quest is allowed to apply.

    Duck-typed rather than isinstance-checked: stored attributes come back as
    Evennia _SaverDict, which is a MutableMapping and not a dict subclass.
    """
    clean = []
    for effect in effects or []:
        try:
            etype = effect.get("type")
        except AttributeError:
            continue
        if etype in QUEST_EFFECTS:
            clean.append(dict(effect))
    return clean


def _find(character, quest_id):
    for quest in _quests(character):
        if int(quest.get("id", 0)) == int(quest_id):
            return quest
    return None


def _update(character, quest_id, **changes):
    entries = _quests(character)
    for quest in entries:
        if int(quest.get("id", 0)) == int(quest_id):
            quest.update(changes)
            break
    _save(character, entries)


def accept(character, quest_id=None):
    """Take on an offered quest. Returns (quest, message)."""
    quest = _find(character, quest_id) if quest_id is not None else offered_to(character)
    if quest is None or quest.get("status") != OFFERED:
        return None, "There is no such offer."
    if current(character) is not None:
        return None, ("You already have something underway. Finish or "
                      "|wquests abandon|n it first.")
    quest_id = quest["id"]
    _update(character, quest_id, status=ACTIVE, accepted_at=time.time())
    quest = _find(character, quest_id)

    # For a character the planner drives, an accepted errand simply becomes
    # what they are working towards. That is the whole integration: a quest
    # goal and a character's own goal are already the same kind of thing.
    _adopt_goal(character, quest)

    deadline = ""
    if quest.get("time_limit"):
        deadline = f" You have {_short_time(quest['time_limit'])}."
    return quest, f"You accept: |w{quest['title']}|n.{deadline}"


def decline(character, quest_id=None):
    """Turn down an offered quest. Returns (quest, message)."""
    quest = _find(character, quest_id) if quest_id is not None else offered_to(character)
    if quest is None or quest.get("status") != OFFERED:
        return None, "There is no such offer."
    _update(character, quest["id"], status=DECLINED)
    return quest, f"You decline: {quest['title']}."


def abandon(character, quest_id=None):
    """
    Give up on the quest underway. Returns (quest, message).

    No punishment is exacted. A punishment is the price of letting a deadline
    run out with the giver still waiting; saying plainly that you are not
    going to do it is a different thing, and the giver at least knows where
    they stand.
    """
    quest = _find(character, quest_id) if quest_id is not None else current(character)
    if quest is None or quest.get("status") != ACTIVE:
        return None, "You have nothing underway to abandon."
    _update(character, quest["id"], status=ABANDONED)
    _release_goal(character, quest)
    # Counted with the failures. Saying plainly that you will not do it is
    # better manners than letting the clock run out, but the errand is still
    # one somebody asked for and did not get.
    _tally(character, FAILED, _world_root(character), quest["title"])
    return quest, f"You give up on: {quest['title']}."


def lapse_offers(character, older_than=OFFER_LAPSES_AFTER):
    """
    Quietly decline offers nobody ever answered. Returns how many.

    An unanswered offer holds the one slot shut, so a character who was asked
    something and never replied could never be asked anything again.
    """
    now = time.time()
    lapsed = 0
    for quest in _quests(character):
        if quest.get("status") != OFFERED:
            continue
        if now - (quest.get("offered_at") or now) >= older_than:
            _update(character, quest["id"], status=DECLINED)
            lapsed += 1
    return lapsed


def _adopt_goal(character, quest):
    """Make an accepted quest the goal the planner works at."""
    if not character.db.is_npc:
        return
    character.db.goal = [dict(c) for c in (quest.get("goal") or [])]
    character.db.goal_stalls = 0
    character.db.goal_from_quest = quest.get("id")


def _release_goal(character, quest):
    """Stop working at a quest goal once the quest is over."""
    if not character.db.is_npc:
        return
    if character.db.goal_from_quest == quest.get("id"):
        character.db.goal = []
        character.db.goal_stalls = 0
        character.db.goal_from_quest = None


def remaining(quest):
    """Seconds left, or None when the quest is untimed."""
    if not quest.get("time_limit") or not quest.get("accepted_at"):
        return None
    return quest["accepted_at"] + quest["time_limit"] - time.time()


def _short_time(seconds):
    seconds = int(max(0, seconds))
    if seconds >= 120:
        return f"{seconds // 60} minutes"
    return f"{seconds} seconds"


def _world_root(character):
    room = getattr(character, "location", None)
    return room.db.world_root if room else None


def _tally(character, outcome, world_root, title=""):
    """
    Add one to the character's record of errands run.

    Every world keeps these two, under these names, whatever else it invents:
    a count of what somebody has actually done is the plainest fact there is
    about them, and it is worth nothing if half the world calls it something
    else. They are seeded into every register for that reason.
    """
    from world import traits

    slug = "quests_completed" if outcome == DONE else "quests_failed"
    traits.bump(character, slug, 1, world_root=world_root,
                reason=title or None)


def _apply(character, effects, world_root):
    from world.effects import apply as apply_effects

    if not effects:
        return []
    return apply_effects(character, character.location, effects,
                         world_root=world_root)


def review(character, announce=True):
    """
    Test every active quest, completing and failing as due.

    Called whenever the world changes under a player and on a slow timer, so
    that finishing a quest is noticed at the moment it happens rather than
    when someone thinks to ask.
    """
    room = character.location
    world_root = room.db.world_root if room else None
    finished = []

    for quest in _quests(character):
        if quest.get("status") != ACTIVE:
            continue
        quest_id = quest["id"]

        if goals.satisfied(quest.get("goal"), character, world_root):
            _update(character, quest_id, status=DONE)
            _release_goal(character, quest)
            _tally(character, DONE, world_root, quest["title"])
            said = _apply(character, quest.get("reward"), world_root)
            if announce:
                _tell(character,
                      f"|gQuest complete: |w{quest['title']}|g.|n",
                      f"{character.key} has done what {quest['giver']} asked: "
                      f"{quest['title']}.",
                      said)
            finished.append((quest, True))
            continue

        left = remaining(quest)
        if left is not None and left <= 0:
            _update(character, quest_id, status=FAILED)
            _release_goal(character, quest)
            _tally(character, FAILED, world_root, quest["title"])
            said = _apply(character, quest.get("punishment"), world_root)
            if announce:
                _tell(character,
                      f"|rQuest failed: |w{quest['title']}|r — out of time.|n",
                      f"{character.key} has run out of time on "
                      f"{quest['giver']}'s errand: {quest['title']}.",
                      said)
            finished.append((quest, False))

    return finished


def _tell(character, own, public, extra=()):
    """
    Report a quest outcome to whoever should hear it.

    A player reads their own messages. An NPC has nobody reading its
    messages at all, so the room hears instead -- which is rather the point
    of letting NPCs run errands for each other: what a player standing there
    sees is the world getting on with its own business.
    """
    if not character.db.is_npc:
        character.msg(own)
        for line in extra:
            character.msg(line)
        return

    room = character.location
    if room is None:
        return
    room.msg_contents(public)
    for line in extra:
        room.msg_contents(line)
    if hasattr(character, "_add_to_history"):
        character._add_to_history("action", character.key, public)

    # The people standing there should be able to react to it -- the character
    # who asked most of all. This is the same path any other room event takes,
    # so it respects the chain cap and the activity gate.
    from world.npc_gen import notify_npcs

    notify_npcs(room, "action", character.key, public, exclude=character,
                actor=character)


def review_room(room):
    """Review the quests of everyone in a room, NPCs included."""
    if room is None:
        return
    for obj in list(room.contents):
        if is_person(obj):
            review(obj)


def format_list(character):
    """The player's quest list, offers first, with per-condition progress."""
    room = character.location
    world_root = room.db.world_root if room else None
    entries = visible(character)
    if not entries:
        return "You have no quests. Talk to the people you meet."

    lines = []
    offers = [q for q in entries if q.get("status") == OFFERED]
    active = [q for q in entries if q.get("status") == ACTIVE]

    if offers:
        lines.append("|wOffered to you:|n")
        for quest in offers:
            lines.append(f"  |w{quest['id']}.|n {quest['title']}  |x(from {quest['giver']})|n")
            if quest.get("description"):
                lines.append(f"      {quest['description']}")
            lines.append(f"      |xAsks:|n {goals.describe(quest['goal'], character, world_root)}")
            if quest.get("time_limit"):
                lines.append(f"      |xTime limit:|n {_short_time(quest['time_limit'])}")
            if quest.get("reward"):
                lines.append(f"      |xReward:|n {_summarise(quest['reward'])}")
            if quest.get("punishment"):
                lines.append(f"      |xIf you fail:|n {_summarise(quest['punishment'])}")
        lines.append("")
        lines.append("Type |wquests accept|n or |wquests decline|n.")

    if active:
        if offers:
            lines.append("")
        lines.append("|wUnderway:|n")
        for quest in active:
            left = remaining(quest)
            clock = f"  |x({_short_time(left)} left)|n" if left is not None else ""
            lines.append(f"  |w{quest['id']}.|n {quest['title']}  |x(from {quest['giver']})|n{clock}")
            for met, text in goals.progress(quest["goal"], character, world_root):
                mark = "|gdone|n" if met else "|xtodo|n"
                lines.append(f"      [{mark}] {text}")
        lines.append("")
        lines.append("|xOne errand at a time. |wquests abandon|x gives this "
                     "one up, and nothing is exacted for it.|n")

    return "\n".join(lines)


def _summarise(effects):
    """Rewards and punishments in words, for the quest listing."""
    parts = []
    for effect in effects or []:
        etype = effect.get("type")
        name = effect.get("name") or effect.get("name_role") or "something"
        if etype == "create_object":
            parts.append(f"you receive {name}")
        elif etype == "destroy_object":
            parts.append(f"you lose {name}")
        elif etype == "move_object":
            parts.append(f"{name} changes hands")
        elif etype == "set_state":
            added = ", ".join(effect.get("add") or []) or "changed"
            parts.append(f"{name} becomes {added}")
        elif etype == "modify_object":
            parts.append(f"{name} is altered")
    return "; ".join(parts) or "nothing in particular"
