"""Trees, grass and flowers for the ring around a converted world.

The game decorates the ring's chunks with the trees of *its* biomes: where the converted world is
a forest and the game's biome there is plains or ocean, the forest would stop dead at the border.
The ring therefore gets the converted border's trees too, fewer and fewer towards its outer edge,
in the shapes of the old games (oak and birch of WorldGenTrees, spruce of WorldGenTaiga2).
"""

from __future__ import annotations

import numpy as np

from .betagen import DIRT, GRASS

LOG, LEAVES, TALL_GRASS, DANDELION, ROSE = 17, 18, 31, 37, 38
OAK, SPRUCE, BIRCH = 0, 1, 2


def plant(blocks: np.ndarray, data: np.ndarray, count: int, spruce: float, birch: float,
          rng: np.random.Generator, sea: int) -> int:
    """Up to ``count`` trees on the grass of a chunk ([y, z, x] arrays, trunks at least 2 blocks
    from the chunk's sides so the leaves stay inside it).  Returns the trees planted."""
    if count <= 0:
        return 0
    H = blocks.shape[0]
    planted = []
    for _ in range(count * 3):
        if len(planted) >= count:
            break
        x, z = int(rng.integers(2, 14)), int(rng.integers(2, 14))
        if any(abs(x - px) + abs(z - pz) < 4 for px, pz in planted):
            continue
        col = blocks[:, z, x]
        nz = np.nonzero(col)[0]
        if not len(nz):
            continue
        g = int(nz.max())
        if col[g] not in (GRASS, DIRT) or g <= sea or g + 12 >= H:
            continue
        r = rng.random()
        kind = SPRUCE if r < spruce else BIRCH if r < spruce + birch else OAK
        if kind == SPRUCE:
            ok = _spruce(blocks, data, x, g + 1, z, rng)
        else:
            ok = _round(blocks, data, x, g + 1, z, rng, kind)
        if ok:
            blocks[g, z, x] = DIRT
            planted.append((x, z))
    return len(planted)


def _free(blocks, x0, x1, y0, y1, z0, z1) -> bool:
    box = blocks[y0:y1, z0:z1, x0:x1]
    return bool(((box == 0) | (box == LEAVES)).all())


def _round(blocks, data, x, y, z, rng, kind) -> bool:
    """WorldGenTrees (oak) / WorldGenForest (birch): a trunk of 4 - 6 (birch 5 - 7) and a round crown."""
    h = int(rng.integers(4, 7)) + (1 if kind == BIRCH else 0)
    top = y + h
    if not _free(blocks, x - 2, x + 3, y + 1, top + 1, z - 2, z + 3):
        return False
    for yy in range(top - 3, top + 1):
        r = 1 + (top - yy) // 2                 # as the game: 2, 2, 1, 1 from the bottom
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                if abs(dx) == r and abs(dz) == r and r > 0 and (rng.integers(2) == 0 or yy == top):
                    continue
                if blocks[yy, z + dz, x + dx] == 0:
                    blocks[yy, z + dz, x + dx] = LEAVES
                    data[yy, z + dz, x + dx] = kind
    blocks[y:top, z, x] = LOG
    data[y:top, z, x] = kind
    return True


def _spruce(blocks, data, x, y, z, rng) -> bool:
    """WorldGenTaiga2: a trunk of 6 - 9 and a cone of leaves, wider every other layer."""
    h = int(rng.integers(6, 10))
    bare = 1 + int(rng.integers(2))
    top = y + h
    if not _free(blocks, x - 2, x + 3, y + bare, top + 1, z - 2, z + 3):
        return False
    for n, yy in enumerate(range(top, y + bare - 1, -1)):
        r = 0 if n == 0 else 1 if n == 1 else (2 if n % 2 == 0 else 1)     # the tip, then wider every other layer
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                if r > 0 and abs(dx) == r and abs(dz) == r:
                    continue
                if blocks[yy, z + dz, x + dx] == 0:
                    blocks[yy, z + dz, x + dx] = LEAVES
                    data[yy, z + dz, x + dx] = SPRUCE
    blocks[y:top, z, x] = LOG
    data[y:top, z, x] = SPRUCE
    return True


def cover(blocks: np.ndarray, data: np.ndarray, grass: int, flowers: int, rng: np.random.Generator, sea: int) -> None:
    """Tall grass and flowers on the chunk's grass blocks ([y, z, x] arrays)."""
    if grass <= 0 and flowers <= 0:
        return
    H = blocks.shape[0]
    solid = blocks != 0
    top = H - 1 - np.argmax(solid[::-1], axis=0)                      # z, x
    zz, xx = np.nonzero((np.take_along_axis(blocks, top[None], axis=0)[0] == GRASS) & (top > sea) & (top < H - 1))
    if not len(zz):
        return
    pick = rng.permutation(len(zz))[:grass + flowers]
    for n, i in enumerate(pick):
        z, x = int(zz[i]), int(xx[i])
        y = int(top[z, x]) + 1
        if n < grass:
            blocks[y, z, x], data[y, z, x] = TALL_GRASS, 1
        else:
            blocks[y, z, x] = DANDELION if rng.random() < 0.6 else ROSE
