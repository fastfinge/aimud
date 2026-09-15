## Bad Ideas and Why ##

This is the graveyard where bad ideas go to die, with the reason we decided they were bad, so we don't have them again.

* Jinja2 (or any general-purpose templating language) for in-game text and tokens: it is a programming language, with loops, conditionals, filters and attribute access to Python objects. Letting models or players author it is code written from inside the game, which basic-principles.md forbids, and its sandbox has a history of escapes. Text in AIMud needs substitution, agreement and grounding in world state, not logic; logic belongs in rules. The token grammar in tokens-and-phrases.md is deliberately limited to slots, calls and a closed table of fields, with no conditionals or loops, for this reason.