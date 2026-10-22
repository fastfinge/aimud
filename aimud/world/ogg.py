"""
Ogg files that are the same whenever their sound is.
docs/archived/sound.md 4.3.

libsndfile gives every Ogg stream it writes a random serial number, so
encoding the same sound twice gives two files with two hashes -- and an asset
is its hash. Everything else Vorbis writes is the same for the same samples,
so `steady` sets the serial to one fixed number and puts each page's
checksum right, and then the same sound is the same file, every time.

No Django and nothing of the game's, so `world/sounds/rebuild.py` can use it
outside a running server.
"""

import struct

#: The serial every steadied stream carries. Any number would do; this one
#: spells "aimd".
SERIAL = 0x61696D64

_CAPTURE = b"OggS"


def _table():
    table = []
    for index in range(256):
        value = index << 24
        for _bit in range(8):
            value = ((value << 1) ^ 0x04C11DB7) if value & 0x80000000 \
                else value << 1
        table.append(value & 0xFFFFFFFF)
    return table


_CRC = _table()


def _crc(data):
    """Ogg's CRC-32: polynomial 0x04C11DB7, unreflected, starting at 0."""
    value = 0
    for byte in data:
        value = ((value << 8) & 0xFFFFFFFF) ^ _CRC[((value >> 24) ^ byte) & 0xFF]
    return value


def steady(data):
    """
    The same Ogg file with a fixed serial and checksums to match.

    Raises ValueError for anything that is not a run of whole Ogg pages, so
    a file this does not understand is never quietly passed on half-changed.
    """
    data = bytearray(data)
    at = 0
    while at < len(data):
        if data[at:at + 4] != _CAPTURE or at + 27 > len(data):
            raise ValueError("that is not a whole Ogg stream")
        segments = data[at + 26]
        table_end = at + 27 + segments
        if table_end > len(data):
            raise ValueError("that Ogg stream stops in the middle of a page")
        length = table_end - at + sum(data[at + 27:table_end])
        if at + length > len(data):
            raise ValueError("that Ogg stream stops in the middle of a page")
        struct.pack_into("<I", data, at + 14, SERIAL)
        struct.pack_into("<I", data, at + 22, 0)
        struct.pack_into("<I", data, at + 22, _crc(data[at:at + length]))
        at += length
    return bytes(data)
