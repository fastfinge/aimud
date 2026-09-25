"""
What a model may bring into being in this world, and on whose account.

Every generator in this game answers the same two questions before it builds a
prompt: is there a key to spend, and is this worth spending it on. Neither of
them is the question a world's creator actually wants to ask, which is *what
may this world grow by itself*.

The endless-alchemy world is the case that makes it plain. It is a kitchen
with four substances in it, and the whole game is combining them into a fifth:
the model should invent things, and should invent the *sorts* of thing they
are, and should not be inventing rooms, or people, or a verb nobody typed.
Today the only way to say that is to have no key at all, which takes the
combining away too. The switch that exists is `worldmode`, and it is about how
hard a world thinks rather than about what it is allowed to think *about*.

**Three answers, not two**, and the middle one is the useful one:

* `always` -- anything may cause it, a character included. What every world
  has done so far, and the default, so no world in play changes.
* `asked` -- only when a *player's own action* reached for it. A player walks
  through a door and the room beyond is written; a wandering character walks
  through the same door and finds nothing. This is what keeps a world from
  growing while nobody is looking, without freezing it.
* `never` -- nothing of this sort is ever generated here. What is here is what
  somebody built.

**Five things, because five is what a generator can be pointed at.** Rooms,
items, people, verbs and errands. Not "descriptions" or "names": those are
part of making one of the five, and a world that could have a room but not its
description would have a nameless room rather than a saved call.

**What this is not.** It does not govern a character *thinking* -- an innkeeper
who already exists answering a question is not the world growing, and turning
people off does not strike anybody dumb. Whether characters act on their own is
a separate switch and a separate plan (`future-plans.md`, NPC autonomy). Nor is
it a permission: `owner` on a maker says who may build, and this says what a
world may build for itself.

**Read through the sponsor.** `Sponsor.will(making)` is the one question a
generator asks, because a sponsor is the only thing that knows all three parts
of the answer -- the world, whether there is a key, and who caused the call.
"""

from evennia.utils import logger

#: Where a world keeps what it allows, as {what: how freely}.
ATTR = "generation"

#: How freely, in the order a menu offers them: most permitted first, because
#: that is what every world already does and what most of them want.
ALWAYS, ASKED, NEVER = "always", "asked", "never"
SETTINGS = (ALWAYS, ASKED, NEVER)

#: What every world does unless it says otherwise. Not a preference: it is
#: what this game was before this module existed, and a world already in play
#: must not change under somebody because a register gained a default.
DEFAULT = ALWAYS

#: The five, each with what it covers and what it reads like turned off.
#: Written out rather than left to the call sites for the reason
#: `effects.VOCABULARY` is: the sentence and the gate have to be able to drift
#: only together, and `settings` and `help` read these.
MAKES = (
    ("rooms", "Places, and the ways between them",
     "the map is what somebody built, and stops where they stopped"),
    ("items", "Things, and the sorts of thing they are",
     "nothing is conjured by being named; what is here is what was made"),
    ("people", "Characters",
     "nobody new arrives. Whoever is here stays, and still talks"),
    ("verbs", "What a verb means here: actions, and the rules about them",
     "a verb nobody has written a rule for does nothing"),
    ("quests", "Errands characters ask for",
     "characters hand out the errands this world has written, and invent none"),
)

MADE = tuple(name for name, _label, _off in MAKES)


def label_of(making):
    for name, label, _off in MAKES:
        if name == making:
            return label
    return str(making)


def _off_reads_as(making):
    for name, _label, off in MAKES:
        if name == making:
            return off
    return "nothing of that sort is generated here"


# ---------------------------------------------------------------------------
# What a world holds
# ---------------------------------------------------------------------------

def held(world_root):
    """{what: how freely} for this world, filled in with the default."""
    from evennia.utils.dbserialize import deserialize

    stored = {}
    if world_root is not None:
        stored = dict(deserialize(getattr(world_root.db, ATTR, None)) or {})
    return {name: _clean(stored.get(name)) for name in MADE}


def setting(world_root, making):
    """How freely this world generates one sort of thing."""
    return held(world_root).get(str(making), DEFAULT)


def _clean(wanted):
    wanted = str(wanted or "").strip().lower()
    return wanted if wanted in SETTINGS else DEFAULT


def choose(world_root, making, wanted):
    """
    Put one of them at a setting. Returns what it is at afterwards.

    Everything is stored, the default included, so that what a world was set
    up with survives a `reset world` -- which rebuilds from the spec and would
    otherwise quietly put a world's own decisions back to the default.
    """
    making = str(making or "").strip().lower()
    if world_root is None or making not in MADE:
        return DEFAULT
    stored = held(world_root)
    stored[making] = _clean(wanted)
    setattr(world_root.db, ATTR, stored)
    logger.log_info(f"permits: {world_root.key} generates {making} "
                    f"{stored[making]}")
    return stored[making]


def apply_choice(world_root, wanted):
    """The whole choice at once, as a world spec carries it."""
    for making in MADE:
        if making in dict(wanted or {}):
            choose(world_root, making, dict(wanted)[making])


def from_spec(spec):
    """What a world spec says about this, cleaned. {} when it says nothing."""
    given = dict((spec or {}).get(ATTR) or {})
    return {name: _clean(given[name]) for name in MADE if name in given}


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------

def allows(world_root, making, actor=None, wanted=None):
    """
    Whether a model may be asked to make one of these, for this actor.

    `wanted` is the setting to use instead of the world's own, for the one
    caller that has no world yet to ask: making the first room of a world is
    the moment the choice is being applied, and the world it would be read off
    does not exist until the room does.
    """
    how = _clean(wanted) if wanted is not None \
        else setting(world_root, making)
    if how == NEVER:
        return False
    if how == ALWAYS:
        return True
    return is_player(actor)


def is_player(actor):
    """
    Whether an action was a player's own, which is what `asked` turns on.

    A puppeted character, and nothing else. A character with no session is
    somebody's body left standing in a room, and the whole point of `asked` is
    that a world does not grow while its player is away.
    """
    from evennia.objects.objects import DefaultCharacter

    if actor is None or not isinstance(actor, DefaultCharacter):
        return False
    if getattr(actor.db, "is_npc", False):
        return False
    try:
        return bool(actor.sessions.count())
    except AttributeError:
        return bool(getattr(actor, "account", None))


def refused(world_root, making, actor=None):
    """
    Why nothing was generated, for whoever is standing there.

    Said differently for the two reasons, because they want two different
    things done about them: a world that never generates this is finished as
    it is and wants building by hand, and a world that only answers a player
    has simply been reached by the wrong person.
    """
    how = setting(world_root, making)
    if how == NEVER:
        return (f"Nothing new of that sort happens in this world -- "
                f"{_off_reads_as(making)}.")
    if how == ASKED and not is_player(actor):
        return (f"Nothing new of that sort happens here unless a player goes "
                f"looking for it.")
    return ""


def report(world_root):
    """What this world allows, as lines somebody should read."""
    stored = held(world_root)
    lines = []
    for name, label, off in MAKES:
        how = stored[name]
        said = {ALWAYS: "|gwhenever anything asks|n",
                ASKED: "|yonly when a player goes looking|n",
                NEVER: f"|rnever|n -- {off}"}[how]
        lines.append(f"  |w{name}|n ({label.lower()}): {said}")
    return "\n".join(lines)
