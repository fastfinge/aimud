"""
Tests, in three tiers, because two of them are free and one is not.

This game is mostly made of model calls, and a test that needs one costs money
and answers differently every time. That is why there have been no repeatable
tests here: everything worth checking looked like it needed a model, so nothing
was checked twice. Most of it does not.

Every test carries a tag saying which tier it is in, and the tag is what makes
the free ones safe to run in a batch, a hook or CI:

    unit    no database, no network, no Evennia objects. Pure functions.
    world   the Evennia database; still no network.
    llm     a real key and real money.

    evennia test --exclude-tag=llm .    everything free and deterministic
    evennia test --tag=unit .           the inner loop, seconds
    evennia test --tag=llm .            deliberate, costs money, needs a key

The tier is enforced as well as declared: a `unit` test inherits from Django's
`SimpleTestCase`, which refuses database access, so a test that quietly grows a
dependency on the database fails rather than slowing everything down. An `llm`
test skips itself when no key is configured, so a fresh checkout reports skips
instead of failures.

**The rule that keeps the paid tier small:** if a test can be written against a
recorded reply, it belongs in `world`. A real model is only needed to answer one
question -- whether it still replies in the shape the prompts ask for -- and that
question is asked about schemas and closed vocabularies, never about prose.
"""
