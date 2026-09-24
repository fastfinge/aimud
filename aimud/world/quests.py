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

**A quest used to exist only from the moment it was offered.** `offer` built
the record on the character receiving it, so there was no such thing as an
errand waiting to be given, and every quest the game had ever seen was written
by `quest_gen` in the middle of a conversation. A world built by hand needs the
other thing, and so does a world with no model at all.

So a **spec** is an errand written in advance and kept on the world: the same
fields `offer` takes, plus the four only a pre-written errand needs -- who
gives it, whether it repeats, what must be done first, and when it is
available. `offer` takes one, `quest_gen` writes one, and a player writes one
through the menus, which is what keeps this from being a second quest system.

**A spec belongs to the world, not to its giver.** Deleting the character who
handed it out leaves it in place with nobody to give it, the way a rule filed
against a deleted object stays in the book -- one store and an orphan report,
rather than a second store and an index to keep in step with it.

**Each giver keeps its own way of asking.** Reuse is meant to save the
expensive half of an errand -- a testable goal, sanitised conditions, effects
inside QUEST_EFFECTS -- and not to make two characters say the same sentence.
The goal is the machine half; the description is the voice, and it hangs on
the giver. Which is the split `attempt.py` already makes one level down,
between what a verb means for everything of its sort and how this door differs
from that door.
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


def lookup_tools():
    """
    `list_errands`: the written errands, for a generator to reuse one.

    A world with a dozen written errands is one where a character asked for
    work should usually be handing one out rather than inventing a thirteenth.
    Reuse saves the expensive half -- a testable goal, sanitised conditions,
    effects inside QUEST_EFFECTS -- and `use_quest` lets the character still
    ask in their own words, which is the cheap half and the one worth writing
    fresh. This is "one vocabulary per world" (world/traits.py) applied to
    errands, and it heads off the same drift: eleven near-identical
    fetch-the-chalk quests with eleven different goals, only some testable.
    """
    from world import toolbox as tb

    def listing(ctx, args):
        held = specs(ctx.world_root)
        if not held:
            return "This world has no written errands."
        lines = []
        for record in sorted(held.values(), key=lambda r: r.get("id", "")):
            givers = ", ".join(npc.key for npc, _said
                               in givers_of(ctx.world_root, record))
            lines.append(
                f"{record['id']}: {record.get('title')} -- "
                f"{goals.describe(record.get('goal'))}"
                + (f" (given by {givers})" if givers else " (given by nobody)")
                + ("" if record.get("repeatable") else " [once ever]"))
        return "\n".join(lines)

    return [tb.Tool("list_errands",
                    "The errands this world has already written. Hand one of "
                    "these out rather than writing another like it.",
                    tb.params(tb.PAGE), tb.answering(listing),
                    doing="looking up this world's errands", looks=True,
                    available=lambda ctx: bool(specs(ctx.world_root)))]


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
          reward=None, punishment=None, time_limit=None, spec_id=""):
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
        # Which written errand this came from, when it came from one. What
        # makes "once ever" mean it, and what a chain's `after` reads.
        "spec": str(spec_id or ""),
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


# ---------------------------------------------------------------------------
# Specifications: an errand written in advance
# ---------------------------------------------------------------------------

#: Where a world keeps the errands it holds, and the counter that names them.
SPECS_ATTR = "quest_specs"
SPECS_COUNTER = "quest_spec_counter"

#: Where a character records which written errands they have finished, and
#: when. Beside the quest list rather than in it: a finished quest leaves the
#: list in time, and "once ever" has to outlive that.
DONE_ATTR = "quests_done"


def specs(world_root):
    """Every errand this world holds, as {id: spec}."""
    from evennia.utils.dbserialize import deserialize

    if world_root is None:
        return {}
    return dict(deserialize(getattr(world_root.db, SPECS_ATTR, None)) or {})


def spec(world_root, spec_id):
    """One errand, or None."""
    return specs(world_root).get(str(spec_id or "").strip()) or None


def blank_spec(**fields):
    """An errand with every slot present, so nothing downstream has to guess."""
    record = {
        "id": "",
        "title": "",
        "description": "",
        "goal": [],
        "reward": [],
        "punishment": [],
        "time_limit": None,
        # Who hands it out, and in whose words:
        # [{"npc": <id>, "description": ""}]. A list, because one errand may
        # be several characters', and each of them asks differently. An empty
        # description falls back to the errand's own.
        "givers": [],
        # Once ever, or again after `cooldown` seconds.
        "repeatable": False,
        "cooldown": 0,
        # Errands that must be finished first, which is what makes a chain.
        "after": [],
        # And anything else that must be true before it is on offer.
        "only_when": [],
    }
    record.update({k: v for k, v in fields.items() if k in record})
    return record


