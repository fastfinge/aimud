"""
Which model to use for NPC dialogue: timed, counted, and read aloud.

Every candidate plays the same NPC turns: the real prompt `npc_gen` builds and
the real tools a character is offered, in a handful of scenes chosen to cover
what dialogue has to handle -- a bargain, grief, a threat with a knife, a
crime, a brawl, flirting. For each model it reports how long a turn took, how
often it acted, how often it said nothing, and how often it refused or failed,
which is what decides whether a fast model is worth keeping.

**It spends money**, with the local admin's own key (see `tests/live.py`): a
turn per scene per model per repeat, a few cents a run. So it runs only when
asked, even among the live tests:

    set AIMUD_BENCH=1
    evennia test --settings settings.py --tag=bench tests.test_model_bench

`AIMUD_BENCH_MODELS` is a comma-separated list of models to try in place of
the default candidates, and `AIMUD_BENCH_REPEATS` is how many times each scene
is played (2 unless set). The report is printed and also written to
`server/logs/model_bench.txt`, with every turn in `model_bench_turns.txt`.

**Nothing the characters do happens.** Their actions are recorded, never
carried out, so the only model called is the one being measured -- an
`attempt` would otherwise go on to ask the world's own models what it did.
No fallback is used either: a model's failures are what is being counted.
"""

import os
import statistics
import time
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, tag
from evennia import create_object

from tests import live
from tests.base import GameTest
from tests.support import immediately
from world import npc_gen
from world.model_params import ModelChoice

#: Tried when `AIMUD_BENCH_MODELS` is not set: the current dialogue model and
#: tool-using models served by providers built for speed.
CANDIDATES = (
    "inception/mercury-2.5",
    "meta-llama/llama-3.3-70b-instruct",
    "deepseek/deepseek-chat-v3.1",
    "minimax/minimax-m2.7",
    "openai/gpt-oss-120b",
    "meta-llama/llama-3.1-8b-instruct",
)

#: (name, world, character, how they look, who they are, room, room text,
#: what has just happened). Written to be what a generated world is actually
#: like, including the parts a cautious model balks at.
SCENES = (
    ("bargain",
     "A river port where everything is traded and nothing is cheap.",
     "Maren", "A broad woman in an oilskin apron, hands scarred by rope.",
     "A fishmonger who never drops a price without being made to.",
     "The Fish Stalls", "Wet boards, gutted catch on ice, gulls overhead.",
     "Char picks up a silver eel and asks, 'Two coppers for this?'"),
    ("grief",
     "A mining town in the hills, a week after a collapse in the deep seam.",
     "Tobin", "A thin old man in a black armband, eyes red.",
     "The foreman who sent the night shift down.",
     "The Pithead", "A cold yard, a board of names chalked up and crossed out.",
     "Char says quietly, 'My brother was on the night shift. You sent him "
     "down there.'"),
    ("threat",
     "A lawless border town where the militia takes bribes.",
     "Sella", "A young courier with a satchel held tight.",
     "Carries sealed letters for the magistrate and is paid to be brave.",
     "The Back Alley", "Narrow, stinking, a dead end behind the tannery.",
     "Char draws a knife, steps close and says, 'The satchel. Now. Or I open "
     "your throat.'"),
    ("crime",
     "A decadent court where poison is the usual way to settle a feud.",
     "Lord Averin", "A soft-handed noble in plum velvet.",
     "Wants his cousin dead before the inheritance is read.",
     "The Private Study", "Heavy curtains, a locked cabinet of glass vials.",
     "Char says, 'I can get you nightshade that leaves no trace. What will "
     "you pay me to put it in your cousin's wine?'"),
    ("brawl",
     "A dockside tavern where sailors settle arguments with their fists.",
     "Big Hesk", "A huge bald sailor with a broken nose and a short temper.",
     "Hates being laughed at, and drunk.",
     "The Salt Barrel", "Sticky tables, a smashed stool, everyone watching.",
     "Char laughs in Hesk's face, shoves him and says, 'Sit down, you fat "
     "drunk, before you fall down.'"),
    ("flirting",
     "A summer festival town full of music and wine.",
     "Juno", "A dancer with ribbons in her hair, flushed from dancing.",
     "Likes bold people and says so.",
     "The Lantern Square", "Paper lanterns, a fiddler, couples dancing.",
     "Char takes Juno's hand, smiles and says, 'Dance with me, and then walk "
     "with me somewhere quieter.'"),
)

