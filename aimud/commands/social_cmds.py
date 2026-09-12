"""
Social command overrides that notify NPCs of player actions.
"""

from evennia.commands.default.general import CmdPose


class CmdAIEmote(CmdPose):
    """
    Overrides pose/emote so NPCs witness the action, and so the pose is
    attributed to whatever the character is called in this world.

    The broadcast is built here rather than delegated to CmdPose, which
    composes it from `caller.name` -- the account name. A character who has
    named themselves in this world would otherwise pose under their login.
    """

    def func(self):
        caller = self.caller
        if not self.args:
            caller.msg("What do you want to do?")
            return

        # parse() has already put the separating space in, or left it out for
        # a pose starting with an apostrophe or comma.
        name = caller.get_display_name(caller)
        pose = f"{name}{self.args}"

        room = caller.location
        if room is None:
            caller.msg(pose)
            return

        room.msg_contents(text=(pose, {"type": "pose"}), from_obj=caller)

        # And so "him" means whoever just posed. A pose is not an action on
        # an object and has no template, so nothing else records it -- see
        # events.noticed, which the NPCs' own speech shares.
        from world import events

        events.noticed(room, caller)

        # The pose already opens with the actor's name, and describe_event
        # notices that, so the event is recorded once rather than as
        # "Aria Delacroix Aria Delacroix bows deeply."
        from world.npc_gen import notify_npcs

        notify_npcs(room, "emote", name, pose, actor=caller)
