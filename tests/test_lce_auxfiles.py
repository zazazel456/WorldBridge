"""The auxiliary save files whose layout depends on the console: data/largeMapDataMappings.dat.

neoLegacy (``DirectoryLevelStorage::prepareLevel``) reads ``count`` entries of ``sizeof(PlayerUID) + int +
n x (int64, int32)`` and then a bit field; a PS3 file (28 byte ids) read as Windows64 (8 byte ids) made it loop
"-- -1 (0xffffffffffffffff) = -1" for 8 GB of log.
"""
import struct

import pytest

from worldbridge.lce import auxfiles as aux
from worldbridge.lce.container import PLATFORMS, SaveContainer
from worldbridge.lce.world import LCEWorld, LCEWriteOptions, LCEWriter
from worldbridge.model import Progress

from .helpers import SyntheticWorld

# the real files (gdp_ps3, gdp_x360, gdp_wiiu, gdp_psvita_3, gdp_ps4), as the consoles wrote them
_PS3 = bytes.fromhex(
    "00000002" "6b6e6172465f35323000000000000000" "0025280dfc7dac2f00000003" "00000001" "000000000000000c" "00000001"
    "6b6e6172465f35323000000000000000" "0097280dfc7dac2f00000001" "00000001" "000000000000000c" "00000000"
    "03" + "00" * 31)
_X360 = bytes.fromhex("00000001" "e00000f5524ed2fc" "00000001" "000000000000000c" "00000000" "01" + "00" * 31)
_WIIU = bytes.fromhex("00000001" "9cf253d06cff11e384ecfdcd4441e72ed0bbcbe0" "00000001" "000000000000000c" "00000000"
                      "01" + "00" * 31)


def _vita() -> bytes:
    uid = b"M0rqu1ng4".ljust(16, b"\0") + bytes.fromhex("0009d44b5e32c4e600000000")
    return (struct.pack(">I", 1) + uid + struct.pack(">I", 1) + struct.pack(">q", 12) + struct.pack(">i", 0)
            + b"\x01" + bytes(31))


def _ps4() -> bytes:
    uid = bytes(16) + bytes.fromhex("0058709e298a7e6fd7c3a818")
    return (struct.pack(">I", 1) + uid + struct.pack(">I", 1) + struct.pack(">q", 12) + struct.pack(">i", 0)
            + b"\x01" + bytes(1023))


def test_the_real_files_parse_with_the_id_size_of_their_console():
    for blob, plat, entries in ((_PS3, "ps3", 2), (_X360, "xbox360", 1), (_WIIU, "wiiu", 1), (_vita(), "vita", 1),
                                (_ps4(), "ps4", 1)):
        got, tail = aux.parse_mappings(blob, aux.UID_LEN[plat])
        assert len(got) == entries and len(tail) == aux.trailer_size(plat), plat
        for uid, pairs in got:
            assert len(uid) == aux.UID_LEN[plat] and pairs and struct.unpack(">q", pairs[0][0])[0] == 12


def test_a_wrong_id_size_is_not_a_valid_file():
    """The PS3 file as a Windows64 one is garbage (the counts run past the end): the converter must not copy it."""
    assert aux.parse_mappings(_PS3, 8) is None


@pytest.mark.parametrize("src, blob", [("ps3", _PS3), ("xbox360", _X360), ("wiiu", _WIIU), ("vita", _vita()),
                                       ("ps4", _ps4())])
@pytest.mark.parametrize("dst", list(PLATFORMS))
def test_every_platform_pair_gives_a_file_the_target_reads(src, blob, dst):
    players = {"ps3": [("P_280dfc7dac2f_00000001_knarF_520", "P_280dfc7dac2f_00000001_knarF_520")],
               "xbox360": [("16140902118143742716", "16140902118143742716")],
               "wiiu": [("9cf253d06cff11e384ecfdcd4441e72e", "9cf253d06cff11e384ecfdcd4441e72e")],
               "vita": [("P_d44b5e32c4e6_00000000_M0rqu1ng4", "P_d44b5e32c4e6_00000000_M0rqu1ng4")],
               "ps4": [("P_709e298a7e6f_413713367_", "P_709e298a7e6f_413713367_")]}[src]
    # the player is written under the id the target loads: an XUID, a console user, a Wii U user
    target_name = {"win64": "15885783760619110653", "xbox360": "15885783760619110653",
                   "wiiu": "0123456789abcdef0123456789abcdef",
                   "ps3": "P_709e298a7e6f_00000000_Host"}.get(dst, "P_709e298a7e6f_00000000_Host")
    out, kept, lost = aux.convert_mappings(blob, src, dst, [(players[0][0], target_name)])
    ulen = aux.UID_LEN[dst]
    if ulen is None:                 # Xbox One / Switch: id size never seen, so no entry (valid whatever it is)
        assert out == aux.empty_mappings(dst) and kept == 0
        return
    entries, tail = aux.parse_mappings(out, ulen)       # what the game reads
    assert len(tail) == aux.trailer_size(dst)
    assert len(entries) == kept
    assert kept >= 1                                   # the player was told: its large maps stay
    for uid, pairs in entries:
        assert len(uid) == ulen
        assert struct.unpack(">q", pairs[0][0])[0] == 12


