"""Automatic detection of the world format at a path."""

from __future__ import annotations

import gzip
import os
import struct
import zipfile
import zlib
from dataclasses import dataclass
from typing import Optional

from . import nbt
from .i18n import tr
from .model import ConversionError


@dataclass
class Detected:
    kind: str  # lce | java_numeric | java_modern | bedrock | pe_old | indev | classic | bta | archive
    description: str
    path: str
    subkind: str = ""


def _read(path: str, n: int = 64) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(n)
    except OSError:
        return b""


class UnsupportedWorld(ConversionError):
    """The path holds a world (or what is left of one) that cannot be read: the message says why."""


CLASSIC_MAGIC = b"\x27\x1b\xb7\x88"
JAVA_SERIALIZATION = b"\xac\xed\x00\x05"
_GZIP = b"\x1f\x8b"
_CLASSIC_RAW_SIZE = 256 * 64 * 256       # Classic before 0.0.13a: level.dat holds the bare blocks, gzipped
# DataVersion of the Java releases from 1.9 (the first with a DataVersion) to 1.12.2
_PRE_FLATTENING = {169: "1.9", 175: "1.9.1", 176: "1.9.2", 183: "1.9.3", 184: "1.9.4", 510: "1.10", 511: "1.10.1",
                   512: "1.10.2", 819: "1.11", 921: "1.11.1", 922: "1.11.2", 1139: "1.12", 1241: "1.12.1",
                   1343: "1.12.2"}


def _is_lfs_pointer(head: bytes) -> bool:
    return head.startswith(b"version https://git-lfs.github.com/spec/")


def _lfs_error(path: str) -> "UnsupportedWorld":
    return UnsupportedWorld(tr("{file} is a Git LFS pointer (a small text file standing for the real one): fetch the "
                               "real files with “git lfs pull” or download the world as an archive.",
                               file=os.path.basename(path)))


def _payload_head(path: str, head: bytes, n: int = 8) -> bytes:
    """The first bytes of a file's content, through gzip when it is gzipped."""
    if head[:2] != _GZIP:
        return head[:n]
    try:
        with gzip.open(path) as f:
            return f.read(n)
    except (OSError, EOFError, zlib.error):
        return b""


def _gzip_size(path: str) -> int:
    """Uncompressed size of a gzip file (modulo 4 GiB), from its trailer."""
    try:
        with open(path, "rb") as f:
            f.seek(-4, os.SEEK_END)
            return struct.unpack("<I", f.read(4))[0]
    except (OSError, struct.error):
        return -1


def _is_classic(path: str, head: bytes) -> bool:
    """A Minecraft Classic level, gzipped or not and whatever its name: the Classic magic number or a
    bare Java serialisation stream; gzipped ``.mine`` files and gzipped 256 x 64 x 256 level.dat
    (Classic before 0.0.13a) too."""
    raw = _payload_head(path, head)
    if raw[:4] in (CLASSIC_MAGIC, JAVA_SERIALIZATION):
        return True
    if head[:2] == _GZIP and raw:
        low = path.lower()
        if low.endswith(".mine"):
            return True
        if low.endswith((".dat", ".lvl")) and raw[:1] != b"\x0a" and _gzip_size(path) == _CLASSIC_RAW_SIZE:
            return True
    return False


def _bedrock_header(path: str, head: bytes) -> Optional[int]:
    """The storage version of a Bedrock / Pocket Edition level.dat (8-byte header + little endian NBT),
    None when the file is not one."""
    if len(head) < 9:
        return None
    ver, length = struct.unpack_from("<II", head, 0)
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if 0 < ver < 100 and head[8:9] == b"\x0a" and length == size - 8:
        return ver
    return None


def _java_level(level_dat: str):
    """(the Data compound of a Java level.dat, None) or (None, the UnsupportedWorld saying why it cannot be read)."""
    if _is_lfs_pointer(_read(level_dat, 64)):
        return None, _lfs_error(level_dat)
    try:
        with open(level_dat, "rb") as f:
            root = nbt.load(f.read()).tag
        if not isinstance(root, nbt.CompoundTag):
            raise ValueError(type(root).__name__)
    except Exception as ex:  # noqa: BLE001
        return None, UnsupportedWorld(tr("level.dat is not a valid NBT file: the world is damaged or incomplete "
                                         "({error}).", error=str(ex) or type(ex).__name__))
    return (nbt.get_tag(root, "Data") or root), None


def _java_version(data) -> tuple:
    """(DataVersion, version name) from a level.dat Data compound; either may be None."""
    dv = name = None
    try:
        v = nbt.get(data, "DataVersion")
        dv = int(v) if v is not None else None
        ver = nbt.get_tag(data, "Version")
        if ver is not None:
            name = str(nbt.get(ver, "Name") or "").strip() or None
    except Exception:  # noqa: BLE001
        pass
    return dv, name


