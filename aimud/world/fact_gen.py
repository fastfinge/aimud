"""
Turning what a character has been through into what it now knows.

Sleep condenses a run of events into summaries. This reads those summaries and
asks what is simply true afterwards: that Bram owes a favour, that the ledger
went missing in the winter, that the archivist does not trust the steward. An
event is something that happened once; a fact is what a character carries away
from it, and it is what should still be there when the evening itself has gone
hazy.

Three things keep it cheap enough to be worth having.

It reads summaries rather than events, so a week of somebody's afternoons
arrives as a dozen lines instead of three hundred.

It runs one character at a time, in a chain rather than a fan-out, so a world
of forty NPCs cannot put forty requests in flight at once.

And it only runs when nobody is playing. This is a single-player game: there
is no moment convenient for everybody, only a moment convenient for the one
person at the keyboard, and that moment is when they have stopped typing. Any
character reached after they come back is left for the next quiet spell.
"""

import json
import urllib.request

from evennia.utils import logger
from twisted.internet import threads

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

#: Most facts taken from one character in one pass. A model given no limit
#: writes a sentence per summary, which is not distillation, only rephrasing.
MAX_FACTS = 8

_SYSTEM_PROMPT = """You read what one character in a text adventure has been through and say what they now know.

Respond with a single JSON object — no other text — matching:
{"facts": ["...", "..."]}

You are given summaries of that character's recent experience, written from
their point of view. Return the things that are STILL TRUE afterwards and
worth carrying: what they learned about a person, a place, a thing, or an
arrangement between them.

Write each fact as one short sentence in the character's own first person —
"Bram owes me a favour", "the ledger went missing last winter", "the archivist
does not trust the steward".

Leave out:
- anything that was only true for a moment (where somebody was standing, what
  they were holding at the time)
- the character's own passing actions, unless the result outlasts them
- anything you are guessing at; only what the summaries actually say
- restatements of a whole summary. A fact is shorter than what it came from.

Give 0 to {max_facts}. An uneventful stretch genuinely yields none, and an
empty list is a better answer than a padded one.
Return only the JSON object."""


def _call_openrouter(api_key, model, messages):
    """Runs in a thread."""
    payload = {"model": model, "messages": messages}
    from world.model_params import of as _settings

    payload.update(_settings(model))
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode())
    return result["choices"][0]["message"]["content"]


def _parse_facts(content):
    """The facts out of a model response, however tidily it answered."""
    from world.model_json import parse_object

    data = parse_object(content)
    facts = []
    for item in (data.get("facts") or [])[:MAX_FACTS]:
        text = str(item).strip()
        if text and text not in facts:
            facts.append(text)
    return facts


def _account_for(bank):
    """
    Whoever pays for distilling this character's memories. Main thread.

    The world's creator, the same account that paid for every room in it.
    Falls back to any account with a key, so a character orphaned from its
    world by a move does not simply stop being thought about.
    """
    from evennia.objects.models import ObjectDB

    from world import memory

    owner = memory._owner_id(bank)
    if owner is not None:
        character = ObjectDB.objects.filter(id=owner).first()
        location = getattr(character, "location", None) if character else None
        world_root = location.db.world_root if location is not None else None
        creator = world_root.db.world_creator if world_root is not None else None
        if creator is not None and creator.db.openrouter_api_key:
            return creator

    from evennia.accounts.models import AccountDB

    for account in AccountDB.objects.all():
        if account.db.openrouter_api_key:
            return account
    return None


def distil(banks=None, on_done=None):
    """
    Async, fire-and-forget. Distil each character's summaries into facts.

    Works through the banks one at a time and stops the moment somebody starts
    playing again -- so a long queue costs a player nothing, it simply gets
    shorter over several quiet spells rather than one.
    """
    from world import memory

    queue = list(banks if banks is not None else memory.living_banks())
    tally = {"characters": 0, "facts": 0}

    def _next():
        from world.activity import quiet_enough_for_heavy_work

        if not queue:
            return _finish("done")
        if not quiet_enough_for_heavy_work():
            return _finish("interrupted; somebody is playing")

        bank = queue.pop(0)
        memory.distillable(bank, lambda summaries, through:
                           _got(bank, summaries, through))

    def _got(bank, summaries, through):
        if not summaries:
            return _next()

        account = _account_for(bank)
        if account is None:
            return _finish("no account with an API key")
        try:
            api_key = account.get_openrouter_key()
        except ValueError:
            return _finish("no API key")

        model = account.model_for("memory")
        messages = [
            {"role": "system",
             "content": _SYSTEM_PROMPT.replace("{max_facts}", str(MAX_FACTS))},
            {"role": "user",
             "content": ("What this character has been through lately:\n"
                         + "\n".join(f"- {s}" for s in summaries)
                         + "\n\nWhat do they know now?")},
        ]

        def _answered(content):
            try:
                facts = _parse_facts(content)
            except Exception:
                return _next()
            if not facts:
                # Nothing worth keeping, but the reading still counts: without
                # moving the mark these same summaries come back every pass.
                return memory.store_facts(bank, [], through,
                                          on_done=lambda _n: _next())
            tally["characters"] += 1
            tally["facts"] += len(facts)
            memory.store_facts(bank, facts, through,
                               on_done=lambda _n: _next())

        threads.deferToThread(
            _call_openrouter, api_key, model, messages
        ).addCallbacks(_answered, lambda _f: _next())

    def _finish(why):
        if tally["facts"]:
            logger.log_info(
                f"memory: distilled {tally['facts']} fact(s) from "
                f"{tally['characters']} character(s) ({why})"
            )
        if on_done:
            on_done(tally)

    _next()
