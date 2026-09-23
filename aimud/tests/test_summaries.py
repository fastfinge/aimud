"""
Summarising memories through the game's model rather than a local one.

Sleep was running a local CPU model: 5.7 CPU-hours on a live server in one
afternoon, never finishing, while a player waited four minutes for a room.
`world.summaries` routes it through OpenRouter like every other model job.

Nothing here needs an embedding stack, in keeping with `test_memory_shape`:
what is asserted is who pays, what is sent, and what a refusal does. The one
exception is `WhatMnemosyneIsToldToDo`, which asserts against the real
mnemosyne modules on purpose -- those attribute names are the whole integration
and an upgrade that renamed one would otherwise put the CPU back to work in
silence.
"""

from unittest import mock

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from tests.support import FakeSponsor, replying
from world import llm, preferences, summaries


@tag("unit")
class WhoseModelAnswers(SimpleTestCase):

    def complete(self, sponsor, model, *replies):
        with replying(*replies) as recorder:
            with summaries.paying_for(sponsor, model):
                said = summaries._complete(
                    "Summarise these.", max_tokens=512, temperature=0.3,
                    timeout=30)
        return said, recorder

    def test_the_paying_worlds_model_writes_the_summary(self):
        said, recorder = self.complete(FakeSponsor(), "cheap/model",
                                       "Bram mended the cart.")
        self.assertEqual(said, "Bram mended the cart.")
        self.assertIn("Summarise these.", recorder.sent(0))

    def test_a_bank_nobody_pays_for_is_not_summarised(self):
        said, recorder = self.complete(None, None, "never asked")
        self.assertIsNone(said)
        self.assertEqual(recorder.count, 0, "it asked anyway")

    def test_nor_is_one_whose_sponsor_chose_no_model(self):
        said, recorder = self.complete(FakeSponsor(), "", "never asked")
        self.assertIsNone(said)
        self.assertEqual(recorder.count, 0)

    def test_a_refusal_is_no_summary_rather_than_a_raise(self):
        """
        mnemosyne takes None as "no summary", and the rest of the pass goes
        on. Raising would abandon every bank after this one over one bad key.
        """
        said, _recorder = self.complete(FakeSponsor(), "cheap/model",
                                        llm.LLMError("no credit left"))
        self.assertIsNone(said)

    def test_an_empty_answer_is_no_summary_too(self):
        said, _recorder = self.complete(FakeSponsor(), "cheap/model", "")
        self.assertIsNone(said)

    def test_mnemosynes_own_model_override_is_ignored(self):
        """
        Which model answers for a job belongs to whoever pays -- that is what
        `settings models` is for -- not to an environment variable inside a
        dependency.
        """
        with replying("a summary") as recorder:
            with summaries.paying_for(FakeSponsor(), "cheap/model"):
                summaries._complete("Summarise.", max_tokens=512,
                                    temperature=0.3, timeout=30,
                                    provider="somebody", model="their/model")
        self.assertEqual(recorder.count, 1)


@tag("unit")
class NamingWhoPays(SimpleTestCase):

    def test_the_payer_is_put_back_afterwards(self):
        """
        One bank at a time, under `memory._lock` -- but a pass names a payer
        per bank, so leaving the last one set would bill the wrong world if
        anything ever summarised outside the loop.
        """
        self.assertIsNone(summaries._paying["sponsor"])
        with summaries.paying_for(FakeSponsor(), "cheap/model"):
            self.assertIsNotNone(summaries._paying["sponsor"])
        self.assertIsNone(summaries._paying["sponsor"])

    def test_and_put_back_even_when_sleeping_raises(self):
        with self.assertRaises(RuntimeError):
            with summaries.paying_for(FakeSponsor(), "cheap/model"):
                raise RuntimeError("the bank would not open")
        self.assertIsNone(summaries._paying["sponsor"])


