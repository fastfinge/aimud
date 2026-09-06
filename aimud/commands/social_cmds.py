"""
Social command overrides that notify NPCs of player actions.
"""

from evennia.commands.default.general import CmdPose


class CmdAIEmote(CmdPose):
    """
    Overrides pose/emote so NPCs in the room witness the action.
    """

    def func(self):
        if not self.args:
            self.caller.msg("What do you want to do?")
            return
        super().func()
        room = self.caller.location
        if room:
            from world.npc_gen import notify_npcs
            pose_text = f"{self.caller.name}{self.args}"
            notify_npcs(room, "emote", self.caller.get_display_name(self.caller), pose_text)