def numeric_label(kind: str, data) -> str:
    if kind == "mcregion":
        return "Java Edition Beta 1.3 – Java 1.1 (McRegion)"
    if kind == "alpha":
        return "Java Edition Infdev / Alpha – Beta 1.2"
    dv, name = _java_version(data)
    name = name or _PRE_FLATTENING.get(dv or 0)
    if name:
        return f"Java Edition {name} (Anvil)"
    if dv:
        return f"Java Edition 1.9 – 1.12.2 (Anvil, DataVersion {dv})"
    return "Java Edition 1.2 – 1.12.2 (Anvil)"


def _modern_label(data) -> str:
    dv, name = _java_version(data)
    if name and dv:
        return f"Java Edition {name} (DataVersion {dv})"
    return f"Java Edition 1.13+ (DataVersion {dv})" if dv else "Java Edition 1.13+"


def _bedrock_label(level_dat: str, storage: Optional[int]) -> str:
    """Pocket Edition 0.9 - 0.16 kept its LevelDB worlds with storage version 4 (Bedrock 1.0 brought 5)
    and wrote no lastOpenedWithVersion, or one starting with 0."""
    pocket = storage is not None and storage <= 4
    if not pocket:
        try:
            with open(level_dat, "rb") as f:
                root = nbt.load(f.read()[8:], little_endian=True).tag
            lov = nbt.get_tag(root, "lastOpenedWithVersion")
            pocket = lov is not None and len(lov) > 0 and int(lov[0].py_data) == 0
        except Exception:  # noqa: BLE001
            pass
    return "Pocket Edition 0.9 – 0.16 (LevelDB)" if pocket else "Bedrock Edition (LevelDB)"


def _check_bedrock_db(path: str) -> None:
    """Raise UnsupportedWorld when the db folder of a Bedrock-style world holds no LevelDB database."""
    db = os.path.join(path, "db")
    if os.path.isdir(os.path.join(db, "cdb")) or os.path.isdir(os.path.join(db, "vdb")):
        raise UnsupportedWorld(tr("New Nintendo 3DS Edition worlds are not supported: their chunks are not kept in "
                                  "a LevelDB database (db/cdb, db/vdb) like those of the other Bedrock worlds."))
    if not os.path.isfile(os.path.join(db, "CURRENT")):
        raise UnsupportedWorld(tr("The db folder of this Bedrock world holds no LevelDB database (CURRENT is "
                                  "missing): the world is incomplete."))


def _detect_file(path: str) -> Optional[Detected]:
    """The worlds that are one file: archives, Classic, Indev."""
    low = path.lower()
    head = _read(path, 16)
    if low.endswith((".mcworld", ".zip")) and zipfile.is_zipfile(path):
        return Detected("archive", tr("World archive (.mcworld / .zip)"), path)
    if low.endswith(".mclevel"):
        return Detected("indev", "Java Edition Indev (.mclevel)", path)
    if _is_classic(path, head):
        return Detected("classic", "Java Edition Classic (.mine / level.dat)", path)
    if low.endswith((".mine", ".dat", ".lvl")) and head[:2] == _GZIP and os.path.basename(low) != "level.dat" \
            and _payload_head(path, head, 1) == b"\x0a":
        try:
            with open(path, "rb") as f:
                root = nbt.load(f.read()).tag
            if "Map" in root and "Environment" in root:
                return Detected("indev", "Java Edition Indev (.mclevel)", path)
        except Exception:  # noqa: BLE001
            pass
    return None


_NOT_WORLDS = ("level.dat_old", "session.lock", "levelname.txt", "icon.png", "world_icon.jpeg", "thumbs.db",
               "desktop.ini")


def _single_file_world(path: str, names) -> Optional[Detected]:
    """A folder that only holds a single-file world (Classic, Indev, .mcworld)."""
    files = sorted(n for n in names if os.path.isfile(os.path.join(path, n)) and not n.startswith(".")
                   and n.lower() not in _NOT_WORLDS)
    if not files or len(files) > 32:
        return None
    hits = [d for d in (_detect_file(os.path.join(path, n)) for n in files) if d is not None]
    return hits[0] if len(hits) == 1 else None


