r"""
Evennia settings file.

The available options are found in the default settings file found
here:

https://www.evennia.com/docs/latest/Setup/Settings-Default.html

Remember:

Don't copy more from the default file than you actually intend to
change; this will make sure that you don't overload upstream updates
unnecessarily.

When changing a setting requiring a file system path (like
path/to/actual/file.py), use GAME_DIR and EVENNIA_DIR to reference
your game folder and the Evennia library folders respectively. Python
paths (path.to.module) should be given relative to the game's root
folder (typeclasses.foo) whereas paths within the Evennia library
needs to be given explicitly (evennia.foo).

If you want to share your game dir, including its settings, you can
put secret game- or server-specific settings in secret_settings.py.

"""

import os

# Use the defaults from Evennia unless explicitly overridden
from evennia.settings_default import *

######################################################################
# Evennia base server config
######################################################################

# This is the name of your game. Make it catchy!
SERVERNAME = "aimud"

# Every one of Evennia's own commands inherits from this class, so naming our
# own here is what puts the goal reminder under `look`, `get` and `say` as
# well as under the commands this game defines. It subclasses MuxCommand and
# changes nothing else -- see commands/command.py.
COMMAND_DEFAULT_CLASS = "commands.command.MuxCommand"

# Evennia's own parser, with one rule on top: inside a generated world, a
# building, admin or system command has to be typed with its prefix --
# `@open`, `@examine`, `@force` -- so that `open door` is opening a door rather
# than a builder making an exit called "door". See server/conf/cmdparser.py.
COMMAND_PARSER = "server.conf.cmdparser.cmdparser"

# Evennia's own test runner, with the two costs the suite was paying per test
# taken out: a real password hash for every fixture account, and a full garbage
# collection that walked the WordNet indices. See server/conf/test_runner.py.
TEST_RUNNER = "server.conf.test_runner.Runner"

# Directories holding rulesets this server offers beyond the ones that ship
# with the game. A ruleset is a validated JSON document and never code, so
# nothing here can run; what putting a file in one of these buys is the right
# to add rules, kinds, states and figures a world's creator can then choose
# from. It needs access to the machine, which is the bar basic-principles.md
# sets for extending the game. A file whose `name` matches a built-in ruleset
# replaces it. See world/rulesets.py.
RULESET_DIRS = [os.path.join(GAME_DIR, "server", "conf", "rulesets")]


######################################################################
# Settings given in secret_settings.py override those in this file.
######################################################################
try:
    from server.conf.secret_settings import *
except ImportError:
    print("secret_settings.py file not found or failed to import.")
