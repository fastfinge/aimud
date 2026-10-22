"""
MSP, the MUD Sound Protocol, on Evennia's telnet. docs/archived/sound.md 3.2.

Evennia speaks GMCP, MSDP and MXP and has no MSP, so this adds it: one more
telnet option (90) offered in the handshake, a protocol flag the Server can
read, and `send_msp`, which writes a line the client takes for an
instruction rather than text. Everything about what to play is decided in
`world/sound.py`; nothing here knows what a sound is.

A client that answers `DONT`, or nothing, never has a line of MSP written to
it, so nobody's screen fills with `!!SOUND(...)`.

Evennia's SSL protocol subclasses whatever `TELNET_PROTOCOL_CLASS` names, so
telnet over TLS offers MSP too, with nothing more here.
"""

from evennia.server.portal.telnet import TelnetProtocol

#: The telnet option MSP negotiates on.
MSP = bytes([90])

#: Where `world/sound.py` reads whether a session agreed to it.
FLAG = "MSP"


class MspMixin:
    """MSP on a telnet protocol: offered, remembered, and written."""

    def connectionMade(self):
        super().connectionMade()
        self.protocol_flags[FLAG] = False
        # One more handshake for the Portal to wait on before it tells the
        # Server what this client can do; the client answering either way
        # counts it down, and Evennia's own timeout covers a client that
        # says nothing.
        self.handshakes += 1
        self.will(MSP).addCallbacks(self._msp_yes, self._msp_no)

    def _msp_yes(self, _option):
        self.protocol_flags[FLAG] = True
        self.handshake_done()

    def _msp_no(self, _option):
        self.protocol_flags[FLAG] = False
        self.handshake_done()

    def enableLocal(self, option):
        # A client asking for MSP before being offered it is agreeing to it.
        if option == MSP:
            self.protocol_flags[FLAG] = True
            return True
        return super().enableLocal(option)

    def disableLocal(self, option):
        if option == MSP:
            self.protocol_flags[FLAG] = False
            return True
        return super().disableLocal(option)

    def send_msp(self, *args, **kwargs):
        """
        Write `!!SOUND(...)` or `!!MUSIC(...)` lines as they are, each on a
        line of its own, which is how a client tells them from text.
        """
        if not self.protocol_flags.get(FLAG):
            return
        for line in args:
            if isinstance(line, (list, tuple)):
                for each in line:
                    self.sendLine(str(each))
            elif line:
                self.sendLine(str(line))


class MspTelnetProtocol(MspMixin, TelnetProtocol):
    pass
