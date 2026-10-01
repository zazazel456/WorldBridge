"""Semantic comparison of two converted BTA worlds: e.g. the output of a reference
conversion and of WorldBridge (blocks, biomes, block entities, entities ignoring UUIDs, level.dat, players).

Usage: python tools/bta_compare.py <world A> <world B>
"""
import os, sys, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np
from worldbridge import nbt
from worldbridge.java.region import JavaRegion
from worldbridge.mapview import _unpack

A, B = sys.argv[1], sys.argv[2]
maxshow = 8

def norm(t, drop=("UUID",)):
    if isinstance(t, nbt.CompoundTag):
        return tuple(sorted((k, norm(v)) for k, v in t.items() if k not in drop))
    if isinstance(t, nbt.ListTag):
        return ("L",) + tuple(norm(x) for x in t)
    if isinstance(t, (nbt.IntArrayTag, nbt.LongArrayTag, nbt.ByteArrayTag)):
        return ("A", type(t).__name__, tuple(np.asarray(t).tolist()))
    v = t.py_data
    if isinstance(v, float):
        v = round(v, 4)
    return (type(t).__name__, v)

def states(sec):
    bs = sec["block_states"]
    pal = [str(p["Name"].py_data) + ("[" + ",".join(f"{k}={v.py_data}" for k, v in sorted(p["Properties"].items())) + "]" if "Properties" in p else "") for p in bs["palette"]]
    if "data" in bs:
        bits = max(4, (len(pal) - 1).bit_length())
        idx = _unpack(np.asarray(bs["data"]), bits, 4096, False)
    else:
        idx = np.zeros(4096, int)
    return np.array(pal, dtype=object)[idx]

def biomes(sec):
    b = sec["biomes"]
    pal = [str(x.py_data) for x in b["palette"]]
    if "data" in b:
        idx = _unpack(np.asarray(b["data"]), (len(pal) - 1).bit_length(), 64, False)
    else:
        idx = np.zeros(64, int)
    return np.array(pal, dtype=object)[idx]

diffs = collections.Counter(); shown = collections.Counter(); nchunks = 0
def report(kind, msg):
    diffs[kind] += 1
    if shown[kind] < maxshow:
        shown[kind] += 1
        print(kind, msg)

for sub in ("region", "DIM-1/region", "DIM1/region"):
    da, db = os.path.join(A, sub), os.path.join(B, sub)
    if not os.path.isdir(da) and not os.path.isdir(db):
        continue
    files = sorted(set(os.listdir(da) if os.path.isdir(da) else []) | set(os.listdir(db) if os.path.isdir(db) else []))
    for fn in files:
        if not fn.endswith(".mca"): continue
        ra = JavaRegion(os.path.join(da, fn)) if os.path.exists(os.path.join(da, fn)) else None
        rb = JavaRegion(os.path.join(db, fn)) if os.path.exists(os.path.join(db, fn)) else None
        ca = set(ra.chunks()) if ra else set(); cb = set(rb.chunks()) if rb else set()
        if ca != cb: report("chunkset", f"{sub}/{fn}: {len(ca)} vs {len(cb)}")
        for lx, lz in sorted(ca & cb):
            nchunks += 1
            a = nbt.load(ra.read(lx, lz)).tag; b = nbt.load(rb.read(lx, lz)).tag
            for k in set(a.keys()) | set(b.keys()):
                if k in ("sections", "entities", "block_entities", "LastUpdate"): continue
                if norm(a.get(k)) != norm(b.get(k)) if k in a and k in b else True:
                    report("root", f"{fn} {lx},{lz} key {k}")
            sa = {int(s["Y"].py_data): s for s in a["sections"]}; sb = {int(s["Y"].py_data): s for s in b["sections"]}
            for y in sorted(set(sa) | set(sb)):
                xa, xb = states(sa[y]), states(sb[y])
                bad = np.flatnonzero(xa != xb)
                for i in bad[:3]:
                    report("block", f"{fn} {lx},{lz} y={y*16 + (i>>8)} z={(i>>4)&15} x={i&15}: {xa[i]} vs {xb[i]}")
                diffs["block_total"] += len(bad)
                ba, bb = biomes(sa[y]), biomes(sb[y])
                if (ba != bb).any(): report("biome", f"{fn} {lx},{lz} sec {y}: {ba[ba!=bb][:3]} vs {bb[ba!=bb][:3]}")
            tea = {(int(t["x"].py_data), int(t["y"].py_data), int(t["z"].py_data)): t for t in a["block_entities"]}
            teb = {(int(t["x"].py_data), int(t["y"].py_data), int(t["z"].py_data)): t for t in b["block_entities"]}
            if set(tea) != set(teb): report("te_set", f"{fn} {lx},{lz}: {sorted(set(tea)^set(teb))[:4]}")
            for p in set(tea) & set(teb):
                if norm(tea[p]) != norm(teb[p]): report("te", f"{p}: {tea[p]} \n   vs {teb[p]}")
            ea = collections.Counter(norm(e) for e in a["entities"]); eb = collections.Counter(norm(e) for e in b["entities"])
            if ea != eb:
                report("entities", f"{fn} {lx},{lz}: {len(a['entities'])} vs {len(b['entities'])} ; only A: {list((ea-eb).elements())[:1]} ; only B: {list((eb-ea).elements())[:1]}")
print("chunks compared:", nchunks)
print("DIFFS:", dict(diffs))
# level.dat and players
la = nbt.load(open(os.path.join(A, "level.dat"), "rb").read()).tag["Data"]
lb = nbt.load(open(os.path.join(B, "level.dat"), "rb").read()).tag["Data"]
for k in sorted(set(la.keys()) | set(lb.keys())):
    if k in ("LastPlayed",): continue
    if k not in la or k not in lb or norm(la[k]) != norm(lb[k]):
        print("level.dat differs:", k, str(la.get(k))[:150], "|", str(lb.get(k))[:150])
pa = sorted(os.listdir(os.path.join(A, "playerdata"))) if os.path.isdir(os.path.join(A, "playerdata")) else []
pb = sorted(os.listdir(os.path.join(B, "playerdata"))) if os.path.isdir(os.path.join(B, "playerdata")) else []
print("players", pa == pb, pa, pb)
for f in set(pa) & set(pb):
    x = nbt.load(open(os.path.join(A, "playerdata", f), "rb").read()).tag
    y = nbt.load(open(os.path.join(B, "playerdata", f), "rb").read()).tag
    if norm(x, ()) != norm(y, ()): print("player differs", f)
