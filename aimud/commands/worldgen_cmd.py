"""
The worldgen command.
"""

from commands.command import Command


class CmdWorldgen(Command):
    """
    Generate a new AI-powered world and enter it.

    Usage:
      worldgen <description>

    Examples:
      worldgen A fantasy dungeon beneath an ancient castle
      worldgen A Korean airport at midnight
      worldgen A sprawling cyberpunk bazaar

    Generates a starting room based on the description and moves your
    character into it.  As you explore exits, new rooms are generated
    on the fly using your configured AI model.

    Requires an OpenRouter API key (see |wapikey|n).
    Configure which model to use with |wmodels|n.
    """

    key = "worldgen"
    locks = "cmd:all()"
    help_category = "World"

    def func(self):
        world_description = self.args.strip()
        if not world_description:
            self.caller.msg("Usage: worldgen <world description>")
            return

        account = getattr(self.caller, "account", None) or self.caller

        try:
            account.get_openrouter_key()
        except ValueError as e:
            self.caller.msg(str(e))
            return

        caller = self.caller
        self.caller.msg(f"Generating starting room for: |w{world_description}|n")

        def on_success(room):
            caller.msg(f"|gEntering: {room.db.room_title or room.key}|n")
            caller.move_to(room, quiet=False)

        def on_error(err):
            caller.msg(f"|rWorld generation failed: {err}|n")

        from world.worldgen import generate_first_room
        generate_first_room(account, world_description, on_success, on_error)