def save_spec(world_root, record):
    """Write an errand, giving it an id if it has none. Answers with it."""
    if world_root is None:
        return None
    record = blank_spec(**dict(record or {}))
    record["goal"] = goals.sanitise(record.get("goal") or [])
    record["reward"] = _clean_effects(record.get("reward"))
    record["punishment"] = _clean_effects(record.get("punishment"))
    if not record["id"]:
        number = int(getattr(world_root.db, SPECS_COUNTER, 0) or 0) + 1
        setattr(world_root.db, SPECS_COUNTER, number)
        record["id"] = f"q{number}"
    store = specs(world_root)
    store[record["id"]] = record
    setattr(world_root.db, SPECS_ATTR, store)
    logger.log_info(f"quests: {record['id']} {record['title']!r} written for "
                    f"{world_root.key}")
    return record


def remove_spec(world_root, spec_id):
    """Take an errand out of the world. Quests already accepted are untouched."""
    store = specs(world_root)
    spec_id = str(spec_id or "").strip()
    if spec_id not in store:
        return None
    gone = store.pop(spec_id)
    setattr(world_root.db, SPECS_ATTR, store)
    return gone


def givers_of(world_root, record):
    """The characters who hand one out, skipping any that have been deleted."""
    from evennia.objects.models import ObjectDB

    found = []
    for entry in (record or {}).get("givers") or []:
        try:
            npc = ObjectDB.objects.get(id=int(entry.get("npc")))
        except Exception:
            continue
        found.append((npc, str(entry.get("description") or "")))
    return found


def orphaned(world_root):
    """
    Errands with nobody left to give them.

    Reported rather than repaired, the way `rulebooks.orphans` reports a rule
    whose object has gone: an errand somebody wrote is worth keeping until
    they say otherwise, and `edit quest` hands it to somebody else.
    """
    return [record for record in specs(world_root).values()
            if not givers_of(world_root, record)]


def specs_from(world_root, npc):
    """What this character hands out, as [(spec, their own words)]."""
    found = []
    for record in sorted(specs(world_root).values(),
                         key=lambda r: r.get("id", "")):
        for entry in record.get("givers") or []:
            try:
                if int(entry.get("npc")) == npc.id:
                    found.append((record, str(entry.get("description") or "")))
            except (TypeError, ValueError):
                continue
    return found


# -- what somebody has already done -----------------------------------------

def finished(character):
    """{spec id: when it was last finished} for this character."""
    from evennia.utils.dbserialize import deserialize

    return dict(deserialize(getattr(character.db, DONE_ATTR, None)) or {})


def record_finished(character, spec_id):
    if not spec_id:
        return
    done = finished(character)
    done[str(spec_id)] = time.time()
    setattr(character.db, DONE_ATTR, done)


def available(character, world_root, record):
    """
    (whether this errand may be offered to this character now, why not).

    Five questions, asked in the order somebody would ask them: have they done
    it already, is it too soon to do it again, have they done what comes
    first, is the world ready for it, and are their hands free.
    """
    if not record:
        return False, "there is no such errand"
    done = finished(character)
    spec_id = str(record.get("id") or "")
    when = done.get(spec_id)
    if when is not None:
        if not record.get("repeatable"):
            return False, "they have done it already"
        cooldown = int(record.get("cooldown") or 0)
        if cooldown and time.time() - when < cooldown:
            return False, "they did it too recently"
    for earlier in record.get("after") or []:
        if str(earlier) not in done:
            return False, f"they have not finished {earlier} yet"
    wanted = record.get("only_when") or []
    if wanted:
        from world import conditions

        ctx = conditions.context(actor=character, world_root=world_root,
                                 room=getattr(character, "location", None))
        if not conditions.satisfied(wanted, ctx):
            return False, "the world is not ready for it"
    if not can_accept(character):
        return False, "they already have an errand"
    return True, ""


def offer_spec(npc, character, record, description=""):
    """
    Hand a written errand over. Returns the quest, or None.

    The description is the giver's own where they have one and the errand's
    otherwise, which is what keeps one errand given by three characters from
    being the same sentence three times.
    """
    if not record:
        return None
    return offer(npc, character, record.get("title"),
                 description or record.get("description"),
                 record.get("goal"), reward=record.get("reward"),
                 punishment=record.get("punishment"),
                 time_limit=record.get("time_limit"),
                 spec_id=record.get("id"))


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
            # And against the written errand it came from, which is what
            # "once ever" and a chain's `after` read. Kept apart from the
            # quest list, which is swept.
            record_finished(character, quest.get("spec"))
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
            from world.model_json import listed

            added = ", ".join(listed(effect.get("add"))) or "changed"
            parts.append(f"{name} becomes {added}")
        elif etype == "modify_object":
            parts.append(f"{name} is altered")
    return "; ".join(parts) or "nothing in particular"