@tag("world")
class WhoPaysForABank(GameTest):
    accounts = True

    def setUp(self):
        super().setUp()
        self.room1.db.is_world_root = True
        self.room1.db.world_root = self.room1

    def test_the_world_creator_pays_for_their_own_world(self):
        from world import sponsor as sponsor_mod

        self.account.db.openrouter_api_key = "sk-test"
        sponsor_mod.claim(self.room1, self.account)
        sponsor, model = summaries.payer_for(f"aimud-world-{self.room1.id}")
        self.assertEqual(sponsor.account, self.account)
        self.assertTrue(model)

    def test_a_world_whose_maker_has_gone_is_still_thought_about(self):
        """
        Any account with a key stands in. The alternative is memories that are
        never summarised again, and mnemosyne deletes what it never slept.
        """
        self.account.db.openrouter_api_key = "sk-test"
        sponsor, _model = summaries.payer_for("aimud-world-999999")
        self.assertEqual(sponsor.account, self.account)

    def test_a_game_with_no_key_anywhere_pays_for_nothing(self):
        self.account.db.openrouter_api_key = ""
        self.account2.db.openrouter_api_key = ""
        self.assertEqual(summaries.payer_for(f"aimud-world-{self.room1.id}"),
                         (None, None))

    def test_the_summaries_model_is_asked_for_before_the_memory_one(self):
        """
        Its own job: a bulk background summariser wants a cheap fast model,
        and `remember` is a player waiting on an answer. `memory` is named as
        the fallback so a game that set only that one still works.
        """
        self.account.db.openrouter_api_key = "sk-test"
        with mock.patch.object(type(self.account), "model_for") as chose:
            summaries.payer_for(f"aimud-world-{self.room1.id}")
        self.assertEqual(chose.call_args.args, ("summaries", "memory"))

    def test_and_it_is_a_job_somebody_can_choose(self):
        self.assertIn("summaries", dict(preferences.JOBS))

    def test_a_whole_pass_looks_for_the_stand_in_account_once(self):
        """
        Not once per bank. A world whose creator has gone falls through to
        any account with a key, and doing that in the loop scanned every
        account in the game once for every bank on disk.
        """
        self.account.db.openrouter_api_key = "sk-test"
        banks = [f"aimud-world-{n}" for n in range(900001, 900021)]
        with mock.patch.object(summaries, "_anybody_with_a_key",
                               return_value=self.account) as looked:
            payers = summaries.payers_for(banks)
        self.assertEqual(looked.call_count, 1)
        self.assertEqual(len(payers), len(banks))
        self.assertTrue(all(who is not None for who, _model in payers.values()))


@tag("unit")
class WhatMnemosyneIsToldToDo(SimpleTestCase):
    """
    Asserted against the real mnemosyne, because these attribute names *are*
    the integration. Its settings are module constants read from the
    environment at import, so `os.environ` set afterwards does nothing -- and
    its local fallback cannot be switched off by any setting at all.
    """

    def setUp(self):
        try:
            from mnemosyne.core import llm_backends, local_llm
        except Exception:
            self.skipTest("no mnemosyne installed")
        self.backends, self.local = llm_backends, local_llm
        self.before = (local_llm.HOST_LLM_ENABLED, local_llm.HOST_LLM_TIMEOUT,
                       local_llm.HOST_LLM_MODEL, local_llm.HOST_LLM_PROVIDER,
                       local_llm._load_llm,
                       llm_backends.get_host_llm_backend())
        self.addCleanup(self.restore)

    def restore(self):
        (self.local.HOST_LLM_ENABLED, self.local.HOST_LLM_TIMEOUT,
         self.local.HOST_LLM_MODEL, self.local.HOST_LLM_PROVIDER,
         self.local._load_llm, backend) = self.before
        self.backends.set_host_llm_backend(backend)

    def test_the_host_backend_is_switched_on_and_registered(self):
        self.assertTrue(summaries.install())
        self.assertTrue(self.local.HOST_LLM_ENABLED)
        self.assertTrue(summaries.installed())

    def test_the_local_model_can_no_longer_be_loaded(self):
        """
        The trap this closes: mnemosyne's documented precedence is that a
        failed host call falls *straight to the local model*, so without this
        one refused request would put the CPU back to work for twenty minutes.
        """
        summaries.install()
        self.assertIsNone(self.local._load_llm())
        self.assertIsNone(self.local._call_local_llm("summarise this"))

    def test_and_mnemosyne_still_has_the_hooks_this_relies_on(self):
        for name in ("HOST_LLM_ENABLED", "HOST_LLM_TIMEOUT", "_load_llm",
                     "_call_local_llm", "_try_host_llm"):
            self.assertTrue(hasattr(self.local, name), name)
        self.assertTrue(hasattr(self.backends, "set_host_llm_backend"))
        self.assertTrue(hasattr(self.backends, "CallableLLMBackend"))

    def test_installing_twice_changes_nothing(self):
        summaries.install()
        first = self.backends.get_host_llm_backend()
        summaries.install()
        self.assertEqual(getattr(first, "name", ""), summaries.BACKEND_NAME)
        self.assertTrue(summaries.installed())