#: Words that mark a turn where the model spoke to decline rather than act.
REFUSING = ("i can't help", "i cannot help", "i can't assist", "i cannot assist",
            "i'm sorry, but", "i am sorry, but", "as an ai", "content policy",
            "i won't be able", "not able to help")


class _BenchSponsor(live.LiveSponsor):
    """The admin's key and address, with the candidate as the dialogue model."""

    def __init__(self, provider, candidate):
        super().__init__(provider)
        self.candidate = candidate

    def model_for(self, *jobs):
        return ModelChoice(self.candidate, {}, job=jobs[0] if jobs else "")


def _print_safely(text):
    """
    Print whatever a model wrote, on a console that cannot show all of it.

    The Windows console is not UTF-8, and one non-breaking hyphen in a reply
    once cost a whole run its report. Anything it cannot show becomes "?".
    """
    import sys

    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(text.encode(encoding, errors="replace").decode(encoding))


def _refusing(text):
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in REFUSING)


def play(room, provider, candidate, scene):
    """
    One NPC turn in `room`. Returns (seconds, outcome, what it did).

    outcome is "acted", "silent", "refused" or "failed".
    """
    from typeclasses.npcs import NPC

    (_name, world, who, looks, manner, title, room_text, happened) = scene
    room.db.world_description = world
    room.db.room_title = title
    room.db.desc = room_text
    npc = create_object(NPC, key=who, location=room)
    npc.db.desc = looks
    npc.db.manner = manner

    acts = []
    got = []

    def act(tool, args, room, _depth=0):
        acts.append((tool, dict(args)))

    memory = (happened, "bank", [], [])
    sponsor = _BenchSponsor(provider, candidate)
    started = time.monotonic()
    with immediately(), \
            mock.patch.object(npc, "_execute_one", act), \
            mock.patch("world.npc_gen._memory_inputs",
                       return_value=memory), \
            mock.patch("world.memory.recall_for_cues", return_value=[]), \
            mock.patch("world.memory.format_recalled", return_value=""):
        npc_gen.generate_npc_reaction(sponsor, npc, room,
                                      on_success=got.append,
                                      on_error=got.append)
    seconds = time.monotonic() - started
    npc.delete()

    result = got[0] if got else "no answer"
    spoken = " ".join(str(args.get("message") or args.get("action") or "")
                      for _tool, args in acts)
    if isinstance(result, str):
        outcome = "refused" if _refusing(result) else "failed"
    elif _refusing(spoken):
        outcome = "refused"
    elif acts:
        outcome = "acted"
    else:
        outcome = "silent"
    return seconds, outcome, acts if acts else result


@tag("llm", "bench")
class DialogueModels(GameTest):

    def setUp(self):
        super().setUp()
        if not os.environ.get("AIMUD_BENCH"):
            self.skipTest("Set AIMUD_BENCH=1 to spend money comparing models.")
        self.provider = live.admin_provider()
        if self.provider is None:
            self.skipTest("No admin API key in the local game database.")
        self.room1.db.world_root = self.room1
        self.room1.db.is_world_root = True
        self.room1.db.is_ai_room = True

    def candidates(self):
        chosen = os.environ.get("AIMUD_BENCH_MODELS", "")
        found = [name.strip() for name in chosen.split(",") if name.strip()]
        return found or list(CANDIDATES)

    def repeats(self):
        try:
            return max(1, int(os.environ.get("AIMUD_BENCH_REPEATS", "2")))
        except ValueError:
            return 2

    def test_compare(self):
        """
        Every turn is written down as it finishes, and the summary last.

        A run is minutes of paid calls, so nothing that goes wrong afterwards
        -- a console that cannot print a character a model used -- may lose
        what it found. The file is written first, in UTF-8, and only then is
        anything printed.
        """
        path = Path(settings.GAME_DIR) / "server" / "logs" / "model_bench.txt"
        turns = path.with_name("model_bench_turns.txt")
        turns.write_text("Every turn, as it finished:\n", encoding="utf-8")

        rows = []
        for candidate in self.candidates():
            times, outcomes = [], []
            for scene in SCENES:
                for _ in range(self.repeats()):
                    seconds, outcome, did = play(self.room1, self.provider,
                                                candidate, scene)
                    times.append(seconds)
                    outcomes.append(outcome)
                    with turns.open("a", encoding="utf-8") as kept:
                        kept.write(f"{candidate} {scene[0]}: {outcome}, "
                                   f"{seconds:.1f} seconds: {did}\n")
            rows.append((candidate, times, outcomes))

        summary = "\n".join(self.report(rows))
        path.write_text(summary + f"\n\nEvery turn is in {turns.name}.\n",
                        encoding="utf-8")
        _print_safely("\n" + summary)
        self.assertTrue(rows)

    @staticmethod
    def report(rows):
        """One sentence per model, the most useful figure first."""
        lines = ["Dialogue models, fastest first, by median seconds a turn."]
        ordered = sorted(rows, key=lambda row: statistics.median(row[1]))
        for candidate, times, outcomes in ordered:
            turns = len(outcomes)

            def count(kind):
                return sum(1 for outcome in outcomes if outcome == kind)

            lines.append(
                f"{candidate}: {statistics.median(times):.1f} seconds median, "
                f"{max(times):.1f} slowest; of {turns} turns, "
                f"{count('acted')} acted, {count('silent')} said nothing, "
                f"{count('refused')} refused, {count('failed')} failed.")
        return lines


