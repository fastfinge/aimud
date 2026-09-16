"""
The test runner: Evennia's own, with two things the suite cannot afford.

Both are per-test costs the game pays for reasons that have nothing to do with
the game, and between them they were most of the wall clock. Neither changes
what a test asserts.

**Passwords are not hashed for real.** `EvenniaTest.setUp` creates two accounts
before every single test method, and creating an account hashes a password --
PBKDF2, a million rounds, deliberately slow, because a password database that
is fast to hash is a password database that is fast to crack. None of that is
worth anything against a fixture whose password is "testpassword" and which is
thrown away microseconds later. So while the suite runs, and only while the
suite runs, hashing is MD5. The override lives here rather than in
`settings.py` so that there is no arrangement of settings, secret or otherwise,
under which a real server stores a real password this way.

**The corpus is frozen before the collector can see it.** Evennia's `tearDown`
calls `flush_cache()`, which ends in `gc.collect()` -- a full collection after
every test, to reap the idmapper's caches. WordNet's indices are about 370,000
tracked containers that live for the whole run and are never garbage, and a
full collection walks all of them: 130ms a test, spent proving that a
dictionary somebody will need again is still reachable. `gc.freeze()` moves
what already exists into the permanent generation, which collection skips.
Objects a test makes afterwards are new, so they are still collected as ever
and `flush_cache` still does its job.

The corpus is warmed first, deliberately. Freezing before it loads would freeze
nothing that matters, and the load has to happen at some point anyway -- better
once, here, than inside whichever test reached for a word first.
"""

import gc

from django.test.utils import override_settings
from evennia.server.tests.testrunner import EvenniaTestSuiteRunner

#: Fast, and worthless for anything but a fixture. See the module docstring.
_TEST_PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


class Runner(EvenniaTestSuiteRunner):
    """Evennia's runner, with the suite's two standing costs taken out."""

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        # `override_settings`, rather than assigning to `settings`, because
        # Django caches the hashers it built and only clears that cache on the
        # `setting_changed` signal -- which a bare assignment does not send.
        self._hashers = override_settings(PASSWORD_HASHERS=_TEST_PASSWORD_HASHERS)
        self._hashers.enable()

    def teardown_test_environment(self, **kwargs):
        self._hashers.disable()
        super().teardown_test_environment(**kwargs)

    def setup_databases(self, **kwargs):
        # After the database, so that the freeze covers everything the run
        # sets up once: the corpus, the migrations, the typeclass machinery.
        config = super().setup_databases(**kwargs)

        from world import lexicon

        lexicon.warm()
        gc.collect()
        gc.freeze()
        return config
