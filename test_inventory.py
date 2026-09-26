#!/usr/bin/env python3
import hashlib
import os
import struct
import sys
import tempfile

import app_gui
import valheim_character_editor as c
from valheim_character_editor import Character, inv_rows_for, inv_rows_from_uniques


def s(x):
    b = x.encode("utf-8")
    return bytes([len(b)]) + b


def item(h, x, y, cheated=False):
    return (struct.pack("<i", 100) + bytes([x, y, 0, 0x40]) +
            struct.pack("<i", h) + bytes([1 if cheated else 0]))


def build_blob(rows, items):
    # a minimal but structurally complete PlayerData blob
    b = bytearray()
    b += struct.pack("<i", 33)                          # player data version
    b += struct.pack("<4f", 100.0, 100.0, 100.0, 0.0)   # health, stamina, tsd
    b += s("Eikthyr")                                   # guardian power
    b += struct.pack("<f", 0.0)                         # guardian power cooldown
    b += struct.pack("<i", 1)                           # inventory version
    b += struct.pack("<H", len(items)) + b"".join(item(*i) for i in items)
    b += struct.pack("<i", 0) * 4                       # four empty string lists
    # the fifth list is the global keys; "invrows N" sits in it
    b += struct.pack("<i", 2) + s("HildirMap") + s("invrows %d" % rows)
    b += struct.pack("<i", 0) * 3                       # three more
    b += s("") + s("")                                  # two loose strings
    b += bytes(24)                                      # two vec3
    b += struct.pack("<i", 0)
    b += struct.pack("<i", 0)
    b += struct.pack("<i", 2)                           # skills version
    b += struct.pack("<i", 1) + struct.pack("<iff", 1, 10.0, 0.5)
    b += struct.pack("<i", 0)
    b += struct.pack("<3f", 10.0, 10.0, 10.0)           # stamina, maxEitr, eitr
    b += struct.pack("<i", 0)                           # trailing byte block
    return bytes(b)


def build_profile(blob):
    b = bytearray()
    b += struct.pack("<iii", 46, 205, 1)     # profile version, stats, buckets
    b += bytes(4 * 205)                      # one float per stat
    b += struct.pack("<i", 0) * 9            # eight float dicts + sub count
    b += bytes([0])                          # first spawn
    b += struct.pack("<i", 0)                # no known worlds
    b += s("Tester") + struct.pack("<q", 1) + s("seed")
    b += bytes([0])                          # m_usedCheats
    b += struct.pack("<q", 1700000000)       # date created
    b += bytes([1])                          # has embedded player data
    b += struct.pack("<i", len(blob)) + blob
    return bytes(b)


def build_fch(rows, items):
    body = build_profile(build_blob(rows, items))
    return (struct.pack("<i", len(body)) + body +
            struct.pack("<i", 64) + hashlib.sha512(body).digest())


class Stub:
    pass


def collect_as_gui(items, rows):
    # run the GUI's own collection slice, without a Tk root
    st = Stub()
    st.inv_items = {(i["x"], i["y"]): i for i in items}
    st.inv_rows = rows
    return app_gui.EditorApp._collect_inventory(st)


def main():
    # Row count comes out of the "invrows N" global key.
    assert inv_rows_from_uniques(["GP_Eikthyr", "invrows 6"]) == 6
    assert inv_rows_from_uniques(["invrows 4"]) == 4
    assert inv_rows_from_uniques([]) == c.INV_ROWS_FALLBACK
    assert inv_rows_from_uniques(["invrows junk"]) == c.INV_ROWS_FALLBACK
    # a corrupt count can't size the grid past what a byte addresses
    assert inv_rows_from_uniques(["invrows 999999999"]) == c.INV_ROWS_MAX
    assert inv_rows_from_uniques(["invrows 0"]) == 1

    # items below the declared count raise it, so none are ever hidden
    assert inv_rows_for([{"y": 3}], 4) == 4
    assert inv_rows_for([{"y": 5}], 4) == 6
    assert inv_rows_for([{"y": 1}], 6) == 6
    assert inv_rows_for([], 4) == 4

    # (hash, x, y): two items sit in rows 4 and 5, one in the first row.
    slots = [(1, 0, 0), (2, 0, 4), (3, 1, 5)]
    want = [(0, 0), (0, 4), (1, 5)]
    raw = build_fch(6, slots)
    fd, path = tempfile.mkstemp(suffix=".fch")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(raw)
        ch = Character(path)
        assert ch.player["inv_rows"] == 6, ch.player["inv_rows"]
        assert sorted((i["x"], i["y"]) for i in ch.player["inventory"]) == want, \
            ch.player["inventory"]

        # The GUI slice used to drop everything past row 3.
        kept = collect_as_gui(ch.player["inventory"], ch.player["inv_rows"])
        assert len(kept) == 3, "rows 4-5 dropped by the GUI slice: %r" % (kept,)

        # Saving those items through the writer keeps them.
        out = c.write_character(ch, None, {}, ch.profile["used_cheats"],
                                False, list(kept))
        with open(path, "wb") as f:
            f.write(out)
        again = Character(path)
        assert sorted((i["x"], i["y"]) for i in again.player["inventory"]) == want, \
            again.player["inventory"]

        # A save that touches nothing must not change a single byte.
        with open(path, "wb") as f:
            f.write(raw)
        ch = Character(path)
        assert c.write_character(ch, None, {}, ch.profile["used_cheats"]) == raw, \
            "idle save changed the file"

        # A save declaring 4 rows but holding a row-5 item still keeps it.
        with open(path, "wb") as f:
            f.write(build_fch(4, [(1, 0, 0), (2, 0, 5)]))
        ch = Character(path)
        assert ch.player["inv_rows"] == 6, ch.player["inv_rows"]
        assert len(collect_as_gui(ch.player["inventory"], ch.player["inv_rows"])) == 2

        print("test_inventory: OK")
        return 0
    finally:
        for p in (path, path + ".bak"):
            if os.path.exists(p):
                os.remove(p)


if __name__ == "__main__":
    sys.exit(main())
