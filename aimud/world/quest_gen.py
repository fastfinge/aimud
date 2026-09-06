"""
Turning what a character wants into conditions the game can test.

Used for two things that are the same job: a quest an NPC asks a player to
do, and a goal an NPC sets for itself.

An NPC asks for something in its own words -- "fetch me the chalk from the
storeroom and I'll give you a token". Making that testable means naming real
objects and writing typed conditions, which is the hardest structured output
in the game and was previously demanded of the dialogue model in the middle
of a tool call that was also supposed to produce speech in character. No
quest was ever successfully offered.

So it happens here instead, in its own call, on its own model. It is rare --
once per quest, not once per reaction -- so it can afford a capable model
where dialogue cannot.
"""

import json
import re
import urllib.request

from twisted.internet import threads

from evennia.utils import logger

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_SYSTEM = """You turn a character's request into a quest a game can check.

Respond with a single JSON object — no other text — matching:
{
  "title": "Three or four words naming the errand",
  "goal": [ ... ],
  "reward": [ ... ],
  "punishment": [ ... ]
}

goal is what must become true for the errand to be done. Each entry is one of:
{"type": "holds",     "object": "brass key"}                  they are carrying it
{"type": "delivered", "object": "letter", "to": "Clerk"}      they gave it to someone
{"type": "state",     "object": "lamp", "is": ["lit"], "lacks": ["broken"]}
{"type": "gone",      "object": "rats"}                        it no longer exists
{"type": "exists",    "object": "stew"}                        it has been made
{"type": "in_room",   "room": "Kitchen"}                       they went there

Name objects as they are actually called in the list you are given. Do not
invent a condition type, and do not ask for something the world has no way to
show: a goal that cannot be tested can never be completed, and the errand
would hang forever.

reward is what they get, and punishment what it costs them to fail. Both are
lists of effects, usually:
{"type": "create_object", "name": "...", "description": "...", "takeable": true, "location": "actor"}
{"type": "destroy_object", "name": "the thing they lose"}
{"type": "set_state", "name": "...", "add": ["blessed"]}

Give an empty punishment list unless the character clearly threatened one.
Keep the goal to one or two conditions. Return only the JSON object."""


def _call_openrouter(api_key, model, messages):
    payload = {"model": model, "messages": messages}
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())["choices"][0]["message"]["content"]


def _parse_json_object(content):
    try:
        return json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON in model response: {content!r}")
        return json.loads(match.group())


def _surroundings(npc, target):
    """
    What the quest may refer to: the things that actually exist nearby.

    Without this the model invents object names, and a goal naming something
    that is not there can never be satisfied.
    """
    from evennia.objects.objects import DefaultCharacter

    room = npc.location
    here, carried, people, exits = [], [], [], []
    for obj in (room.contents if room else []):
        if getattr(obj, "destination", None) is not None:
            exits.append(obj.key)
        elif obj.db.is_npc or isinstance(obj, DefaultCharacter):
            people.append(obj.get_display_name(npc))
        else:
            here.append(obj.key)
    for obj in target.contents:
        carried.append(obj.key)
    for obj in npc.contents:
        here.append(f"{obj.key} (carried by {npc.key})")

    room_title = (room.db.room_title or room.key) if room else "nowhere"
    return (
        f"Room: {room_title}\n"
        f"Objects here: {', '.join(here) or 'nothing loose'}\n"
        f"{target.get_display_name(npc)} is carrying: {', '.join(carried) or 'nothing'}\n"
        f"People here: {', '.join(people) or 'nobody'}\n"
        f"Ways out: {', '.join(exits) or 'none'}"
    )


def formalise(account, npc, target, request, offer, consequence, on_success, on_error):
    """
    Async. Turn a spoken request into a testable quest.

    Calls on_success({"title", "goal", "reward", "punishment"}) or
    on_error(msg) in the main thread.
    """
    model = (account.get_model_for("quests")
             or account.get_model_for("commands")
             or "openai/gpt-4o-mini")
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    room = npc.location
    world = (room.db.world_description if room else "") or ""

    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                f"World: {world}\n\n"
                f"{npc.key} is asking {target.get_display_name(npc)} for something.\n\n"
                f"What {npc.key} wants: {request}\n"
                f"What {npc.key} offers: {offer or 'nothing in particular'}\n"
                f"What {npc.key} threatens if it is not done: "
                f"{consequence or 'nothing'}\n\n"
                f"{_surroundings(npc, target)}\n\n"
                f"Write this as a checkable quest."
            ),
        },
    ]

    def _done(content):
        try:
            data = _parse_json_object(content)
            on_success({
                "title": str(data.get("title", "")).strip() or "An errand",
                "goal": data.get("goal") or [],
                "reward": data.get("reward") or [],
                "punishment": data.get("punishment") or [],
            })
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(
        _call_openrouter, api_key, model, messages
    ).addCallbacks(_done, _fail)


_GOAL_SYSTEM = """You turn what a character wants into conditions a game can check.

Respond with a single JSON object — no other text — matching:
{"goal": [ ... ]}

Each entry is one of:
{"type": "holds",     "object": "brass key"}                   they are carrying it
{"type": "delivered", "object": "letter", "to": "Clerk"}       they gave it to someone
{"type": "state",     "object": "lamp", "is": ["lit"]}         its condition
{"type": "gone",      "object": "rats"}                        it no longer exists
{"type": "in_room",   "room": "Kitchen"}                       they went there

Name objects and rooms as they are actually called in the list you are given.
Give one or two conditions, and something reachable from where they are --
this is what the character will do next, not their life's ambition. Return an
empty list if what they want cannot be expressed this way."""


def formalise_goal(account, npc, want, on_success, on_error):
    """
    Async. Turn a character's stated want into testable conditions.

    Calls on_success([condition, ...]) or on_error(msg) in the main thread.
    """
    model = (account.get_model_for("quests")
             or account.get_model_for("commands")
             or "openai/gpt-4o-mini")
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    room = npc.location
    world = (room.db.world_description if room else "") or ""
    messages = [
        {"role": "system", "content": _GOAL_SYSTEM},
        {
            "role": "user",
            "content": (
                f"World: {world}\n\n"
                f"{npc.key} wants: {want}\n\n"
                f"{_surroundings(npc, npc)}\n\n"
                f"Write this as checkable conditions."
            ),
        },
    ]

    def _done(content):
        try:
            data = _parse_json_object(content)
            on_success(data.get("goal") or [])
        except Exception as exc:
            on_error(str(exc))

    threads.deferToThread(
        _call_openrouter, api_key, model, messages
    ).addCallbacks(_done, lambda f: on_error(f.getErrorMessage()))
