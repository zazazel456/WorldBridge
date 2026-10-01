import numpy as np

from worldbridge import nbt
from worldbridge.model import NumericChunk, WorldInfo, WorldSource


def make_chunk(cx, cz, seed=0):
    rng = np.random.default_rng(abs(seed * 7 + cx * 1000 + cz * 31 + 100000))
    c = NumericChunk(cx, cz, 256)
    c.blocks[0] = 7
    c.blocks[1:60] = 1
    c.blocks[60:63] = 3
    c.blocks[63] = 2
    ore = rng.random((59, 16, 16)) < 0.03
    c.blocks[1:60][ore] = 56
    c.blocks[64, 5, 5] = 35
    c.data[64, 5, 5] = 14
    c.blocks[64, 6, 6] = 54  # chest
    c.data[64, 6, 6] = 2
    c.biomes = np.full((16, 16), 4, np.uint8)
    c.tile_entities.append(nbt.CompoundTag({
        "id": nbt.StringTag("Chest"), "x": nbt.IntTag(cx * 16 + 6), "y": nbt.IntTag(64), "z": nbt.IntTag(cz * 16 + 6),
        "Items": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(264), "Count": nbt.ByteTag(5),
                                                "Damage": nbt.ShortTag(0), "Slot": nbt.ByteTag(0)})], 10),
    }))
    c.entities.append(nbt.CompoundTag({
        "id": nbt.StringTag("Pig"),
        "Pos": nbt.ListTag([nbt.DoubleTag(cx * 16 + 8.5), nbt.DoubleTag(65.0), nbt.DoubleTag(cz * 16 + 8.5)], 6),
        "Motion": nbt.ListTag([nbt.DoubleTag(0), nbt.DoubleTag(0), nbt.DoubleTag(0)], 6),
        "Rotation": nbt.ListTag([nbt.FloatTag(0), nbt.FloatTag(0)], 5),
        "Health": nbt.ShortTag(10),
    }))
    return c


class SyntheticWorld(WorldSource):
    def __init__(self, radius=2, dims=(0,)):
        self.info = WorldInfo()
        self.info.level = nbt.CompoundTag({
            "LevelName": nbt.StringTag("Test World"), "RandomSeed": nbt.LongTag(12345),
            "SpawnX": nbt.IntTag(8), "SpawnY": nbt.IntTag(64), "SpawnZ": nbt.IntTag(8),
            "GameType": nbt.IntTag(1), "Time": nbt.LongTag(1000), "generatorName": nbt.StringTag("default"),
        })
        self.info.players["host"] = nbt.CompoundTag({
            "Pos": nbt.ListTag([nbt.DoubleTag(8.5), nbt.DoubleTag(65.0), nbt.DoubleTag(8.5)], 6),
            "Inventory": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(276), "Count": nbt.ByteTag(1),
                                                       "Damage": nbt.ShortTag(0), "Slot": nbt.ByteTag(0)})], 10),
            "Dimension": nbt.IntTag(0),
        })
        self.radius = radius
        self.dims = dims

    def dimensions(self):
        return list(self.dims)

    def chunk_coords(self, dim):
        r = self.radius
        return [(x, z) for x in range(-r, r) for z in range(-r, r)]

    def read_chunk(self, dim, cx, cz):
        return make_chunk(cx, cz, seed=dim)
