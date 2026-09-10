"""
What a verb takes, declared once, instead of guessed at every time.

Inform 7 says `Powering is an action applying to one thing` before it says
anything about what powering does, and the separation earns its keep three
times over. This game has never had it: a verb's arity is inferred from
whatever the player happened to type, so `power` and `power datapad` become
two rules that must each be right, and a verb typed with no object produces a
rule whose effects name a role nobody bound.

That last one is not hypothetical. `search`, in the exported corpus, is stored
with `requires: {}` and an effect that sets `searched` on `direct` -- typed
bare, it binds no direct object, the effect resolves to nothing, and the
attempt reports success having changed the world not at all. A silent no-op is
worse than a refusal, because a refusal can be read.

So an action is declared: which roles it takes, whether each may be left
unsaid, and how near the actor has to be to each. And a sense, because every
lexical relation a rule writer is shown is only as right as the sense it
started from -- `verb_ancestors("launch")` answers `['open', 'propel']` from
the bare word, which is the world's `open` rule offered as a starting point
for launching a spacecraft.

**First answer stands.** As for a kind, and for the same reason: an action's
arity is what every rule about it was written against, and revising it later
would quietly change what those rules mean.
"""

from evennia.utils import logger

#: Where a world keeps what it has decided about each action.
ATTR = "action_specs"

#: The parts a verb can take. `actor` is not among them -- there is always
#: one, and no verb has to declare that somebody is doing it.
ROLES = ("direct", "instrument", "target", "container", "source")

#: How near the actor has to be for a role to count, and what follows.
#:
#: visible   -- it is enough to see it: read a notice across the room.
#: touchable -- within reach, which is `relations.reachable`.
#: carried   -- in their hands, and if it is not, they pick it up first.
#:
#: The third is Inform's `applying to one carried thing`, and it is the reason
#: to have this at all: 54 `holds` clauses across the corpus are each a
#: hand-written version of it, every one of them a refusal where an implicit
#: taking would have done.
VISIBLE, TOUCHABLE, CARRIED = "visible", "touchable", "carried"
ACCESS = (VISIBLE, TOUCHABLE, CARRIED)

#: What a role's access is when nobody says. Reaching for a thing is the
#: ordinary case; seeing it from across the room is the exception, and holding
#: it is a claim worth making deliberately.
DEFAULT_ACCESS = TOUCHABLE


def _store(world_root):
    return dict(getattr(world_root.db, ATTR, None) or {}) if world_root else {}


def spec(world_root, action):
    """What this world has decided about an action, or None if it is new."""
    from world import verbs

    if not world_root or not action:
        return None
    return _store(world_root).get(verbs.canonical_verb(str(action)))


def vocabulary(world_root):
    """Every action this world has declared, for a prompt that should reuse one."""
    return sorted(_store(world_root))


def clean_roles(applies_to):
    """
    A declaration's roles, with anything unusable dropped.

    Closed on the way in rather than trusted: a role nobody can bind and an
    access nobody can test are both conditions no attempt could ever meet, and
    the place to refuse them is before they are written down.
    """
    seen, out = set(), []
    for entry in (applies_to or []):
        try:
            role = str(entry.get("role") or "").strip().lower()
        except AttributeError:
            continue
        if role not in ROLES or role in seen:
            continue
        access = str(entry.get("access") or "").strip().lower()
        seen.add(role)
        out.append({
            "role": role,
            "access": access if access in ACCESS else DEFAULT_ACCESS,
            "optional": bool(entry.get("optional", False)),
        })
    return out


