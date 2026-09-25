"""
Every lookup tool, by name, gathered from the modules that keep what each reads.

Phase 4 of docs/generator-tool-loops.md, §5. A lookup is defined beside the
register it reads -- `traits.lookup_tools` beside the trait register, and so on
-- for the reason `gear.prompt_block` sits beside gear: the shape asked for and
the shape read cannot drift apart. This module only collects them, so that a
generator or a character can be handed tools by name.

A tool is offered only where it can answer: the dictionary's tools with a
dictionary, a character's memory with a character. A toolbox leaves out
anything whose `available` says no, the way `_tools_for` leaves out a tool
whose choices would be empty.
"""

#: The modules that keep a register some model may want to look into.
MODULES = (
    "traits", "pronouns", "token_lists", "verbs", "lexicon", "commonsense",
    "rule_gen", "rulebooks", "kinds", "relations", "npc_gen", "zones", "goals",
    "actions", "memory", "rulecheck", "quests",
)


def all_tools():
    """{name: Tool} for every lookup there is."""
    import importlib

    found = {}
    for name in MODULES:
        module = importlib.import_module(f"world.{name}")
        for tool in module.lookup_tools():
            found[tool.name] = tool
    return found


def named(*names):
    """The lookups called these names, in that order; unknown names are skipped."""
    tools = all_tools()
    return [tools[name] for name in names if name in tools]