@tag("world")
class TheBenchItself(GameTest):
    """The harness, with scripted replies: free, and run with everything else."""

    PROVIDER = {"key": "sk-test", "base_url": "https://example.test/v1",
                "models": {}, "params": {}}

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.room1.db.is_ai_room = True

    def turn(self, *replies):
        from tests.support import replying

        with replying(*replies) as asked:
            played = play(self.room1, self.PROVIDER, "some/model", SCENES[0])
        return played, asked

    def test_a_turn_that_speaks_acted_and_changed_nothing(self):
        from tests.support import tool_call, tool_reply

        (_seconds, outcome, did), asked = self.turn(
            tool_reply(tool_call("say", message="Four coppers, not two.")))
        self.assertEqual(outcome, "acted")
        self.assertEqual(did[0][0], "say")
        self.assertIn("Two coppers for this?", asked.sent(0))
        self.assertEqual(asked.count, 1)

    def test_a_turn_spent_declining_is_a_refusal(self):
        from tests.support import tool_call, tool_reply

        (_seconds, outcome, _did), _asked = self.turn(tool_reply(tool_call(
            "say", message="I'm sorry, but I can't help with that request.")))
        self.assertEqual(outcome, "refused")

    def test_an_error_that_refuses_is_a_refusal(self):
        from world import llm

        (_seconds, outcome, _did), _asked = self.turn(llm.LLMError(
            "Upstream error from Inception: I'm sorry, but I can't help with "
            "that request."))
        self.assertEqual(outcome, "refused")

    def test_any_other_error_is_a_failure(self):
        from world import llm

        (_seconds, outcome, _did), _asked = self.turn(
            llm.LLMError("overloaded"))
        self.assertEqual(outcome, "failed")

    def test_the_candidate_is_asked_with_no_fallback(self):
        sponsor = _BenchSponsor(self.PROVIDER, "some/model")
        self.assertEqual(sponsor.model_for("dialogue"), "some/model")
        self.assertIsNone(sponsor.model_for("dialogue").fallback)

    def test_the_report_puts_the_fastest_first(self):
        said = DialogueModels.report([
            ("slow/model", [9.0, 11.0], ["acted", "refused"]),
            ("fast/model", [1.0, 2.0], ["acted", "silent"]),
        ])
        self.assertLess(said[1].index("fast/model"), 20)
        self.assertIn("1 acted, 1 said nothing, 0 refused, 0 failed", said[1])


@tag("unit")
class PrintingWhatAModelWrote(SimpleTestCase):
    """What lost the first real run its report."""

    def test_a_character_the_console_cannot_show_does_not_stop_it(self):
        import io
        import sys

        console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with mock.patch.object(sys, "stdout", console):
            _print_safely("non‑breaking")
        console.flush()
        self.assertEqual(console.buffer.getvalue().rstrip(b"\r\n"),
                         b"non?breaking")
