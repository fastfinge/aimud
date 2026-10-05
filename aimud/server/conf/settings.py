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

# Assets: files the game keeps for its players and tools -- world documents
# today, and sounds, images and the rest as the systems that use them arrive.
# Players name and pick them and never see a path. See docs/archived/assets.md.
INSTALLED_APPS += ["assets"]

# How much each account may keep, in bytes; None for no limit. An admin can
# set one account's own with `edit quota`. An asset counts against whoever
# paid for it to exist, once, and never against somebody reusing it.
ASSET_QUOTA = 500 * 1024 * 1024

# How much the server keeps of assets their owners gave up. When it is full,
# the least-used of them are deleted and marked missing wherever they were
# used, so giving files up cannot fill the disk on nobody's quota.
ASSET_POOL_QUOTA = 1024 * 1024 * 1024

# Where asset files are kept: the class that stores them. The local one keeps
# them under MEDIA_ROOT, which Evennia already serves at /media/ without
# listing directories. Another class (S3, say) needs nothing else changed.
ASSET_STORE = "world.asset_store.LocalStore"

# This server's address as somebody outside it would type it, such as
# "https://mud.example.com:4001". A server cannot work it out for itself, and
# a world exported from here, or a sound sent to a client, needs a full URL.
# Until it is set, exports name their assets by hash alone.
ASSET_BASE_URL = ""

# Ports a player-named download may use. The web's usual ones, and 4001,
# Evennia's website port, so a world can be imported from another aimud.
# Whatever is listed here, nothing is ever fetched from a private address.
ASSET_FETCH_PORTS = (80, 443, 8080, 8443, 4001)

# The MCP endpoint, which is how an agent plays and builds here. Off unless
# this says otherwise, and listening on localhost when it is: turning it on
# and reaching it from another machine are two separate decisions, and the
# second one belongs to somebody who has read what a token is. A token is the
# account -- everything that account can do, its API key included -- so an
# agent meant to play beside you wants an account of its own, which can be
# given less. Lockdown mode puts the interface back to localhost whatever is
# set here, as it does for telnet. See docs/archived/mcp.md and world/agents.py.
#
# 4007 because Evennia has 4000 to 4006 already: telnet 4000, the web proxy
# 4001, the websocket client 4002, SSL 4003, SSH 4004, the webserver's own
# internal port 4005 (the second half of WEBSERVER_PORTS, which is easy to
# miss) and AMP 4006. Picking 4005 makes the Portal bind it first and the
# Server fail to start at all, which is how this comment came to be written.
MCP_ENABLED = False
MCP_INTERFACE = "127.0.0.1"
MCP_PORT = 4007

# Where a browser reaches this game's web pages, for the one thing that sends
# a browser here from somewhere else: a service authorised with OAuth, which
# comes back to /services/oauth/callback. Empty means localhost on the web
# port, which works for an admin at this machine and nobody else. Services
# themselves are added in the game by the owner (`create service`), with this
# server's credentials and never a player's. See docs/archived/mcp-client.md and
# world/services.py.
SERVICES_PUBLIC_URL = ""


######################################################################
# Settings given in secret_settings.py override those in this file.
######################################################################
try:
    from server.conf.secret_settings import *
except ImportError:
    print("secret_settings.py file not found or failed to import.")
