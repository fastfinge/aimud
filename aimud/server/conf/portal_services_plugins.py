"""
Start plugin services

This plugin module can define user-created services for the Portal to
start.

This module must handle all imports and setups required to start
twisted services (see examples in evennia.server.portal.portal). It
must also contain a function start_plugin_services(application).
Evennia will call this function with the main Portal application (so
your services can be added to it). The function should not return
anything. Plugin services are started last in the Portal startup
process.

"""


def start_plugin_services(portal):
    """
    This hook is called by Evennia, last in the Portal startup process.

    portal - a reference to the main portal application.

    The MCP endpoint is started here and nowhere else. It is a way into the
    game, so it belongs beside telnet and the webclient rather than in the
    webserver: the Portal is where sessions are made, and an MCP session is an
    Evennia session. See docs/archived/mcp.md §3.2.

    It listens only if `MCP_ENABLED` says so, on the interface `MCP_INTERFACE`
    names, which is localhost unless somebody deliberately changed it --
    and `check_lockdown` puts it back to localhost when the server is in
    lockdown, exactly as it does for telnet and the webclient.
    """
    from django.conf import settings

    if not getattr(settings, "MCP_ENABLED", False):
        return

    import evennia
    from twisted.application import internet
    from twisted.web import server

    from server.conf.mcp_protocol import McpResource

    interface = portal.check_lockdown(
        [getattr(settings, "MCP_INTERFACE", "127.0.0.1")])[0]
    port = getattr(settings, "MCP_PORT", 4005)

    site = server.Site(McpResource(evennia.PORTAL_SESSION_HANDLER),
                       logPath=None)
    site.noisy = False
    service = internet.TCPServer(port, site, interface=interface)
    service.setName(f"aimudMCP{interface}:{port}")
    service.setServiceParent(portal)
    portal.info_dict.setdefault("mcp", []).append(f"mcp: {interface}:{port}")
