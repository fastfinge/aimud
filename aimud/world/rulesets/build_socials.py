"""
Write `socials.json` from the table below.

This is a developer's tool, not part of the game, the way
`world/sounds/rebuild.py` is: the table is the source and the JSON is what
ships, because a ruleset is data and never code (`world/rulesets.py`). Run it
from the repo root after changing the table:

    python aimud/world/rulesets/build_socials.py

**What a social is here.** A verb nothing needs permission for, which changes
nothing and says one sentence: smiling, nodding, bowing. Every world used to
pay a model to work out what to print the first time anybody smiled, and
every world printed something a little different. Each social below becomes:

* an action, declared with its ways of saying it -- alone, and with
  somebody -- and `admits_all`, so no world asks a model whether a person can
  be smiled at;
* a carry-out rule for each way, guarded by which roles were named, whose
  `report` is the sentence. A report is rendered for each viewer, so one
  sentence reads "You smile at Bob." to you, "Alice smiles at you." to Bob
  and "Alice smiles at Bob." to everybody else, and no model is asked.

A world's own rule about one of these verbs beats the ruleset's at the same
scope (`rulebooks.rank`), so a world where kissing breaks a curse says so
with one rule and loses nothing.

**Where the list came from.** Which socials a MUD wants is a question
CoffeeMud's `resources/socials.txt` (Apache 2.0, github.com/bozimmerman/
CoffeeMud) has answered for decades, and this list was chosen from it. Every
sentence was written anew in a plain voice, for any world: nothing crude,
nothing about the game the player is in, nothing that is an attack, and no
verb that names an ordinary act a world will want to mean something real by
-- shaking a bottle, rolling a die, kneeling, running.

**The table.** One row per social:

    verb, kind, means, alone, with somebody[, roles]

`kind` is how near somebody has to be: "sight" for what can be done across
a room, "touch" for what needs reaching, "alone" for a social that takes
nobody. `alone` and `with somebody` are what follows the actor -- written
"$pconj(smile) at {who}." -- and `{who}` becomes whichever role was named.
`roles` is which parts of a sentence name somebody, by default "smile at
Bob" (target) and "smile Bob" (direct); "agree with Bob" names its somebody
with "with", which the parser calls the instrument.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

#: The two ways somebody is usually named: "smile at Bob", "hug Bob".
BOTH = ("target", "direct")
WITH = ("instrument", "direct")

SIGHT, TOUCH, ALONE = "sight", "touch", "alone"

SOCIALS = [
    # Faces.
    ("smile", SIGHT, "to smile", "$pconj(smile).",
     "$pconj(smile) at {who}."),
    ("grin", SIGHT, "to grin", "$pconj(grin).", "$pconj(grin) at {who}."),
    ("beam", SIGHT, "to smile broadly", "$pconj(beam).",
     "$pconj(beam) at {who}."),
    ("smirk", SIGHT, "to smirk", "$pconj(smirk).",
     "$pconj(smirk) at {who}."),
    ("wink", SIGHT, "to wink", "$pconj(wink).", "$pconj(wink) at {who}."),
    ("frown", SIGHT, "to frown", "$pconj(frown).",
     "$pconj(frown) at {who}."),
    ("scowl", SIGHT, "to scowl", "$pconj(scowl).",
     "$pconj(scowl) at {who}."),
    ("glare", SIGHT, "to glare", "$pconj(glare) at nothing in particular.",
     "$pconj(glare) at {who}."),
    ("stare", SIGHT, "to stare", "$pconj(stare) into space.",
     "$pconj(stare) at {who}."),
    ("peer", SIGHT, "to look closely", "$pconj(peer) around.",
     "$pconj(peer) at {who}."),
    ("blink", SIGHT, "to blink", "$pconj(blink).",
     "$pconj(blink) at {who}."),
    ("pout", SIGHT, "to pout", "$pconj(pout).", "$pconj(pout) at {who}."),
    ("sneer", SIGHT, "to sneer", "$pconj(sneer).",
     "$pconj(sneer) at {who}."),
    ("grimace", SIGHT, "to grimace", "$pconj(grimace).",
     "$pconj(grimace) at {who}."),
    ("eye", SIGHT, "to look at warily", "$pconj(look) around warily.",
     "$pconj(eye) {who} warily."),
    ("eyeroll", SIGHT, "to roll one's eyes", "$pconj(roll) {actor.adjective} "
     "eyes.", "$pconj(roll) {actor.adjective} eyes at {who}."),
    ("eyebrow", SIGHT, "to raise an eyebrow", "$pconj(raise) an eyebrow.",
     "$pconj(raise) an eyebrow at {who}."),
    ("headshake", SIGHT, "to shake one's head",
     "$pconj(shake) {actor.adjective} head.",
     "$pconj(shake) {actor.adjective} head at {who}."),
    ("blush", ALONE, "to blush", "$pconj(blush).", None),
    ("innocent", ALONE, "to look innocent", "$pconj(look) innocent.", None),
    ("facepalm", ALONE, "to put one's face in one's hand",
     "$pconj(put) {actor.adjective} face in {actor.adjective} hand.", None),

    # Laughter and its relations.
    ("laugh", SIGHT, "to laugh", "$pconj(laugh).",
     "$pconj(laugh) at {who}."),
    ("giggle", SIGHT, "to giggle", "$pconj(giggle).",
     "$pconj(giggle) at {who}."),
    ("chuckle", SIGHT, "to chuckle", "$pconj(chuckle).",
     "$pconj(chuckle) at {who}."),
    ("cackle", SIGHT, "to cackle", "$pconj(cackle).",
     "$pconj(cackle) at {who}."),
    ("snicker", SIGHT, "to snicker", "$pconj(snicker).",
     "$pconj(snicker) at {who}."),
    ("chortle", ALONE, "to chortle", "$pconj(chortle).", None),
    ("guffaw", ALONE, "to laugh loudly", "$pconj(guffaw).", None),
    ("snort", ALONE, "to snort", "$pconj(snort).", None),

    # Greeting, parting and manners.
    ("wave", SIGHT, "to wave", "$pconj(wave).", "$pconj(wave) at {who}."),
    ("nod", SIGHT, "to nod", "$pconj(nod).", "$pconj(nod) to {who}."),
    ("bow", SIGHT, "to bow", "$pconj(bow).", "$pconj(bow) to {who}."),
    ("curtsey", SIGHT, "to curtsey", "$pconj(curtsey).",
     "$pconj(curtsey) to {who}."),
    ("salute", SIGHT, "to salute", "$pconj(salute).", "$pconj(salute) {who}."),
    ("greet", SIGHT, "to greet", "$pconj(greet) everyone.",
     "$pconj(greet) {who}."),
    ("hail", SIGHT, "to call a greeting", "$pconj(call) out a greeting.",
     "$pconj(hail) {who}."),
    ("welcome", SIGHT, "to welcome", "$pconj(welcome) everyone.",
     "$pconj(welcome) {who}."),
    ("farewell", SIGHT, "to bid farewell", "$pconj(bid) everyone farewell.",
     "$pconj(bid) {who} farewell."),
    ("goodnight", SIGHT, "to wish goodnight",
     "$pconj(wish) everyone a good night.",
     "$pconj(wish) {who} a good night."),
    ("thank", SIGHT, "to thank", "$pconj(thank) everyone.",
     "$pconj(thank) {who}."),
    ("apologize", SIGHT, "to apologise", "$pconj(apologise).",
     "$pconj(apologise) to {who}."),
    ("beckon", SIGHT, "to beckon", "$pconj(beckon).",
     "$pconj(beckon) to {who}."),

    # Agreeing, and not.
    ("agree", SIGHT, "to agree", "$pconj(agree).",
     "$pconj(agree) with {who}.", WITH),
    ("disagree", SIGHT, "to disagree", "$pconj(disagree).",
     "$pconj(disagree) with {who}.", WITH),
    ("shrug", SIGHT, "to shrug", "$pconj(shrug).", "$pconj(shrug) at {who}."),
    ("sigh", SIGHT, "to sigh", "$pconj(sigh).", "$pconj(sigh) at {who}."),
    ("tsk", SIGHT, "to click one's tongue", "$pconj(click) {actor.adjective} "
     "tongue.", "$pconj(click) {actor.adjective} tongue at {who}."),
    ("raspberry", SIGHT, "to blow a raspberry", "$pconj(blow) a raspberry.",
     "$pconj(blow) a raspberry at {who}."),
    ("boggle", ALONE, "to be astonished", "$pconj(boggle) at the very idea.",
     None),

    # Praise, blame and asking.
    ("applaud", SIGHT, "to applaud", "$pconj(applaud).",
     "$pconj(applaud) {who}."),
    ("clap", SIGHT, "to clap", "$pconj(clap) {actor.adjective} hands.",
     "$pconj(clap) for {who}."),
    ("cheer", SIGHT, "to cheer", "$pconj(cheer).", "$pconj(cheer) for {who}."),
    ("congratulate", SIGHT, "to congratulate", "$pconj(offer) "
     "congratulations all round.", "$pconj(congratulate) {who}."),
    ("praise", SIGHT, "to praise", "$pconj(sing) everyone's praises.",
     "$pconj(praise) {who}."),
    ("compliment", SIGHT, "to compliment", "$pconj(pay) a compliment to "
     "nobody in particular.", "$pconj(compliment) {who}."),
    ("encourage", SIGHT, "to encourage", "$pconj(offer) a few words of "
     "encouragement.", "$pconj(encourage) {who}."),
    ("accuse", SIGHT, "to look accusingly",
     "$pconj(look) around accusingly.", "$pconj(look) accusingly at {who}."),
    ("blame", SIGHT, "to blame", "$pconj(look) for somebody to blame.",
     "$pconj(blame) {who}."),
    ("tease", SIGHT, "to tease", "$pconj(look) ready to tease somebody.",
     "$pconj(tease) {who}."),
    ("ignore", SIGHT, "to ignore", "$pconj(ignore) everyone.",
     "$pconj(ignore) {who}."),
    ("beg", SIGHT, "to beg", "$pconj(beg).", "$pconj(beg) {who}."),
    ("plead", SIGHT, "to plead", "$pconj(plead).",
     "$pconj(plead) with {who}.", WITH),
    ("grovel", SIGHT, "to grovel", "$pconj(grovel).",
     "$pconj(grovel) at {who}'s feet."),
    ("worship", SIGHT, "to worship", "$pconj(bow) down in worship.",
     "$pconj(worship) {who}."),
    ("pray", SIGHT, "to pray", "$pconj(pray).", "$pconj(pray) for {who}."),
    ("bless", SIGHT, "to give a blessing", "$pconj(give) a blessing.",
     "$pconj(bless) {who}."),
    ("shoo", SIGHT, "to shoo away", "$pconj(make) shooing motions.",
     "$pconj(shoo) {who} away."),
    ("hush", SIGHT, "to ask for quiet", "$pconj(ask) for quiet.",
     "$pconj(hush) {who}."),
    ("point", SIGHT, "to point", "$pconj(point) at nothing in particular.",
     "$pconj(point) at {who}."),
    ("gesture", SIGHT, "to gesture", "$pconj(gesture) vaguely.",
     "$pconj(gesture) at {who}."),
    ("marvel", SIGHT, "to marvel", "$pconj(marvel).",
     "$pconj(marvel) at {who}."),
    ("gasp", SIGHT, "to gasp", "$pconj(gasp).", "$pconj(gasp) at {who}."),

    # Touch.
    ("hug", TOUCH, "to hug", "$pconj(look) like {actor.subject} "
     "$pconj(need) a hug.", "$pconj(hug) {who}."),
    ("cuddle", TOUCH, "to cuddle", "$pconj(look) for somebody to cuddle.",
     "$pconj(cuddle) {who}."),
    ("snuggle", TOUCH, "to snuggle", "$pconj(snuggle) up.",
     "$pconj(snuggle) up to {who}."),
    ("embrace", TOUCH, "to embrace", "$pconj(open) {actor.adjective} arms.",
     "$pconj(embrace) {who}."),
    ("kiss", TOUCH, "to kiss", "$pconj(blow) a kiss.", "$pconj(kiss) {who}."),
    ("peck", TOUCH, "to kiss lightly", "$pconj(pucker) up.",
     "$pconj(give) {who} a peck on the cheek."),
    ("smooch", TOUCH, "to kiss noisily", "$pconj(make) smoothing noises.",
     "$pconj(give) {who} a noisy smooch."),
    ("nuzzle", TOUCH, "to nuzzle", "$pconj(look) for somebody to nuzzle.",
     "$pconj(nuzzle) {who}."),
    ("pat", TOUCH, "to pat", "$pconj(pat) {actor.adjective} pockets.",
     "$pconj(pat) {who} on the back."),
    ("pet", TOUCH, "to pet", "$pconj(look) for something to pet.",
     "$pconj(pet) {who}."),
    ("poke", TOUCH, "to poke", "$pconj(poke) at the air.",
     "$pconj(poke) {who}."),
    ("nudge", TOUCH, "to nudge", "$pconj(look) for somebody to nudge.",
     "$pconj(nudge) {who}."),
    ("pinch", TOUCH, "to pinch", "$pconj(pinch) {actor.reflexive} to be sure "
     "this is real.", "$pconj(pinch) {who}."),
    ("tickle", TOUCH, "to tickle", "$pconj(wiggle) {actor.adjective} fingers "
     "menacingly.", "$pconj(tickle) {who}."),
    ("noogie", TOUCH, "to give a noogie", "$pconj(look) for a head to give a "
     "noogie to.", "$pconj(give) {who} a noogie."),
    ("ruffle", TOUCH, "to ruffle someone's hair",
     "$pconj(run) a hand through {actor.adjective} hair.",
     "$pconj(ruffle) {who}'s hair."),
    ("highfive", TOUCH, "to give a high five", "$pconj(hold) up a hand for "
     "a high five.", "$pconj(give) {who} a high five."),
    ("handshake", TOUCH, "to shake hands", "$pconj(offer) a hand to shake.",
     "$pconj(shake) {who}'s hand."),
    ("comfort", TOUCH, "to comfort", "$pconj(look) in need of comfort.",
     "$pconj(comfort) {who}."),
    ("console", SIGHT, "to console", "$pconj(offer) a few kind words.",
     "$pconj(console) {who}."),
    ("dance", TOUCH, "to dance", "$pconj(dance).",
     "$pconj(dance) with {who}.", WITH),

    # Voices that are not words.
    ("growl", SIGHT, "to growl", "$pconj(growl).", "$pconj(growl) at {who}."),
    ("snarl", SIGHT, "to snarl", "$pconj(snarl).", "$pconj(snarl) at {who}."),
    ("whistle", SIGHT, "to whistle", "$pconj(whistle) a little tune.",
     "$pconj(whistle) at {who}."),
    ("sing", SIGHT, "to sing", "$pconj(sing) a few bars of a song.",
     "$pconj(sing) to {who}."),
    ("hum", ALONE, "to hum", "$pconj(hum) a tune.", None),
    ("yodel", ALONE, "to yodel", "$pconj(yodel).", None),
    ("howl", ALONE, "to howl", "$pconj(howl).", None),
    ("roar", ALONE, "to roar", "$pconj(roar).", None),
    ("purr", ALONE, "to purr", "$pconj(purr).", None),
    ("yowl", ALONE, "to yowl", "$pconj(yowl).", None),
    ("groan", ALONE, "to groan", "$pconj(groan).", None),
    ("moan", ALONE, "to moan", "$pconj(moan).", None),
    ("grumble", ALONE, "to grumble", "$pconj(grumble).", None),
    ("grunt", ALONE, "to grunt", "$pconj(grunt).", None),
    ("mutter", ALONE, "to mutter", "$pconj(mutter) under "
     "{actor.adjective} breath.", None),
    ("mumble", ALONE, "to mumble", "$pconj(mumble) something nobody "
     "catches.", None),
    ("whine", ALONE, "to whine", "$pconj(whine).", None),
    ("whimper", ALONE, "to whimper", "$pconj(whimper).", None),
    ("scream", ALONE, "to scream", "$pconj(scream).", None),
    ("shriek", ALONE, "to shriek", "$pconj(shriek).", None),
    ("squeal", ALONE, "to squeal", "$pconj(squeal).", None),

    # The body, unbidden.
    ("yawn", ALONE, "to yawn", "$pconj(yawn).", None),
    ("sneeze", ALONE, "to sneeze", "$pconj(sneeze).", None),
    ("cough", ALONE, "to cough", "$pconj(cough).", None),
    ("hiccup", ALONE, "to hiccup", "$pconj(hiccup).", None),
    ("burp", ALONE, "to burp", "$pconj(burp).", None),
    ("sniffle", ALONE, "to sniffle", "$pconj(sniffle).", None),
    ("snore", ALONE, "to snore", "$pconj(snore) loudly.", None),
    ("pant", ALONE, "to pant", "$pconj(pant).", None),
    ("drool", ALONE, "to drool", "$pconj(drool).", None),
    ("shiver", ALONE, "to shiver", "$pconj(shiver).", None),
    ("shudder", ALONE, "to shudder", "$pconj(shudder).", None),
    ("tremble", ALONE, "to tremble", "$pconj(tremble).", None),
    ("swoon", ALONE, "to swoon", "$pconj(swoon).", None),

    # Feelings.
    ("cry", ALONE, "to cry", "$pconj(cry).", None),
    ("sob", ALONE, "to sob", "$pconj(sob).", None),
    ("weep", ALONE, "to weep", "$pconj(weep).", None),
    ("sulk", ALONE, "to sulk", "$pconj(sulk).", None),
    ("fume", ALONE, "to fume", "$pconj(fume) quietly.", None),
    ("wince", ALONE, "to wince", "$pconj(wince).", None),
    ("flinch", ALONE, "to flinch", "$pconj(flinch).", None),
    ("cringe", ALONE, "to cringe", "$pconj(cringe).", None),
    ("cower", ALONE, "to cower", "$pconj(cower).", None),
    ("fidget", ALONE, "to fidget", "$pconj(fidget).", None),
    ("squirm", ALONE, "to squirm", "$pconj(squirm).", None),
    ("twiddle", ALONE, "to twiddle one's thumbs",
     "$pconj(twiddle) {actor.adjective} thumbs.", None),
    ("flex", ALONE, "to flex", "$pconj(flex) {actor.adjective} muscles.",
     None),

    # Thought.
    ("ponder", ALONE, "to ponder", "$pconj(ponder).", None),
    ("wonder", ALONE, "to wonder", "$pconj(wonder) aloud.", None),
    ("daydream", ALONE, "to daydream", "$pconj(drift) off into a daydream.",
     None),
    ("contemplate", ALONE, "to contemplate",
     "$pconj(contemplate) the nature of things.", None),
    ("mull", ALONE, "to think something over", "$pconj(mull) it over.",
     None),

    # Moving about for the joy of it.
    ("bounce", ALONE, "to bounce", "$pconj(bounce) on {actor.adjective} "
     "toes.", None),
    ("twirl", ALONE, "to twirl", "$pconj(twirl) around.", None),
    ("jig", ALONE, "to dance a jig", "$pconj(dance) a little jig.", None),
    ("prance", ALONE, "to prance", "$pconj(prance) about.", None),
    ("strut", ALONE, "to strut", "$pconj(strut) about.", None),
    ("frolic", ALONE, "to frolic", "$pconj(frolic).", None),
    ("stomp", ALONE, "to stomp", "$pconj(stomp) {actor.adjective} foot.",
     None),
    ("wiggle", ALONE, "to wiggle", "$pconj(wiggle).", None),
]

#: How near a role must be, for each kind of social.
ACCESS = {SIGHT: "visible", TOUCH: "touchable"}


def _sentence(tail, who=None):
    """`{actor} ` and the tail, with `{who}` made the role named."""
    text = "{actor} " + tail
    if who:
        text = text.replace("{who}", "{" + who + "}")
    return text


def _named(role, named):
    """A guard that somebody was, or was not, named as this role."""
    return {"subject": role, "unbound": not named}


def build():
    """The ruleset, as a dict."""
    actions, rules = [], []
    for row in SOCIALS:
        verb, kind, means, alone, with_somebody = row[:5]
        roles = row[5] if len(row) > 5 else BOTH
        declared = {"action": verb, "means": means, "admits_all": True}
        if kind == ALONE:
            declared["applies_to"] = []
            declared["shapes"] = [[]]
            actions.append(declared)
            rules.append({
                "name": f"{verb}, said alone",
                "phase": "carry_out", "action": verb,
                "scope": {"world": True}, "about": "actor",
                "effects": [{"type": "narrate"}],
                "report": _sentence(alone)})
            continue

        declared["applies_to"] = [{"role": role, "access": ACCESS[kind],
                                   "optional": True} for role in roles]
        declared["shapes"] = [[]] + [[role] for role in roles]
        actions.append(declared)
        rules.append({
            "name": f"{verb}, said alone",
            "phase": "carry_out", "action": verb,
            "scope": {"world": True}, "about": "actor",
            "when": [_named(role, False) for role in roles],
            "effects": [{"type": "narrate"}],
            "report": _sentence(alone)})
        for role in roles:
            rules.append({
                "name": f"{verb}, with somebody named as the {role}",
                "phase": "carry_out", "action": verb,
                "scope": {"world": True}, "about": role,
                "when": [_named(role, True)],
                "effects": [{"type": "narrate"}],
                "report": _sentence(with_somebody, role)})

    return {
        "name": "socials",
        "title": "Socials",
        "version": 1,
        "default": False,
        "means": "Smiling, nodding, bowing and a hundred and fifty more: "
                 "things people do that change nothing and say one "
                 "sentence, ready made, so nobody pays a model to find out "
                 "what a smile looks like.",
        "requires": ["default"],
        "conflicts": [],
        "actions": actions,
        "rules": rules,
    }


def main():
    path = os.path.join(HERE, "socials.json")
    with open(path, "w", encoding="utf-8", newline="\n") as out:
        json.dump(build(), out, indent=2, ensure_ascii=False)
        out.write("\n")
    print(f"{len(SOCIALS)} socials written to {path}")


if __name__ == "__main__":
    main()
