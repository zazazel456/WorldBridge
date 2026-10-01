"""Xbox 360 STFS packages (CON / LIVE / PIRS): reading the files inside a Minecraft save package.

Only what WorldBridge needs: the file listing, the files' contents, the world's display name and
the thumbnail.

Layout, as far as it matters here (big endian unless noted):

* header: the magic, then metadata; ``0x340`` header size, the data area starts at the next
  0x1000 boundary; ``0x411`` display name and ``0x1691`` title name (UTF-16, 0x80 bytes);
  ``0x1712`` thumbnail size and ``0x171A`` the thumbnail (PNG);
* volume descriptor at ``0x379``: ``0x37B`` block separation, ``0x37C`` file table block count
  (little endian u16), ``0x37E`` file table first block (little endian u24), ``0x395`` allocated
  data blocks;
* the data area is a sequence of 0x1000-byte blocks: data blocks interleaved with hash tables.
  A level-0 table holds one 0x18-byte entry per data block of its group of 170 (SHA-1, a status
  byte, the next block of the file as u24); a level-1 table one entry per level-0 table (groups of
  170 × 170 blocks), a level-2 table one per level-1 table.  Each table is written right before the
  first data block that needs it, higher levels first.  When bit 0 of the block separation is clear
  (or when the data area starts at 0xB000) every table takes two blocks, a primary and a backup
  copy, and the status byte of the parent entry (bit 0x40) says which copy is current; for the top
  table, bit 1 of the block separation says it.

Written from https://github.com/Free60Project/wiki (docs/System-Software/Formats/STFS.md).
"""
from __future__ import annotations

import struct
from typing import Dict, List, Optional, Tuple

BLOCK = 0x1000
ENTRY = 0x18
SPAN = (170, 170 * 170, 170 * 170 * 170)   # data blocks covered by one table of level 0, 1, 2
MAGICS = (b"CON ", b"LIVE", b"PIRS")


def _u24le(b: bytes, o: int) -> int:
    return b[o] | (b[o + 1] << 8) | (b[o + 2] << 16)


def _u24be(b: bytes, o: int) -> int:
    return (b[o] << 16) | (b[o + 1] << 8) | b[o + 2]


