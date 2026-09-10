"""
File-based help entries. These complements command-based help and help entries
added in the database using the `sethelp` command in-game.

Control where Evennia reads these entries with `settings.FILE_HELP_ENTRY_MODULES`,
which is a list of python-paths to modules to read.

A module like this should hold a global `HELP_ENTRY_DICTS` list, containing
dicts that each represent a help entry. If no `HELP_ENTRY_DICTS` variable is
given, all top-level variables that are dicts in the module are read as help
entries.

Each dict is on the form
::

    {'key': <str>,
     'text': <str>}``     # the actual help text. Can contain # subtopic sections
     'category': <str>,   # optional, otherwise settings.DEFAULT_HELP_CATEGORY
     'aliases': <list>,   # optional
     'locks': <str>       # optional, 'view' controls seeing in help index, 'read'
                          #           if the entry can be read. If 'view' is unset,
                          #           'read' is used for the index. If unset, everyone
                          #           can read/view the entry.

"""

HELP_ENTRY_DICTS = [
    # The one entry here that is about this game rather than about Evennia, and
    # it exists to be a door. Every word a world invents gets its own help
    # topic (see commands/help_cmds.py), but a player cannot look up a word
    # they have not met and the kinds are deliberately kept out of the index --
    # so something has to stand in the index and say what there is to ask for.
    {
        "key": "vocabulary",
        "aliases": ["words"],
        "category": "General",
        "text": """
            This world invents its own words as it runs, and keeps four sorts
            of them. Each of the four answers a different question about a
            thing, and typing the name of a group lists every word this world
            has put in it:

              |whelp kinds|n         what a thing |wis|n — bottle, chest, flyer
              |whelp affordances|n   what can be |wdone|n to one — read, burn, open
              |whelp conditions|n    what is |wtrue|n of one just now — empty, burning
              |wscore|n              what |wyou|n are measured by — composure, stamina

            And every word in them has an entry of its own, so |whelp
            bottle|n, |whelp burn|n, |whelp empty|n and |whelp composure|n all
            say what this world means by them.

            The four are worth telling apart, because they behave differently:

            A |wkind|n is settled once, by the first thing of that sort the
            world ever makes, and never revised. That is what makes trying
            things worth it — work out how to read a flyer and the world can
            read a pamphlet for nothing.

            An |waffordance|n is a verb, and it is the verb you type. It says
            what can be done |wto|n a thing and never what the thing does: a
            lantern affords |wlight|n because it can be lit.

            A |wcondition|n is what is true of something at the moment, and it
            changes. It is not part of a thing's name — a bottle is a bottle
            whether it is full or empty — so it is listed under the
            description when you look.

            A |wtrait|n is a figure rather than a yes or no, and it can be
            lent to you: armour, a weapon in hand, a fire in the room. |wscore|n
            says what each of yours stands at and how much of it is borrowed.

            No word does two of these jobs at once. A condition and a trait may
            never share one — both say what is true of you now, and two answers
            to one question is worse than neither — so |wwarm|n in any world is
            one or the other. The rest may share a root, because that is
            English working properly: a |wfire|n you can |wburn|n things in,
            holding a log that is |wburning|n.

            Every list is per world. Another world knows other words, and a new
            one knows almost none until somebody has played in it.
        """,
    },
    {
        "key": "evennia",
        "aliases": ["ev"],
        "category": "General",
        "locks": "read:perm(Developer)",
        "text": """
            Evennia is a MU-game server and framework written in Python. You can read more
            on https://www.evennia.com.

            # subtopics

            ## Installation

            You'll find installation instructions on https://www.evennia.com.

            ## Community

            There are many ways to get help and communicate with other devs!

            ### Discussions

            The Discussions forum is found at https://github.com/evennia/evennia/discussions.

            ### Discord

            There is also a discord channel for chatting - connect using the
            following link: https://discord.gg/AJJpcRUhtF

        """,
    },
]