@tag("unit")
class SleepingOneBankAtATime(SimpleTestCase):
    """
    How the pass behaves around the lock and around the player.

    Two faults, both measured on a live server. The lock was held for the
    whole pass -- and every recall and every write in the game takes the same
    lock, so all memory stalled behind however long every bank took together.
    And the pass at server start gave way to nobody: it fires when the game is
    empty, so every check for a quiet moment passes, and the player logging in
    ten seconds later waited behind it.

    `_consolidate_sync` is driven directly here with a stand-in backend. The
    real one needs an embedding stack, and none of what is asserted is about
    mnemosyne -- it is about the loop around it.
    """

    def setUp(self):
        from world import memory

        self.memory = memory
        self.slept = []

    def backend(self):
        """A mnemosyne stand-in that records which banks were slept."""
        slept = self.slept

        class Instance:
            def __init__(self, bank):
                self.bank = bank

            def sleep_all_sessions(self, force=False):
                slept.append(self.bank)
                return {"status": "slept", "bank": self.bank}

            def close(self):
                pass

        class Backend:
            Mnemosyne = Instance

        return Backend()

    def run_pass(self, banks, keep_going=None, payers=None):
        held = []

        def with_backend(action):
            # Records each turn of the lock, which is the thing under test.
            held.append("taken")
            return action(self.backend())

        with mock.patch.object(self.memory, "_with_backend", with_backend):
            done = self.memory._consolidate_sync(
                banks, payers=payers, keep_going=keep_going)
        return done, held

    def test_the_lock_is_taken_once_per_bank_not_once_per_pass(self):
        banks = ["aimud-world-1", "aimud-world-2", "aimud-world-3"]
        done, held = self.run_pass(banks)
        self.assertEqual(self.slept, banks)
        self.assertEqual(len(held), 3, "the whole pass held the lock at once")
        self.assertEqual(sorted(done), banks)

    def test_a_pass_stops_when_somebody_starts_playing(self):
        banks = [f"aimud-world-{n}" for n in range(1, 6)]
        answers = [True, True, False, True, True]

        done, _held = self.run_pass(banks, keep_going=lambda: answers.pop(0))
        self.assertEqual(self.slept, banks[:2])
        self.assertEqual(len(done), 2)

    def test_and_keeps_going_when_nobody_is(self):
        banks = ["aimud-world-1", "aimud-world-2"]
        done, _held = self.run_pass(banks, keep_going=lambda: True)
        self.assertEqual(len(done), 2)

    def test_one_bank_that_will_not_open_does_not_stop_the_rest(self):
        banks = ["aimud-world-1", "aimud-world-2", "aimud-world-3"]
        calls = {"n": 0}

        def with_backend(action):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("that file is locked")
            return action(self.backend())

        with mock.patch.object(self.memory, "_with_backend", with_backend):
            done = self.memory._consolidate_sync(banks)
        self.assertEqual(self.slept, ["aimud-world-1", "aimud-world-3"])
        self.assertEqual(sorted(done), ["aimud-world-1", "aimud-world-3"])

    def test_each_bank_is_slept_with_its_own_world_paying(self):
        banks = ["aimud-world-1", "aimud-world-2"]
        seen = []

        def with_backend(action):
            return action(self.backend())

        real = summaries.paying_for

        def watching(sponsor, model):
            seen.append(model)
            return real(sponsor, model)

        with mock.patch.object(self.memory, "_with_backend", with_backend), \
                mock.patch.object(summaries, "paying_for", watching):
            self.memory._consolidate_sync(banks, payers={
                "aimud-world-1": (FakeSponsor(), "one/model"),
                "aimud-world-2": (FakeSponsor(), "two/model"),
            })
        self.assertEqual(seen, ["one/model", "two/model"])

    def test_a_bank_with_no_payer_is_still_slept(self):
        """
        Everything sleep does besides summarising, it does without a model --
        and what it does includes exempting rows from deletion.
        """
        done, _held = self.run_pass(["aimud-world-1"], payers={})
        self.assertEqual(self.slept, ["aimud-world-1"])
        self.assertEqual(len(done), 1)
