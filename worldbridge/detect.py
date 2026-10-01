"""Automatic detection of the world format at a path."""

from __future__ import annotations

import gzip
import os
import struct
import zipfile
from dataclasses import dataclass
from typing import Optional

from . import nbt
from .i18n import tr


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


def _java_data_version(level_dat: str) -> Optional[int]:
    try:
        root = nbt.load(open(level_dat, "rb").read()).tag
        data = nbt.get_tag(root, "Data") or root
        dv = nbt.get(data, "DataVersion")
        return int(dv) if dv is not None else None
    except Exception:  # noqa: BLE001
        return None


def detect(path: str) -> Optional[Detected]:
    path = os.path.abspath(path)
    if os.path.isfile(path):
        low = path.lower()
        head = _read(path, 16)
        if low.endswith((".mcworld", ".zip")) and zipfile.is_zipfile(path):
            return Detected("archive", tr("World archive (.mcworld / .zip)"), path)
        if low.endswith(".mclevel"):
            return Detected("indev", "Java Edition Indev (.mclevel)", path)
        if low.endswith((".mine", ".dat", ".lvl")) and head[:2] == b"\x1f\x8b":
            try:
                raw = gzip.open(path).read(8)
            except OSError:
                raw = b""
            if raw[:4] == b"\x27\x1b\xb7\x88" or low.endswith(".mine"):
                return Detected("classic", "Java Edition Classic (.mine / level.dat)", path)
            if raw[:1] == b"\x0a" and os.path.basename(low) != "level.dat":
                try:
                    root = nbt.load(open(path, "rb").read()).tag
                    if "Map" in root and "Environment" in root:
                        return Detected("indev", "Java Edition Indev (.mclevel)", path)
                except Exception:  # noqa: BLE001
                    pass
        if os.path.basename(low) == "level.dat":
            d = detect(os.path.dirname(path))
            if d:
                return d
        from .lce.container import looks_like_lce

        if looks_like_lce(path):
            return Detected("lce", "Legacy Console Edition", path)
        return None

    if not os.path.isdir(path):
        return None
    names = set(os.listdir(path))
    level = os.path.join(path, "level.dat")
    if "db" in names and os.path.isdir(os.path.join(path, "db")) and "level.dat" in names:
        return Detected("bedrock", "Bedrock Edition (LevelDB)", path)
    if "chunks.dat" in names and "level.dat" in names:
        return Detected("pe_old", "Pocket Edition 0.1 – 0.8 (chunks.dat)", path)
    from .bta.world import looks_like_bta

    if looks_like_bta(path):
        return Detected("bta", tr("Better than Adventure (Beta 1.7.3 mod, BTA 8.0.1)"), path)
    if "level.dat" in names:
        from .java.numeric import detect_java_numeric

        kind = detect_java_numeric(path)
        if kind:
            desc = {"anvil": "Java Edition 1.2 – 1.12.2 (Anvil)", "mcregion": "Java Edition Beta 1.3 – 1.1 (McRegion)",
                    "alpha": "Java Edition Infdev / Alpha – Beta 1.2"}[kind]
            return Detected("java_numeric", desc, path, kind)
        dv = _java_data_version(level)
        if os.path.isdir(os.path.join(path, "region")) or dv:
            return Detected("java_modern", f"Java Edition 1.13+ (DataVersion {dv})", path)
        # level.dat with only an Indev/Classic style?
    from .lce.container import looks_like_lce

    if looks_like_lce(path):
        return Detected("lce", "Legacy Console Edition", path)
    # a folder that contains exactly one world
    subs = [os.path.join(path, n) for n in names if os.path.isdir(os.path.join(path, n))]
    if len(subs) == 1:
        return detect(subs[0])
    return None


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
