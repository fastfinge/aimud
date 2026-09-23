"""
Summarising memories against the real service and the real mnemosyne.

`test_summaries` asserts who pays and what is sent, against a fake. This is
the half that cannot be faked: that mnemosyne actually consults the backend
this game registers, that a summary comes back through OpenRouter, and --
the part that matters most -- that nothing reaches llama.cpp on the way.

The local path is the whole reason this exists. Sleep was summarising on a
local CPU model: 5.7 CPU-hours on a live server in one afternoon, never
finishing, while a player waited four minutes for a room to build. A mnemosyne
upgrade that renamed one hook would put it straight back, silently, and these
are what would say so.
"""

from django.test import SimpleTestCase, tag

from tests import live
from world import summaries

#: A short run of events, the shape sleep is given.
MEMORIES = [
    "Bram the wheelwright complained that the cart's axle was cracked.",
    "You gave Bram a length of iron banding from the storeroom.",
    "Bram fitted the banding and the cart rolled without the squeal.",
    "Bram said he owed you a favour and would not forget it.",
]


@tag("llm")
class SummarisingForReal(SimpleTestCase):

    def setUp(self):
        try:
            from mnemosyne.core import llm_backends, local_llm
        except Exception:
            self.skipTest("no mnemosyne installed")
        self.local, self.backends = local_llm, llm_backends
        self.sponsor = live.live_sponsor(self)
        self.model = self.sponsor.model_for(summaries.JOB, "memory")

        self.before = (local_llm.HOST_LLM_ENABLED, local_llm.HOST_LLM_TIMEOUT,
                       local_llm.HOST_LLM_MODEL, local_llm.HOST_LLM_PROVIDER,
                       local_llm._load_llm,
                       llm_backends.get_host_llm_backend())
        self.addCleanup(self.restore)
        summaries.install()

        #: Fires if anything asks for the local model. Installed *over* the
        #: stub `install` leaves, so it reports the reach rather than only the
        #: refusal -- and returns None, so no CPU is spent either way.
        self.reached = []
        local_llm._load_llm = lambda: (self.reached.append("local"), None)[1]

    def restore(self):
        (self.local.HOST_LLM_ENABLED, self.local.HOST_LLM_TIMEOUT,
         self.local.HOST_LLM_MODEL, self.local.HOST_LLM_PROVIDER,
         self.local._load_llm, backend) = self.before
        self.backends.set_host_llm_backend(backend)

    def summarise(self, sponsor, model):
        with summaries.paying_for(sponsor, model):
            return self.local.summarize_memories(MEMORIES, source="char-1")

    def test_a_summary_comes_back_through_the_games_own_model(self):
        summary = self.summarise(self.sponsor, self.model)
        self.assertTrue(summary, "no summary came back")
        self.assertIn("bram", summary.lower())

    def test_and_nothing_reaches_the_local_model(self):
        """The one that matters. A pass that touches llama.cpp is the bug."""
        self.summarise(self.sponsor, self.model)
        self.assertEqual(self.reached, [], "it went to the CPU after all")

    def test_a_bank_nobody_pays_for_is_declined_and_not_computed(self):
        """
        mnemosyne's precedence sends a failed host call *straight to the local
        model*, and no setting turns that off -- so `install` stubs the loader.
        Here the reach is visible and the answer is still nothing, which is
        the degradation `world.memory` promises.
        """
        self.assertIsNone(self.summarise(None, None))

    def test_the_stub_install_leaves_is_what_declines_it(self):
        """
        With the tripwire taken off, so what answers is the stub `install`
        leaves behind rather than this test's own. That stub is the only thing
        standing between a refused summary and twenty minutes of CPU.
        """
        summaries.install()             # replaces the tripwire with the stub
        self.assertIsNone(self.local._load_llm())
        self.assertIsNone(self.summarise(None, None))