def declare(world_root, action, applies_to=(), sense="", means=""):
    """
    Settle what an action takes, once, and answer with what was settled.

    First one wins, as for a kind. What is stored is what every rule about the
    action was written against, so a later attempt that happens to name an
    extra noun does not get to change the arity out from under them.

    A sense is taken from the dictionary when English has already settled it --
    `power`, `airlock` and `blaster` have exactly one each -- so most actions
    need nobody asked. `means` falls back to that sense's gloss.
    """
    from world import lexicon, verbs

    action = verbs.canonical_verb(str(action or "").strip().lower())
    if not action:
        return None

    settled = spec(world_root, action)
    if settled is not None:
        return dict(settled)

    sense = str(sense or "").strip()
    if not sense or not lexicon.definition(sense):
        sense = lexicon.settled_sense(action)
    record = {
        "action": action,
        "sense": sense,
        "means": str(means or "").strip() or lexicon.definition(sense),
        "applies_to": clean_roles(applies_to),
    }
    if world_root:
        store = _store(world_root)
        store[action] = record
        setattr(world_root.db, ATTR, store)
        logger.log_info(
            f"actions: {action} takes "
            f"{', '.join(r['role'] for r in record['applies_to']) or 'nothing'}"
            + (f" ({sense})" if sense else ""))
    return record


def observe(world_root, action, bound):
    """
    Declare an action from an attempt, when nobody has declared it yet.

    The standing-in until a generator is asked properly (the plan's phase 8).
    What a player named is what the verb takes, and it is taken as *required* --
    deliberately, because the failure being fixed is the silent one. A verb
    first typed with a noun and later typed bare should say "power what?"
    rather than succeed at nothing.

    Costs no call and no round trip. An action already declared is left alone,
    which is the whole point of declaring it.
    """
    settled = spec(world_root, action)
    if settled is not None:
        return dict(settled)
    return declare(world_root, action, applies_to=[
        {"role": role, "access": DEFAULT_ACCESS, "optional": False}
        for role in ROLES if role in (bound or {})
    ])


# ---------------------------------------------------------------------------
# What a declaration is for
# ---------------------------------------------------------------------------

def missing_role(world_root, action, bound):
    """
    A role this action needs that nobody bound, or "".

    The check that turns a silent no-op into a sentence. Only roles declared
    required are reported: an optional one left unsaid is what an `instead`
    rule is for, and supplying it is that rule's job rather than this one's.
    """
    settled = spec(world_root, action)
    if not settled:
        return ""
    for entry in (settled.get("applies_to") or []):
        try:
            if entry.get("optional"):
                continue
            role = str(entry.get("role") or "")
        except AttributeError:
            continue
        if role and role not in (bound or {}):
            return role
    return ""


def asking_for(action, role):
    """"Power what?" -- the question a missing role asks."""
    which = {
        "direct": "what", "instrument": "with what", "target": "at what",
        "container": "in what", "source": "from what",
    }.get(role, "what")
    return f"{str(action).capitalize()} {which}?"


def access_for(world_root, action, role):
    """How near the actor must be to a role, whatever the declaration said."""
    settled = spec(world_root, action)
    for entry in ((settled or {}).get("applies_to") or []):
        try:
            if str(entry.get("role") or "") == role:
                return str(entry.get("access") or DEFAULT_ACCESS)
        except AttributeError:
            continue
    return DEFAULT_ACCESS


def to_take(world_root, action, bound, actor):
    """
    Everything the actor must be holding for this action, and is not.

    Inform's carrying requirements rule, as data. Nothing calls it yet: it
    lands in the attempt pipeline at the cutover, where taking something is
    an act with a message rather than a silent move, and where there is a
    phase for it to happen in. Written and tested here because it is what
    `access` is *for*, and a slot nothing reads is a slot that rots.
    """
    found = []
    for role, obj in sorted((bound or {}).items()):
        if obj is None or role not in ROLES:
            continue
        if access_for(world_root, action, role) != CARRIED:
            continue
        if getattr(obj, "location", None) is not actor:
            found.append(obj)
    return found


