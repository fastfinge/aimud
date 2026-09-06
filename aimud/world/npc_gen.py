"""
AI generation and reaction for NPCs.

generate_npc()          — create an NPC appropriate to a room (async)
generate_npc_reaction() — send tool-call request to dialogue model (async)
notify_npcs()           — notify all NPCs in a room of an event (sync helper)
"""

import json
import re
import urllib.request

from twisted.internet import threads

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ---------------------------------------------------------------------------
# Tool definitions sent to the dialogue model
# ---------------------------------------------------------------------------

NPC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "move",
            "description": "Move through an available exit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "description": "Exit direction or name (e.g. 'north', 'east')",
                    }
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "say",
            "description": "Say something aloud in the room.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"}
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get",
            "description": "Pick up an object from the room.",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {"type": "string"}
                },
                "required": ["object_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "give",
            "description": "Give an object from your inventory to someone in the room.",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {"type": "string"},
                    "recipient": {
                        "type": "string",
                        "description": "Name of the player or NPC to give to",
                    },
                },
                "required": ["object_name", "recipient"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "emote",
            "description": "Perform an action or gesture (third-person description).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Third-person description, e.g. 'nods solemnly' or 'adjusts her hood'",
                    }
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create",
            "description": "Create a new object in the room.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "takeable": {
                        "type": "boolean",
                        "description": "Whether the object can be picked up by players",
                    },
                },
                "required": ["name", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "destroy",
            "description": "Destroy an object in the room or in your inventory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {"type": "string"}
                },
                "required": ["object_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "modify",
            "description": "Change the name or description of an existing object.",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {
                        "type": "string",
                        "description": "Current name of the object to modify",
                    },
                    "new_name": {"type": "string"},
                    "new_description": {"type": "string"},
                },
                "required": ["object_name"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_NPC_GEN_SYSTEM = """You generate NPC characters for a text-based MUD.
Respond with a single JSON object only — no other text:
{"name": "Character Name (1-3 words)", "description": "3-5 sentence vivid physical and behavioral description."}
The character must fit naturally in the world and room described."""

_NPC_REACT_SYSTEM = (
    "You are {npc_name}, a character in a text-based MUD. Stay in character at all times.\n\n"
    "World: {world_desc}\n"
    "Your description: {npc_desc}\n\n"
    "Current room: [{room_title}]\n"
    "{room_desc}\n"
    "{room_contents}\n\n"
    "Use the available tools to react naturally to recent events. "
    "You may call 0-3 tools per response. "
    "If nothing warrants a response, call no tools. Keep reactions brief and in-character."
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call_openrouter(api_key, model, messages, tools=None):
    payload = {"model": model, "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _parse_json(content):
    try:
        return json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise ValueError(f"No JSON in model response: {content!r}")


def _room_context(room, npc):
    """Build a short room context string for the reaction prompt."""
    people, objects, exits = [], [], []
    for obj in room.contents:
        if obj is npc:
            continue
        if hasattr(obj, "sessions"):
            people.append(obj.key)
        elif getattr(obj, "destination", None) is not None:
            exits.append(obj.key)
        elif obj.db.is_npc:
            people.append(f"{obj.key} (NPC)")
        else:
            objects.append(obj.key)
    parts = []
    if people:
        parts.append("People present: " + ", ".join(people))
    if objects:
        parts.append("Objects here: " + ", ".join(objects))
    if exits:
        parts.append("Exits: " + ", ".join(exits))
    return "\n".join(parts)


#: How many recent events go into a prompt verbatim.  Everything older is
#: reached through memory instead, so this stays small on purpose.
WORKING_MEMORY_EVENTS = 5


def _memory_inputs(npc, room_title):
    """
    Prepare an NPC's prompt memory. Main thread -- it reads the Evennia DB.

    Returns (recent events as text, memory bank name, recall query).  The
    query is the last couple of events, since what an NPC needs to remember
    is whatever bears on what just happened; with nothing going on, the room
    itself is the cue.
    """
    from world.memory import bank_for

    history = npc.db.action_history or []
    recent = history[-WORKING_MEMORY_EVENTS:]
    query = _format_history(history[-2:]) if history else f"being in {room_title}"
    return _format_history(recent), bank_for(npc), query


def _format_history(history):
    if not history:
        return "(no prior events)"
    from world.memory import describe_event

    return "\n".join(
        describe_event(
            event.get("type", "action"),
            event.get("actor", "?"),
            event.get("text", ""),
        )
        for event in history
    )


# ---------------------------------------------------------------------------
# Public sync helper
# ---------------------------------------------------------------------------

def notify_npcs(room, event_type, actor_name, text, exclude=None, actor=None):
    """
    Tell everyone in `room` that something happened. Main thread only.

    NPCs witness it, which may provoke a reaction; player characters record it
    to memory.  NPCs write their own memories through their history hook, so
    they are not recorded twice here.

    event_type : "say" | "action" | "emote"
    exclude    : an object to skip (e.g. the NPC that caused the event)
    actor      : the character responsible, when it is one -- they remember
                 doing it rather than merely seeing it
    """
    from world.memory import record_room_event

    record_room_event(room, event_type, actor_name, text, actor=actor)

    for obj in room.contents:
        if obj is exclude:
            continue
        if obj.db.is_npc:
            obj.witness(event_type, actor_name, text)


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

def generate_npc(account, room, on_success, on_error):
    """
    Async. Generate and spawn an NPC appropriate for the room.
    Calls on_success(npc_obj) or on_error(msg) in the main thread.
    """
    model = account.get_model_for("npcs") or "openai/gpt-4o-mini"
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    world_desc = room.db.world_description or ""
    room_title = room.db.room_title or room.key
    room_desc = room.db.desc or ""

    messages = [
        {"role": "system", "content": _NPC_GEN_SYSTEM},
        {
            "role": "user",
            "content": (
                f"World: {world_desc}\n"
                f"Room: [{room_title}]\n{room_desc}\n\n"
                "Generate an NPC who would naturally be found here."
            ),
        },
    ]

    def _fetch():
        return _call_openrouter(api_key, model, messages)

    def _done(raw):
        try:
            content = raw["choices"][0]["message"].get("content") or ""
            data = _parse_json(content)
            name = str(data.get("name", "Stranger")).strip()
            description = str(data.get("description", "")).strip()

            from evennia import create_object
            from typeclasses.npcs import NPC

            npc = create_object(NPC, key=name, location=room)
            npc.db.desc = description
            npc.db.world_description = room.db.world_description
            on_success(npc)
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(_fetch).addCallbacks(_done, _fail)


def generate_npc_idle(account, npc, room, on_success, on_error):
    """
    Async. Prompt the NPC to take a spontaneous, self-initiated action.
    Uses the same tool-calling infrastructure as generate_npc_reaction but
    asks the model what the NPC would do of its own accord right now.
    Calls on_success(list[{"name", "args"}]) or on_error(msg) in the main thread.
    """
    model = account.get_model_for("dialogue") or "openai/gpt-4o-mini"
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    world_desc = room.db.world_description or npc.db.world_description or ""
    room_title = room.db.room_title or room.key
    room_desc = room.db.desc or ""
    room_contents = _room_context(room, npc)
    history_text, bank, query = _memory_inputs(npc, room_title)

    system = _NPC_REACT_SYSTEM.format(
        npc_name=npc.key,
        world_desc=world_desc,
        npc_desc=npc.db.desc or "(no description)",
        room_title=room_title,
        room_desc=room_desc,
        room_contents=room_contents,
    )

    def _fetch():
        from world.memory import format_memories, recall_sync

        recalled = format_memories(recall_sync(bank, query, top_k=6))
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"What you remember about this place and these people:\n"
                    f"{recalled}\n\n"
                    f"Just now:\n{history_text}\n\n"
                    "Nothing has just happened — act of your own accord. "
                    "What do you do right now, naturally and in character? "
                    "Choose something that fits the moment and the world."
                ),
            },
        ]
        return _call_openrouter(api_key, model, messages, tools=NPC_TOOLS)

    def _done(raw):
        try:
            message = raw["choices"][0]["message"]
            tool_calls_raw = message.get("tool_calls") or []
            parsed = []
            for tc in tool_calls_raw:
                if tc.get("type") == "function":
                    fn = tc["function"]
                    try:
                        call_args = json.loads(fn.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        call_args = {}
                    parsed.append({"name": fn["name"], "args": call_args})
            on_success(parsed)
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(_fetch).addCallbacks(_done, _fail)


def generate_npc_reaction(account, npc, room, on_success, on_error):
    """
    Async. Send the NPC's context + history to the dialogue model with tool-calling.
    Calls on_success(list[{"name", "args"}]) or on_error(msg) in the main thread.
    """
    model = account.get_model_for("dialogue") or "openai/gpt-4o-mini"
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    world_desc = room.db.world_description or npc.db.world_description or ""
    room_title = room.db.room_title or room.key
    room_desc = room.db.desc or ""
    room_contents = _room_context(room, npc)

    # Working memory verbatim, long memory by relevance.  Anything the model
    # needs from further back is recalled rather than replayed.
    history_text, bank, query = _memory_inputs(npc, room_title)

    system = _NPC_REACT_SYSTEM.format(
        npc_name=npc.key,
        world_desc=world_desc,
        npc_desc=npc.db.desc or "(no description)",
        room_title=room_title,
        room_desc=room_desc,
        room_contents=room_contents,
    )

    def _fetch():
        # Recall runs here, inside the thread that was already being deferred
        # for the network call, so it costs no extra hop and never touches the
        # reactor.
        from world.memory import format_memories, recall_sync

        recalled = format_memories(recall_sync(bank, query, top_k=6))
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"What you remember that bears on this:\n{recalled}\n\n"
                    f"Just now:\n{history_text}\n\nHow do you respond?"
                ),
            },
        ]
        return _call_openrouter(api_key, model, messages, tools=NPC_TOOLS)

    def _done(raw):
        try:
            message = raw["choices"][0]["message"]
            tool_calls_raw = message.get("tool_calls") or []
            parsed = []
            for tc in tool_calls_raw:
                if tc.get("type") == "function":
                    fn = tc["function"]
                    try:
                        call_args = json.loads(fn.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        call_args = {}
                    parsed.append({"name": fn["name"], "args": call_args})
            on_success(parsed)
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(_fetch).addCallbacks(_done, _fail)
