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

# Directories holding exported worlds. The first is also where `export world`
# writes, and it is the shared folder players import each other's worlds from.
# A world document is validated JSON and never code, exactly as a ruleset is,
# and its filename comes from the world's title through `exchange.slug` --
# nothing a player types ever becomes a path. Add a directory here to offer
# worlds somebody put on the machine by hand. See world/exchange.py.
WORLD_DIRS = [os.path.join(GAME_DIR, "worlds")]

# The MCP endpoint, which is how an agent plays and builds here. Off unless
# this says otherwise, and listening on localhost when it is: turning it on
# and reaching it from another machine are two separate decisions, and the
# second one belongs to somebody who has read what a token is. A token is the
# account -- everything that account can do, its API key included -- so an
# agent meant to play beside you wants an account of its own, which can be
# given less. Lockdown mode puts the interface back to localhost whatever is
# set here, as it does for telnet. See docs/mcp.md and world/agents.py.
#
# 4007 because Evennia has 4000 to 4006 already: telnet 4000, the web proxy
# 4001, the websocket client 4002, SSL 4003, SSH 4004, the webserver's own
# internal port 4005 (the second half of WEBSERVER_PORTS, which is easy to
# miss) and AMP 4006. Picking 4005 makes the Portal bind it first and the
# Server fail to start at all, which is how this comment came to be written.
MCP_ENABLED = False
MCP_INTERFACE = "127.0.0.1"
MCP_PORT = 4007


######################################################################
# Settings given in secret_settings.py override those in this file.
######################################################################
try:
    from server.conf.secret_settings import *
except ImportError:
    print("secret_settings.py file not found or failed to import.")