def detect(path: str, _depth: int = 0) -> Optional[Detected]:
    """The format of the world at ``path`` (a folder or a file); None when it is not recognised.

    Raises :class:`UnsupportedWorld` (a ConversionError) for worlds that are recognised but cannot be
    read, with a message saying why (Nintendo 3DS worlds, a level.dat that is not NBT or is a Git LFS
    pointer, Bedrock worlds without terrain…)."""
    path = os.path.abspath(path)
    if os.path.isfile(path):
        d = _detect_file(path)
        if d:
            return d
        if os.path.basename(path).lower() == "level.dat":
            d = detect(os.path.dirname(path))
            if d:
                return d
        from .lce.container import looks_like_lce

        if looks_like_lce(path):
            return Detected("lce", "Legacy Console Edition", path)
        if _is_lfs_pointer(_read(path, 64)):
            raise _lfs_error(path)
        return None

    if not os.path.isdir(path):
        return None
    names = set(os.listdir(path))
    level = os.path.join(path, "level.dat")
    has_level = os.path.isfile(level)
    head = _read(level, 64) if has_level else b""
    if _is_lfs_pointer(head):
        raise _lfs_error(level)
    storage = _bedrock_header(level, head) if has_level else None
    if "db" in names and os.path.isdir(os.path.join(path, "db")) and has_level:
        _check_bedrock_db(path)
        if storage is None:
            raise UnsupportedWorld(tr("The level.dat of this Bedrock world is not valid: the world is damaged or "
                                      "incomplete."))
        return Detected("bedrock", _bedrock_label(level, storage), path)
    if "chunks.dat" in names and has_level:
        return Detected("pe_old", "Pocket Edition 0.1 – 0.8 (chunks.dat)", path)
    if storage is not None:
        # a Bedrock level.dat with neither db/ nor chunks.dat, e.g. a world exported without its chunks
        raise UnsupportedWorld(tr("This Bedrock world has no terrain: the db folder with its chunks is missing (only "
                                  "level.dat and the add-ons were saved, the game generates the terrain when the "
                                  "world is first opened), so there is nothing to convert. Open it once in "
                                  "Minecraft and convert the saved world."))
    if has_level and _is_classic(level, head):
        return Detected("classic", "Java Edition Classic (.mine / level.dat)", level)
    from .bta.world import looks_like_bta

    data, problem = _java_level(level) if has_level else (None, None)
    if looks_like_bta(path):
        if problem is not None and not os.path.isfile(os.path.join(path, "level.dat_old")):
            raise problem
        return Detected("bta", tr("Better than Adventure (Beta 1.7.3 mod, BTA 8.0.1)"), path)
    if data is not None:
        from .java.numeric import detect_java_numeric

        kind = detect_java_numeric(path)
        if kind:
            return Detected("java_numeric", numeric_label(kind, data), path, kind)
        if os.path.isdir(os.path.join(path, "region")) or _java_version(data)[0]:
            return Detected("java_modern", _modern_label(data), path)
    elif problem is not None and os.path.isdir(os.path.join(path, "region")):
        raise problem
    from .lce.container import looks_like_lce

    if looks_like_lce(path):
        return Detected("lce", "Legacy Console Edition", path)
    d = _single_file_world(path, names) or _single_world_below(path, names, _depth)
    if d is None and problem is not None:
        raise problem
    return d


def _single_world_below(path: str, names, depth: int) -> Optional[Detected]:
    """The one world inside the subfolders of ``path`` (an extracted archive, a console save folder
    next to folders of other files); None when there is none or more than one."""
    if depth >= 3:
        return None
    subs = sorted(os.path.join(path, n) for n in names if os.path.isdir(os.path.join(path, n)))
    if len(subs) == 1:
        return detect(subs[0], depth + 1)
    if not 1 < len(subs) <= 8:
        return None
    found = []
    for s in subs:
        try:
            d = detect(s, depth + 1)
        except ConversionError:
            continue
        if d is not None:
            found.append(d)
            if len(found) > 1:
                return None
    return found[0] if found else None


def extract_archive(path: str, dest: str) -> str:
    """Extract a .mcworld/.zip; returns the folder that contains the world."""
    with zipfile.ZipFile(path) as z:
        z.extractall(dest)
    for root, dirs, files in os.walk(dest):
        if "level.dat" in files or "saveData.ms" in files or "GAMEDATA" in files:
            return root
    return dest


def snapshot(path: str, parent: str, link: bool = False) -> str:
    """Private working copy of a world folder, so the original is never touched.

    * Bedrock: opening a LevelDB replays its log and may rewrite files, and fails ("LOCK") while
      Minecraft or another program has the world open -> a copy of its own.  The table files
      (``.ldb`` / ``.sst``) are never changed once written (LevelDB writes new ones and deletes the old
      ones), so they are hard links: the copy costs only the log and the manifest, whatever the size
      of the world.
    * Java 1.13+ read through Amulet: Amulet takes the world's ``session.lock`` (Minecraft running on
      that world would lose it) -> ``link=True``: hard links (instant, no extra space) for the files,
      which are only read, and no session.lock.
    Plain copies where links are not possible (another disk: see ``snapshot_parent``)."""
    import shutil
    import tempfile

    os.makedirs(parent, exist_ok=True)
    dest = os.path.join(tempfile.mkdtemp(prefix="snap_", dir=parent), os.path.basename(os.path.normpath(path)) or "world")

    def link_or_copy(src, dst):
        if link or src.endswith((".ldb", ".sst")):
            try:
                os.link(src, dst)
                return
            except OSError:
                pass
        shutil.copy2(src, dst)

    shutil.copytree(path, dest, ignore=shutil.ignore_patterns("LOCK", "session.lock"), copy_function=link_or_copy)
    return dest


def snapshot_parent(path: str, tmp: str) -> Optional[str]:
    """Where to put the working copy of the world ``path`` when ``tmp`` is on another disk: a temporary
    folder next to the world, where hard links work (None: the same disk, or no folder can be made
    there; the caller removes the folder)."""
    import tempfile

    try:
        if os.stat(path).st_dev == os.stat(tmp).st_dev:
            return None
        return tempfile.mkdtemp(prefix=".worldbridge_", dir=os.path.dirname(os.path.abspath(path)))
    except OSError:
        return None