def prompt_block(world_root, action):
    """
    How to ask for a declaration. See `learn` below for who asks it.

    Kept beside the record it describes, the way `gear.prompt_block` and
    `affordances.PROMPT` are, so that the shape asked for and the shape read
    cannot drift apart.
    """
    from world import lexicon

    lines = [
        f'Declare what "{action}" takes, as a JSON object:',
        '{"applies_to": [{"role": "direct", "access": "touchable",',
        '                 "optional": false}], "sense": "", "means": ""}',
        "",
        "role is one of: " + ", ".join(ROLES) + ". Leave the list empty for a",
        "verb that takes nothing -- shrugging, waiting. There is always somebody",
        "acting, so never declare that.",
        "",
        "access says how near they must be:",
        "  visible    enough to see it, like reading a notice across a room",
        "  touchable  within reach. The ordinary answer.",
        "  carried    in their hands -- and if it is not, they pick it up",
        "             first, so never also require that they are holding it.",
        "",
        "optional is for a role that may be left unsaid, where the world can",
        'work out what was meant: "launch" aboard a ship means the ship.',
    ]
    asked = lexicon.verb_sense_prompt(action)
    if asked:
        lines += ["", asked.rstrip()]
    return "\n".join(lines) + "\n"


def learn(account, world_root, action, bound, actor, on_success,
          on_error=None):
    """
    Async. Settle what an action takes, and answer with the declaration.

    The first of the two questions a new verb costs, and the cheaper one: what
    roles it takes, how near they must be, and which may be left unsaid. Asked
    before anything is asked about what the verb *does*, because the answer
    changes that question -- a `direct` declared optional is what lets `power`
    typed bare reach an `instead` rule instead of being told "power what?".

    `observe` is what happens when this cannot be asked, and the two must not
    both fire: a declaration is settled once and first one wins, so an observed
    arity read off one attempt would lock out the real answer for good. That is
    why the caller asks before observing rather than after.

    Never fails the attempt, and so `on_error` never fires: it is in the
    signature because every other generator has one and a caller should not
    have to remember which. A verb whose declaration could not be had -- no
    key, no network, an answer that was not one -- falls back to what the
    attempt itself shows, which is what the world did before anybody asked at
    all. Refusing the verb instead would make a new world unplayable over a
    question it can manage without.
    """
    from world import llm, lore, model_json, verbs

    action = verbs.canonical_verb(str(action or "").strip().lower())
    settled = spec(world_root, action)
    if settled is not None:
        on_success(dict(settled))
        return

    def fall_back(_why=""):
        on_success(observe(world_root, action, bound))

    try:
        api_key = account.get_openrouter_key()
    except (AttributeError, ValueError):
        fall_back()
        return

    named = ", ".join(sorted(bound or {})) or "nothing"
    messages = [
        {"role": "system", "content": prompt_block(world_root, action)},
        {"role": "user",
         "content": (f"{lore.description(world_root, actor)}\n\n"
                     f'A player typed "{action}". The parser filled these '
                     f"roles from what they said: {named}.\n"
                     f"Declare what the action takes in general, not only what "
                     f"this one sentence happened to name.")},
    ]

    def answered(content):
        try:
            reply = model_json.parse_object(content)
        except Exception:
            fall_back()
            return
        # A declaration with an empty list is a real answer -- shrugging and
        # waiting take nothing, and the prompt says so. A reply with no
        # `applies_to` at all is not an answer, and taking it for one would
        # settle, permanently and on no evidence, that the verb takes nothing.
        if not hasattr(reply, "get") or "applies_to" not in reply:
            fall_back()
            return
        try:
            roles = list(reply.get("applies_to") or [])
        except (AttributeError, TypeError):
            fall_back()
            return
        on_success(declare(world_root, action, applies_to=roles,
                           sense=str(reply.get("sense") or ""),
                           means=str(reply.get("means") or "")))

    llm.fetch(llm.ask, api_key, account.model_for("commands"), messages,
              on_success=answered,
              on_error=lambda failure: fall_back(failure.getErrorMessage()))