def _layout(blocks: int, table_blocks: int) -> Tuple[List[int], List[List[int]]]:
    """Where every data block and every hash table sits, in blocks from the start of the data area.

    Returns (data[b], tables[level][index]).  A table of level k and index i is placed right before
    data block ``i * SPAN[k]`` (the first it covers); the first table of a level above 0 is only
    needed once the package outgrows one table of the level below, so it comes right before data
    block ``SPAN[k - 1]``.  Where several tables start at the same data block, the highest level
    comes first."""
    levels = 1 if blocks <= SPAN[0] else 2 if blocks <= SPAN[1] else 3
    starts: Dict[int, List[Tuple[int, int]]] = {}
    for k in range(levels):
        for i in range((blocks + SPAN[k] - 1) // SPAN[k] or 1):
            at = i * SPAN[k] if (i or k == 0) else SPAN[k - 1]
            starts.setdefault(at, []).append((k, i))
    tables: List[List[int]] = [[] for _ in range(levels)]
    data: List[int] = []
    pos = 0
    for b in range(blocks):
        for k, i in sorted(starts.get(b, ()), reverse=True):
            tables[k].append(pos)
            pos += table_blocks
        data.append(pos)
        pos += 1
    if not blocks:
        tables[0].append(0)
    return data, tables


class STFS:
    """An STFS package in memory: ``files`` (name -> (first block, blocks, size)), ``read_file``,
    ``display_name``, ``title_name``, ``profile_id`` and ``thumbnail``."""

    def __init__(self, data: bytes):
        if data[:4] not in MAGICS:
            raise ValueError(f"not an STFS package (magic {bytes(data[:4])!r})")
        self.d = data
        self.base = (struct.unpack_from(">I", data, 0x340)[0] + BLOCK - 1) & ~(BLOCK - 1)
        self.separation = data[0x37B]
        # a data area starting at 0xB000 always has two-block tables (Free60)
        self.table_blocks = 2 if self.base == 0xB000 or not self.separation & 1 else 1
        self.blocks = struct.unpack_from(">I", data, 0x395)[0]
        self._data, self._tables = _layout(self.blocks, self.table_blocks)
        self._copy: Dict[Tuple[int, int], int] = {}   # (level, index) -> 0 primary / 1 backup
        top = len(self._tables) - 1
        self._copy[(top, 0)] = 1 if (self.table_blocks == 2 and self.separation & 2) else 0
        self.display_name = self._text(0x411)
        self.title_name = self._text(0x1691)
        self.profile_id = bytes(data[0x371:0x379]).hex()
        self.thumbnail = self._thumbnail()
        self._consecutive: Dict[str, bool] = {}
        self.files = self._listing(_u24le(data, 0x37E), struct.unpack_from("<H", data, 0x37C)[0])

    # ------------------------------------------------------------------ blocks and hash entries
    def _offset(self, block: int) -> int:
        return self.base + block * BLOCK

    def _table_offset(self, level: int, index: int) -> int:
        return self._offset(self._tables[level][index] + self._which(level, index))

    def _which(self, level: int, index: int) -> int:
        """Which copy of a table is current, from the status byte of its entry in the parent."""
        key = (level, index)
        if key not in self._copy:
            if self.table_blocks == 1:
                self._copy[key] = 0
            else:
                parent = self._table_offset(level + 1, index // 170) + (index % 170) * ENTRY
                self._copy[key] = 1 if self.d[parent + 0x14] & 0x40 else 0
        return self._copy[key]

    def _entry(self, block: int) -> int:
        return self._table_offset(0, block // SPAN[0]) + (block % SPAN[0]) * ENTRY

    def _next(self, block: int) -> int:
        return _u24be(self.d, self._entry(block) + 0x15)

    def _chain(self, first: int, count: int, consecutive: bool) -> List[int]:
        out, b = [], first
        for _ in range(count):
            if not 0 <= b < self.blocks:
                break
            out.append(b)
            b = b + 1 if consecutive else self._next(b)
        return out

    def _read(self, first: int, count: int, size: Optional[int], consecutive: bool = False) -> bytes:
        buf = bytearray()
        for b in self._chain(first, count, consecutive):
            o = self._offset(self._data[b])
            buf += self.d[o:o + BLOCK]
        return bytes(buf if size is None else buf[:size])

    # ------------------------------------------------------------------ contents
    def _listing(self, first: int, count: int) -> Dict[str, Tuple[int, int, int]]:
        files: Dict[str, Tuple[int, int, int]] = {}
        table = self._read(first, count, None)
        for o in range(0, len(table), 0x40):
            e = table[o:o + 0x40]
            flags = e[0x28]
            n = flags & 0x3F
            if not n or flags & 0x80:            # empty entry, or a directory
                continue
            name = e[:n].decode("latin-1", "replace")
            files[name] = (_u24le(e, 0x2F), _u24le(e, 0x29), struct.unpack_from(">I", e, 0x34)[0])
            self._consecutive[name] = bool(flags & 0x40)
        return files

    def read_file(self, name: str) -> bytes:
        first, count, size = self.files[name]
        return self._read(first, count, size, self._consecutive.get(name, False))

    def _text(self, off: int) -> str:
        raw = bytes(self.d[off:off + 0x80])
        for i in range(0, len(raw) - 1, 2):
            if raw[i] == 0 and raw[i + 1] == 0:
                raw = raw[:i]
                break
        return raw.decode("utf-16-be", "ignore")

    def _thumbnail(self) -> Optional[bytes]:
        size = struct.unpack_from(">I", self.d, 0x1712)[0]
        img = bytes(self.d[0x171A:0x171A + size])
        return img if img[:4] == b"\x89PNG" else None
