"""
Asking a decision model a yes-or-no question, instead of a chat model.

Some of what this game asks a model is not a generation at all. "Could a
spaceship be in this cellar" and "can a player pick up that anvil" are single
bits, and until now each spent a whole chat completion to get one: a system
prompt, a tool schema, a four-round loop, a JSON tool call carrying a boolean
and a sentence -- and the sentence was thrown away at every one of the six
places that received it (`_reason`, underscored, in `look_take_cmds`).

A decision model answers exactly that shape. Send it state and typed
questions, get back a number per question and nothing else. There is no text
to parse, no tool to name, no round that can come back empty, and no reply
that is not an answer -- which is why `item_gen._judged` used to treat running
out of rounds as an error and no longer has a way to.

What it buys beyond the cost is a **threshold**. The existence prompt has
always said "be permissive -- deny only clear impossibilities", and that was a
word in a prompt with no way to tell whether it had been heard. It is now a
number in `ALLOW_EXISTENCE`, tuned where the cost of each kind of mistake is
known: a thing wrongly refused is a player told "you don't see any" about
something reasonable, and a thing wrongly allowed is one more object in a
room. Those are not equally bad, so the threshold is not 0.5.

The model is **pinned** rather than tracking `~typesafe/jev-latest`. Every
threshold here was chosen against one version's calibration, and a release
that shifted it would move every one of them at once, silently, in a direction
nobody would see until rooms started filling with nonsense.
"""

from world import llm

#: The decision model, pinned. See the note on pinning above.
JEV = "typesafe/jev-1.13"

#: The job a decision is recorded under in the ledger. The same word the
#: chat-model validator used, so the figures either side of this change are
#: about the same thing and can be compared.
JOB = "validation"

#: How sure the model has to be that a thing could be here, for it to be made.
#:
#: Low on purpose, and the number the old prompt was asking for in words. The
#: two mistakes are not equally bad: refusing something reasonable tells a
#: player "you don't see any glass here" in a kitchen, which reads as the game
#: being broken, while allowing something marginal leaves one more object in a
#: room, which reads as the world being generous. So the benefit of the doubt
#: is given, and only a thing the model puts below a quarter is refused.
#:
#: Measured against a damp medieval cellar, and the reason the exact value
#: matters less than it looks: there is nothing in the middle.
#:
#:     a barrel 0.99   an old lantern 0.94   a door handle 0.90
#:     a chipped mug 0.92   a coil of rope 0.92   a table leg 0.83
#:     a mounted stag's head 0.64
#:     ----- 0.25 -----
#:     a mobile phone 0.07   a spaceship 0.04   a fusion reactor 0.04
#:
#: The band from 0.07 to 0.64 is empty. Anywhere in it would decide these
#: cases the same way, so the threshold only ever speaks to a genuinely
#: marginal thing, which is what it should be for.
ALLOW_EXISTENCE = 0.25

#: How sure it has to be that a thing is part of a living body, for it to be
#: refused whatever else was decided.
#:
#: Even-handed, unlike the one above, because this rule is absolute rather
#: than permissive -- "never valid however plausible it sounds" -- and the
#: failure it exists to stop is a severed shoulder left lying on the floor.
#:
#: This is the number that shows why the two questions are asked separately
#: rather than as one. A body part in that cellar is *plausible* -- a shoulder
#: scores 0.73 for existence, a hand 0.89, hair 0.87 -- so every one of them
#: clears `ALLOW_EXISTENCE` comfortably and would be built. What stops them is
#: the second question, where they score 0.89, 0.81 and 0.92 against a severed
#: hand's 0.07 and a mounted stag's head's 0.04. Asked as a caveat on the
#: first answer, the rule was arguing against the model's own judgement in the
#: same breath; asked on its own it is not in competition with anything.
DENY_BODY_PART = 0.5

#: How sure it has to be that a thing can be picked up.
#:
#: Even-handed: a fixed feature that can be pocketed and a loose tool that
#: cannot are both plainly wrong to a player, and neither is the safer way to
#: be wrong.
ALLOW_TAKEABLE = 0.5


def noul(question, when_true, when_false):
    """
    A yes-or-no question, as the decisions API takes one.

    Both sides are described rather than only the one being asked about. A
    question with no `false` criterion leaves the model to infer the opposite
    of the `true` one, and the opposite of "plausible for this world and room"
    is not obviously "a clear impossibility" -- which is the whole distinction
    the existence check turns on.
    """
    return {"type": "noul", "instructions": question,
            "criteria": {"true": when_true, "false": when_false}}


def certainty(answers, name):
    """
    How sure the model was of a yes, for one `noul`, as a number from 0 to 1.

    A missing or unreadable answer is 0.0 rather than an error. Every caller
    here compares against a threshold, and an answer that cannot be read is
    one the threshold should not pass -- so a garbled reply refuses a thing
    rather than conjuring one.
    """
    try:
        value = float((answers[name] or {})["noul"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    if value != value:      # NaN, which fails every comparison below
        return 0.0
    return min(max(value, 0.0), 1.0)


def model_for(sponsor):
    """
    The decision model, carrying the job it is for.

    A `ModelChoice` rather than the bare string, so the ledger records what
    the call was for the way it does every other call. The sponsor's own model
    settings are deliberately not consulted: this is not a model anybody
    chooses, and it takes no sampling settings to choose for it.
    """
    from world.model_params import ModelChoice

    return ModelChoice(JEV, {}, job=JOB)


def ask(sponsor, state, questions, *, on_answers, on_error):
    """
    Async. Put questions to the decision model and hand back the answers.

    Goes through `llm.fetch`, so it costs nobody on the reactor a wait and a
    test's `immediately()` runs the whole thing before this returns -- the
    same contract every generator in this game already has.

    `on_error` is given words, not a Failure, because that is what the error
    path of every caller takes.
    """
    try:
        sponsor.key()          # refuse early rather than mid-request
    except ValueError as refused:
        on_error(str(refused))
        return

    llm.fetch(llm.decide, sponsor, model_for(sponsor), state, questions,
              on_success=on_answers,
              on_error=lambda failure: on_error(failure.getErrorMessage()))