def test_the_ids_of_the_players_are_rebuilt_for_the_target():
    out, kept, lost = aux.convert_mappings(_PS3, "ps3", "win64", [("P_280dfc7dac2f_00000001_knarF_520", "424242")])
    (uid, pairs), = aux.parse_mappings(out, 8)[0]
    assert uid == struct.pack(">Q", 424242) and kept == 1
    # both entries of the PS3 user are the same player for Windows64: the first value of a key wins
    assert [struct.unpack(">i", v)[0] for _, v in pairs] == [1]
    # the bit field of the used map ids is kept
    assert aux.parse_mappings(out, 8)[1][0] == 3

    out, kept, lost = aux.convert_mappings(_X360, "xbox360", "ps3", [("16140902118143742716", "P_280dfc7dac2f_00000001_Frank")])
    (uid, pairs), = aux.parse_mappings(out, 28)[0]
    assert uid[:5] == b"Frank" and uid[18:24].hex() == "280dfc7dac2f" and len(uid) == 28


def test_the_same_console_family_keeps_the_original_id_bytes():
    out, kept, lost = aux.convert_mappings(_X360, "xbox360", "win64", [("16140902118143742716", "16140902118143742716")])
    assert out == _X360
    out, kept, lost = aux.convert_mappings(_PS3, "ps3", "ps4", [("P_280dfc7dac2f_00000001_knarF_520",
                                                                 "P_280dfc7dac2f_00000001_knarF_520")])
    ents, tail = aux.parse_mappings(out, 28)
    assert len(tail) == 1024 and ents[0][0] == aux.parse_mappings(_PS3, 28)[0][0][0]


def test_players_the_target_does_not_know_are_dropped_not_guessed():
    out, kept, lost = aux.convert_mappings(_PS3, "ps3", "win64", [("P_ffffffffffff_00000001_other", "1")])
    assert (kept, lost) == (0, 2)
    assert out[:4] == bytes(4) and len(out) == 4 + 32 and out[4] == 3        # no entry; the used ids stay used
    out, kept, lost = aux.convert_mappings(_PS3, "ps3", "win64", [])
    assert kept == 0 and out[:4] == bytes(4) and len(out) == 4 + 32


def test_a_file_that_fits_no_layout_becomes_an_empty_table():
    for bad in (b"", b"\x00\x00", struct.pack(">I", 7) + b"\xff" * 40, b"\x7f" * 124):
        out, kept, lost = aux.convert_mappings(bad, "ps3", "win64", [])
        assert out == aux.empty_mappings("win64") and kept == 0


def test_the_layout_of_an_unlisted_platform_is_found_by_trying():
    """A Switch / Xbox One file has an id size never seen: take the one that fits."""
    out, kept, lost = aux.convert_mappings(_PS3, "switch", "win64", [("P_280dfc7dac2f_00000001_knarF_520", "7")])
    assert kept == 0 or aux.parse_mappings(out, 8) is not None
    assert aux.parse_mappings(out, 8)[1] == bytes([3]) + bytes(31)


# ------------------------------------------------------------------ through the whole conversion
def _save_with_mappings(tmp_path, platform, blob, player_id=None):
    src = SyntheticWorld(radius=1)
    path = str(tmp_path / f"src_{platform}")
    w = LCEWriter(path, LCEWriteOptions(platform=platform, world_size=54, host_player_id=player_id), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    main = w.finish(src.info)
    cont = SaveContainer.load(main)
    cont.files[aux.MAPPINGS_FILE] = blob
    cont.save(path, main.rsplit("/", 1)[-1])
    return path


@pytest.mark.parametrize("src, dst", [("xbox360", "win64"), ("win64", "ps3"), ("ps3", "win64"), ("ps4", "xbox360"),
                                      ("wiiu", "vita"), ("vita", "wiiu"), ("win64", "ps4"), ("xbox360", "wiiu")])
def test_a_converted_save_has_the_mappings_in_the_layout_of_the_target(tmp_path, src, dst):
    from worldbridge import detect as det
    from worldbridge.convert import TargetSpec, convert

    blob = {"ps3": _PS3, "xbox360": _X360, "wiiu": _WIIU, "vita": _vita(), "ps4": _ps4(),
            "win64": _X360}[src]
    first = _save_with_mappings(tmp_path, src, blob)
    out = str(tmp_path / "out")
    convert(det.detect(first).path, out, TargetSpec(family="lce", lce_platform=dst, lce_world_size=54))
    world = LCEWorld(det.detect(out).path)
    got = world.container.files.get(aux.MAPPINGS_FILE)
    if got is None:
        return                                           # nothing to carry: no file is a valid state too
    ulen = aux.UID_LEN[dst]
    parsed = aux.parse_mappings(got, ulen)
    assert parsed is not None and len(parsed[1]) == aux.trailer_size(dst), (src, dst, got[:48].hex())
    assert len(got) == 4 + sum(ulen + 4 + 12 * len(p) for _, p in parsed[0]) + len(parsed[1])


def test_the_host_id_given_by_the_user_owns_the_large_maps(tmp_path):
    """PS3 -> Windows64 with --player-id: the entries of the PS3 user become the entries of that XUID."""
    from worldbridge import detect as det
    from worldbridge.convert import TargetSpec, convert

    first = _save_with_mappings(tmp_path, "ps3", _PS3)
    # the synthetic save writes its player as P_000000000000_00000000_Player0: name it as the real one
    cont = SaveContainer.load(det.detect(first).path)
    pl = next(k for k in cont.files if k.startswith("P_"))
    cont.files["P_280dfc7dac2f_00000001_knarF_520.dat"] = cont.files.pop(pl)
    cont.save(first, "GAMEDATA")
    out = str(tmp_path / "out")
    convert(det.detect(first).path, out, TargetSpec(family="lce", lce_platform="win64", lce_world_size=54,
                                                    lce_player_id="15885783760619110653"))
    got = LCEWorld(det.detect(out).path).container.files[aux.MAPPINGS_FILE]
    entries, tail = aux.parse_mappings(got, 8)
    assert [u for u, _ in entries] == [struct.pack(">Q", 15885783760619110653)]
    assert len(tail) == 32 and tail[0] == 3
