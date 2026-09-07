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


def accept(character, quest_id):
    """Take on an offered quest. Returns (quest, message)."""
    quest = _find(character, quest_id)
    if quest is None or quest.get("status") != OFFERED:
        return None, "There is no such offer."
    _update(character, quest_id, status=ACTIVE, accepted_at=time.time())
    quest = _find(character, quest_id)
    deadline = ""
    if quest.get("time_limit"):
        deadline = f" You have {_short_time(quest['time_limit'])}."
    return quest, f"You accept: |w{quest['title']}|n.{deadline}"


def decline(character, quest_id):
    """Turn down an offered quest. Returns (quest, message)."""
    quest = _find(character, quest_id)
    if quest is None or quest.get("status") != OFFERED:
        return None, "There is no such offer."
    _update(character, quest_id, status=DECLINED)
    return quest, f"You decline: {quest['title']}."


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
            said = _apply(character, quest.get("reward"), world_root)
            if announce:
                character.msg(f"|gQuest complete: |w{quest['title']}|g.|n")
                for line in said:
                    character.msg(line)
            finished.append((quest, True))
            continue

        left = remaining(quest)
        if left is not None and left <= 0:
            _update(character, quest_id, status=FAILED)
            said = _apply(character, quest.get("punishment"), world_root)
            if announce:
                character.msg(f"|rQuest failed: |w{quest['title']}|r — out of time.|n")
                for line in said:
                    character.msg(line)
            finished.append((quest, False))

    return finished


def review_room(room):
    """Review the quests of every player character in a room."""
    from evennia.objects.objects import DefaultCharacter

    if room is None:
        return
    for obj in list(room.contents):
        if isinstance(obj, DefaultCharacter):
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
        lines.append("\nType |wquests accept <number>|n or |wquests decline <number>|n.")

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
