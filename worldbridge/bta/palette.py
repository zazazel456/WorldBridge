"""User-tunable choices without a single right answer: which vanilla wood a painted BTA wood colour
becomes, the wood of unpainted BTA oak and what the Drift portal becomes.  Defaults were chosen
by comparing the mean CIELAB colour of the BTA and vanilla 26.3 textures; they can be overridden
with a ``.properties`` file (see ``data/palette.example.properties``)."""

from __future__ import annotations

from typing import List, Optional

COLORS = ("white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray", "light_gray", "cyan", "purple",
          "blue", "brown", "green", "red", "black")

WOODS = ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove", "cherry", "pale_oak", "bamboo",
         "crimson", "warped", "poplar")


class Palette:
    def __init__(self):
        self.painted_wood: List[str] = ["pale_oak", "acacia", "crimson", "warped", "bamboo", "bamboo", "cherry",
                                        "poplar", "poplar", "warped", "crimson", "warped", "spruce", "bamboo",
                                        "mangrove", "dark_oak"]
        self.oak_wood = "oak"
        self.drift_portal = "minecraft:air"

    @classmethod
    def load(cls, path: Optional[str]) -> "Palette":
        p = cls()
        if not path:
            return p
        props = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line[0] in "#!":
                    continue
                for sep in ("=", ":"):
                    if sep in line:
                        k, v = line.split(sep, 1)
                        props[k.strip()] = v.strip()
                        break
        for i, c in enumerate(COLORS):
            if f"painted.{c}" in props:
                p.painted_wood[i] = props[f"painted.{c}"]
        p.oak_wood = props.get("oak", p.oak_wood)
        p.drift_portal = props.get("drift_portal", p.drift_portal)
        return p

    def wood(self, color: int) -> str:
        return self.painted_wood[color & 15]

    @staticmethod
    def planks(wood: str) -> str:
        return "minecraft:" + wood + "_planks"
