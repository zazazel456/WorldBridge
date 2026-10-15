"""The biome source of Bedrock's infinite overworld before 1.18 (Bedrock Dedicated Server 1.6 - 1.17).

The generator is a graph of operation nodes that follows the Java layer stack of 1.13 - 1.14 closely, but is data
driven (biome tags, weighted lists, small filters) and has its own temperature, ocean and edge nodes.  The random
numbers of every node are those of Java's GenLayer: a 64-bit LCG (x * (x * 6364136223846793005 + 1442695040888963407)
+ salt) started from the level seed and the node's salt.  The biomes are the same in every version from 1.6 to 1.17.

    b = BedrockBiomes(seed)
    b.area(x0, z0, w, h)    # [h, w] biome ids per block      (the 1:1 grid stored in the chunks, rows are z)
    b.area4(x0, z0, w, h)   # [h, w] biome ids per 4x4 cell   (the grid the terrain generator reads)

``seed`` is the level seed as an unsigned 32-bit number.  Biome ids are Bedrock's (bedrockdata.BIOME_IDS).
"""

from __future__ import annotations

import numpy as np

from .bedrockdata import BIOMES

# ---------------------------------------------------------------- per-biome lookup arrays (index = numeric id)
_N = 256
ID = {n: o['id'] for n, o in BIOMES.items()}
OCEAN, PLAINS, DESERT, EXTREME_HILLS, FOREST, TAIGA, SWAMP, RIVER = 0, 1, 2, 3, 4, 5, 6, 7
MUSHROOM, MUSHROOM_SHORE, BEACH, JUNGLE_EDGE, DEEP_OCEAN = 14, 15, 16, 23, 24
STONE_BEACH, COLD_BEACH, MESA, SUNFLOWER_PLAINS = 25, 26, 37, 129
FROZEN_RIVER = 11

_TAG = {}
_TEMP = np.zeros(_N, np.float32)
_TYPE = np.full(_N, 0x12, np.int64)
_SNOW = np.zeros(_N, bool)
for _n, _o in BIOMES.items():
    for _t in _o['tags']:
        _TAG.setdefault(_t, np.zeros(_N, bool))[_o['id']] = True
    _TEMP[_o['id']] = np.float32(_o['temp'])
    _TYPE[_o['id']] = _o['type']
    _SNOW[_o['id']] = _o['snow'] > 0


def tag(name):
    return _TAG.get(name, np.zeros(_N, bool))


T_OCEAN, T_DEEP = tag('ocean'), tag('deep')
SHALLOW = T_OCEAN & ~T_DEEP                       # "shallow ocean" lists of the river-init / island nodes
T_MUTATED, T_HILLS = tag('mutated'), tag('hills')


def _ix(a):
    return np.clip(a, 0, _N - 1)


# ---------------------------------------------------------------- the LCG
_A = np.uint64(6364136223846793005)
_C = np.uint64(1442695040888963407)
_M = 0xFFFFFFFFFFFFFFFF


def _u(v):
    return np.uint64(int(v) & _M)


def step(s, v):
    """s * (s * A + C) + v   (wraps modulo 2^64; works on uint64 arrays)"""
    s = np.asarray(s, np.uint64)
    return s * (s * _A + _C) + np.asarray(v, np.uint64)


def _step_int(s, v):
    return (s * ((s * 6364136223846793005 + 1442695040888963407) & _M) + v) & _M


def layer_salt(salt):
    """The node constant: three LCG steps of the node's small salt with itself."""
    s = salt & _M
    for _ in range(3):
        s = _step_int(s, salt & _M)
    return s


def node_seed(world_seed, salt):
    """Per-node start value: three LCG steps of the world seed, each adding layer_salt(salt)."""
    ls = layer_salt(salt)
    st = world_seed & _M
    for _ in range(3):
        st = _step_int(st, ls)
    return st


def chunk_seed(ss, x, z):
    """Random state of cell (x, z):  ss = step(st, 0);  s = ss + x;  s = step(s, z);  step(s, x);  step(s, z)."""
    xs = x.astype(np.int64).view(np.uint64)
    zs = z.astype(np.int64).view(np.uint64)
    cs = np.asarray(ss, np.uint64) + xs
    cs = step(cs, zs)
    cs = step(cs, xs)
    return step(cs, zs)


def first_int(cs, mod):
    """(cs >> 24) mod `mod` with the sign fixed up (a non-negative result)."""
    return (cs.view(np.int64) >> 24) % mod


def grid(x, z, w, h):
    xx = np.empty((h, w), np.int64)
    zz = np.empty((h, w), np.int64)
    xx[:] = np.arange(x, x + w, dtype=np.int64)
    zz[:] = np.arange(z, z + h, dtype=np.int64)[:, None]
    return xx, zz


def weighted(cs, entries):
    """Weighted choice among [(value, weight)] ; one entry needs no random number."""
    if len(entries) == 1:
        return np.full(cs.shape, entries[0][0], np.int64)
    total = sum(w for _, w in entries)
    r = first_int(cs, total)
    out = np.full(cs.shape, entries[-1][0], np.int64)
    acc = 0
    for v, w in entries:
        acc += w
        out = np.where((r < acc) & (out == entries[-1][0]) & (r >= acc - w), v, out)
    return out


# ---------------------------------------------------------------- nodes
class Node:
    def __init__(self, fn, salt, p=None, p2=None, **kw):
        self.fn, self.salt, self.p, self.p2 = fn, salt, p, p2
        self.__dict__.update(kw)
        self.st = self.ss = 0

    def seed(self, ws):
        for q in (self.p, self.p2):
            if q is not None:
                q.seed(ws)
        if self.__dict__.get('unseeded'):
            self.st = self.ss = 0              # never reached by the game's init(): its start seed stays zero
        else:
            self.st = node_seed(ws, self.salt)
            self.ss = _step_int(self.st, 0)

    def area(self, x, z, w, h):
        return self.fn(self, x, z, w, h)

    def cs(self, x, z, w, h):
        xx, zz = grid(x, z, w, h)
        return chunk_seed(self.ss, xx, zz)

    def nxt(self, cs):
        return step(cs, np.uint64(self.st))


def _nb(n, x, z, w, h):
    """3x3 neighbourhood: padded parent area and its centre."""
    p = n.p.area(x - 1, z - 1, w + 2, h + 2)
    return p, p[1:-1, 1:-1]


def _cross(p):
    """north, east, west, south"""
    return p[:-2, 1:-1], p[1:-1, 2:], p[1:-1, :-2], p[2:, 1:-1]


def _corners(p):
    """top-left, top-right, bottom-left, bottom-right"""
    return p[:-2, :-2], p[:-2, 2:], p[2:, :-2], p[2:, 2:]


# -- land / sea (0 / 1) -------------------------------------------------------------------------------------------
def island(n, x, z, w, h):
    xx, zz = grid(x, z, w, h)
    out = (first_int(chunk_seed(n.ss, xx, zz), 10) == 0).astype(np.int64)
    out[(xx == 0) & (zz == 0)] = 1
    return out


def _zoom(n, x, z, w, h):
    fuzzy = n.fuzzy
    px, pz = x >> 1, z >> 1
    pw, ph = ((x + w) >> 1) - px + 1, ((z + h) >> 1) - pz + 1
    p = n.p.area(px, pz, pw + 1, ph + 1)
    a, b, c, d = p[:-1, :-1], p[:-1, 1:], p[1:, :-1], p[1:, 1:]
    ii, jj = grid(0, 0, pw, ph)
    cs = chunk_seed(n.ss, (ii + px) * 2, (jj + pz) * 2)
    r1 = first_int(cs, 2)
    cs = n.nxt(cs)
    r2 = first_int(cs, 2)
    cs = n.nxt(cs)
    r3 = first_int(cs, 4)
    o01 = np.where(r1 == 1, c, a)
    o10 = np.where(r2 == 1, b, a)
    rnd = np.where(r3 == 0, a, np.where(r3 == 1, b, np.where(r3 == 2, c, d)))
    if fuzzy:
        o11 = rnd
    else:
        cv00 = (a == b).astype(np.int64) + (a == c) + (a == d)
        cv10 = (b == c).astype(np.int64) + (b == d)
        cv01 = (c == d).astype(np.int64)
        o11 = np.where((cv00 > cv10) & (cv00 > cv01), a, np.where(cv10 > cv00, b, np.where(cv01 > cv00, c, rnd)))
    same = (a == b) & (a == c) & (a == d)
    o01, o10, o11 = (np.where(same, a, o) for o in (o01, o10, o11))
    buf = np.empty((ph * 2, pw * 2), np.int64)
    buf[0::2, 0::2] = a
    buf[1::2, 0::2] = o01
    buf[0::2, 1::2] = o10
    buf[1::2, 1::2] = o11
    return buf[(z & 1):(z & 1) + h, (x & 1):(x & 1) + w]


def add_island(n, x, z, w, h):
    p, c = _nb(n, x, z, w, h)
    tl, tr, bl, br = _corners(p)
    cs = n.cs(x, z, w, h)
    s = cs
    cnt = np.zeros(c.shape, np.int64)
    for nb in (tl, tr, bl, br):
        s = np.where(nb != 0, n.nxt(s), s)
        cnt += nb != 0
    grow = (c == 0) & (cnt > 0)
    out = np.where(grow, (first_int(s, 3) == 0).astype(np.int64), c)
    sink = (c != 0) & (cnt < 4) & (first_int(cs, 5) == 0)
    return np.where(sink, 0, out)


def remove_too_much_ocean(n, x, z, w, h):
    p, c = _nb(n, x, z, w, h)
    ns = _cross(p)
    all0 = (c == 0) & (ns[0] == 0) & (ns[1] == 0) & (ns[2] == 0) & (ns[3] == 0)
    return np.where(all0 & (first_int(n.cs(x, z, w, h), 2) == 0), 1, c)


# -- climate values: (temperature class << 8) | special/land byte ----------------------------------------------------
def add_snow(n, x, z, w, h):
    v = n.p.area(x, z, w, h)
    r = first_int(n.cs(x, z, w, h), 6)
    t = np.where(r == 0, 4, np.where(r == 1, 3, 1))
    return np.where(v != 0, (t << 8) | 1, 0)


def add_island_temp(n, x, z, w, h):
    p, c = _nb(n, x, z, w, h)
    tl, tr, bl, br = _corners(p)
    cs = n.cs(x, z, w, h)
    lo, hi = c & 255, c >> 8
    # land next to sea: may sink (a frozen land without special flag survives)
    anysea = ((tl & 255) == 0) | ((tr & 255) == 0) | ((bl & 255) == 0) | ((br & 255) == 0)
    special = ((lo - 2) & 255) < 16
    sink = (lo != 0) & anysea & (first_int(cs, 5) == 0)
    keep = (hi == 4) & ~special
    land_out = np.where(sink & ~keep, 0, c)
    # sea next to land: reservoir choice among the land neighbours, then a 1/3 chance (or a frozen non-special pick)
    s = cs
    cnt = np.ones(c.shape, np.int64)
    ch_lo = np.ones(c.shape, np.int64)
    ch_hi = np.ones(c.shape, np.int64)
    any_land = np.zeros(c.shape, bool)
    for nb in (tl, tr, bl, br):
        m = (nb & 255) != 0
        r = first_int(s, cnt)
        s = np.where(m, n.nxt(s), s)
        take = m & (r == 0)
        ch_lo = np.where(take, nb & 255, ch_lo)
        ch_hi = np.where(take, nb >> 8, ch_hi)
        cnt = cnt + m
        any_land |= m
    adopt = (first_int(s, 3) == 0) | ((ch_hi == 4) & (((ch_lo - 2) & 255) >= 16))
    sea_out = np.where(any_land & adopt, (ch_hi << 8) | ch_lo, 0)
    return np.where(lo != 0, land_out, sea_out)


def edge_cool_warm(n, x, z, w, h):
    p, c = _nb(n, x, z, w, h)
    ns = _cross(p)
    hi, lo = c >> 8, c & 255
    cold = np.zeros(c.shape, bool)
    for nb in ns:
        cold |= ((nb >> 8) == 3) | ((nb >> 8) == 4)
    return np.where((lo != 0) & (hi == 1), (np.where(cold, 0, 1) << 8) | lo, c)


def edge_heat_ice(n, x, z, w, h):
    p, c = _nb(n, x, z, w, h)
    ns = _cross(p)
    hi, lo = c >> 8, c & 255
    warm = np.zeros(c.shape, bool)
    for nb in ns:
        warm |= ((nb & 255) != 0) & ((nb >> 8) < 2)
    return np.where((lo != 0) & (hi == 4) & warm, (3 << 8) | lo, c)


def edge_special(n, x, z, w, h):
    v = n.p.area(x, z, w, h)
    cs = n.cs(x, z, w, h)
    hit = (v & 255 != 0) & (first_int(cs, 13) == 0)
    lo2 = first_int(n.nxt(cs), 15) + 2
    return np.where(hit, (v & 0xFF00) | lo2, v)


# -- biomes -------------------------------------------------------------------------------------------------------
_REG_ORDER = ['desert', 'savanna', 'mesa_plateau', 'mesa_plateau_stone', 'forest', 'roofed_forest', 'extreme_hills',
              'taiga',
              'plains', 'birch_forest', 'swampland', 'ice_plains', 'cold_taiga', 'jungle', 'mega_taiga']


def _climate_lists(generator=1):
    """normal[c], special[c]: weighted biome lists per temperature class c (0 medium, 1 warm, 3 cold, 4 frozen)."""
    normal = [[] for _ in range(5)]
    special = [[] for _ in range(5)]
    for name, o in sorted(BIOMES.items(), key=lambda kv: kv[1]['id']):
        if not o['climates'] or 'ocean' in o['tags']:
            continue
        if generator != 1 and 'no_legacy_worldgen' in o['tags']:
            continue
        dst = special if 'rare' in o['tags'] else normal
        for c, wgt in o['climates']:
            dst[c].append((name, wgt))
    for lst in normal + special:
        lst.sort(key=lambda e: _REG_ORDER.index(e[0]))
    return ([[(ID[b], w) for b, w in l] for l in normal], [[(ID[b], w) for b, w in l] for l in special])


def biome_init(n, x, z, w, h):
    v = n.p.area(x, z, w, h)
    cs = n.cs(x, z, w, h)
    lo, hi = v & 255, v >> 8
    out = np.full(v.shape, PLAINS, np.int64)
    out[lo == 0] = OCEAN
    sp_mask = ((lo - 2) & 255) < 16
    for c in range(5):
        for is_sp, lists in ((True, n.special), (False, n.normal)):
            lst = lists[c]
            if not lst:
                continue
            m = (lo != 0) & (hi == c)
            if is_sp:
                m &= sp_mask
            else:
                m &= ~sp_mask | (len(n.special[c]) == 0)
            if m.any():
                out[m] = weighted(cs, lst)[m]
    return out


def add_mushroom(n, x, z, w, h):
    p, c = _nb(n, x, z, w, h)
    oc = T_OCEAN[_ix(c)]
    for q in _corners(p):
        oc = oc & T_OCEAN[_ix(q)]
    return np.where(oc & (first_int(n.cs(x, z, w, h), 100) == 0), MUSHROOM, c)


def promote_center(n, x, z, w, h):
    p, c = _nb(n, x, z, w, h)
    m = c == OCEAN
    for q in _cross(p):
        m &= q == OCEAN
    return np.where(m, DEEP_OCEAN, c)


def rare_spot(n, x, z, w, h):
    v = n.p.area(x, z, w, h)
    return np.where((v == n.src) & (first_int(n.cs(x, z, w, h), n.mod) == 0), n.dst, v)


def river_init(n, x, z, w, h):
    v = n.p.area(x, z, w, h)
    return np.where(SHALLOW[_ix(v)], 0, first_int(n.cs(x, z, w, h), 299999) + 2)


def _reduce(a):
    return np.where(a >= 2, (a & 1) | 2, a)


def river(n, x, z, w, h):
    p, c = _nb(n, x, z, w, h)
    r = _reduce(p)
    cc = r[1:-1, 1:-1]
    diff = np.zeros(c.shape, bool)
    for q in _cross(r):
        diff |= q != cc
    return diff.astype(np.int64)


def smooth(n, x, z, w, h):
    p, c = _nb(n, x, z, w, h)
    nn, ee, ww, ss = _cross(p)
    both = (ww == ee) & (nn == ss)
    pick = np.where(first_int(n.cs(x, z, w, h), 2) == 0, ww, nn)
    out = np.where(both, pick, np.where(ww == ee, ww, np.where(nn == ss, nn, c)))
    return out


# -- edge transformations (small data-driven filters on the four neighbours) -----------------------------------------
def _t(name):
    return tag(name)


def _pred_cold_warm(nb):
    t = _TEMP[_ix(nb)]
    return (t < np.float32(0.2)) | (t >= np.float32(1.0))


def _pred_not_mesa_plateau(nb):
    i = _ix(nb)
    return ~_t('plateau')[i] | ~_t('mesa')[i] | T_MUTATED[i]


def _pred_not_taiga(nb):
    return ~_t('taiga')[_ix(nb)]


def _pred_ice_plains(nb):
    i = _ix(nb)
    return _t('ice_plains')[i] & ~T_MUTATED[i]


def _pred_swamp_to_plains(nb):
    i = _ix(nb)
    ok = ~T_MUTATED[i] & ~T_HILLS[i]
    return (_t('desert')[i] & ok) | (_t('taiga')[i] & _t('cold')[i] & ok) | (_t('ice_plains')[i] & ~T_MUTATED[i])


def _pred_swamp_to_jungle_edge(nb):
    i = _ix(nb)
    return _t('jungle')[i] & ~T_MUTATED[i] & ~_t('edge')[i] & ~T_HILLS[i]


def _pred_jungle_edge(nb):
    i = _ix(nb)
    f = (~_t('forest')[i] | _t('cold')[i] | T_HILLS[i] | _t('mega')[i] | T_MUTATED[i] | _t('birch')[i])
    return ~_t('jungle')[i] & ~T_OCEAN[i] & f


def _pred_desert_from_mesa(nb):
    i = _ix(nb)
    return ~_t('mesa')[i] & ~T_OCEAN[i]


PRE_HILLS_EDGE = {                                   # centre -> [(replacement, neighbour predicate)]
    # 3: [(20, _pred_cold_warm)] -- extreme hills -> edge: its filter (is_temperature_value) is not accepted: no rule
    38: [(37, _pred_not_mesa_plateau)],
    39: [(37, _pred_not_mesa_plateau)],
    32: [(5, _pred_not_taiga)],
    2: [(34, _pred_ice_plains)],
    6: [(1, _pred_swamp_to_plains), (23, _pred_swamp_to_jungle_edge)],
}
POST_SHORE_EDGE = {37: [(2, _pred_desert_from_mesa)], 38: [(2, _pred_desert_from_mesa)]}
for _i in range(_N):
    if _TYPE[_i] == 7 and _i in set(o['id'] for o in BIOMES.values()):
        POST_SHORE_EDGE[_i] = [(JUNGLE_EDGE, _pred_jungle_edge)]




def filtered_transformation(n, x, z, w, h):
    p, c = _nb(n, x, z, w, h)
    ns = _cross(p)
    out = c.copy()
    for cid, rules in n.rules.items():
        m = c == cid
        if not m.any():
            continue
        done = np.zeros(c.shape, bool)
        for target, pred in rules:
            hit = np.zeros(c.shape, bool)
            for q in ns:
                hit |= pred(q)
            sel = m & hit & ~done
            out = np.where(sel, target, out)
            done |= sel
    return out


def region_hills(n, x, z, w, h):
    p, c = _nb(n, x, z, w, h)
    b = n.p2.area(x, z, w, h)
    cs = n.cs(x, z, w, h)
    rem = np.where(b >= 2, (b - 2) % 29 + 2, b)
    mut_cond = (b >= 2) & (rem == 3) & ~T_MUTATED[_ix(c)]
    return _hills_impl(n, c, p, b, cs, rem, mut_cond)


def _hills_impl(n, c, p, b, cs, rem, mut_cond):
    ci = _ix(c)
    flag = rem == 2
    c3 = first_int(cs, 3) == 0
    proceed = flag | c3
    cs2 = n.nxt(cs)
    deep_center = T_OCEAN[ci] & T_DEEP[ci]
    cs3 = n.nxt(cs2)
    run = proceed & (~deep_center | (first_int(cs2, 3) == 0))
    cs_h = np.where(deep_center, cs3, cs2)
    # hills transformation (weighted)
    hill = c.copy()
    for cid, entries in HILLS_OF.items():
        m = run & (c == cid)
        if m.any():
            hill = np.where(m, weighted(cs_h, entries), hill)
    # flagged: mutate the hill biome
    mhill = np.full(c.shape, -1, np.int64)
    for hid, entries in MUTATE_OF.items():
        m = hill == hid
        if m.any():
            mhill = np.where(m, entries[0][0] if len(entries) == 1 else weighted(cs_h, entries), mhill)
    hill2 = np.where(flag & (hill != c), np.where(mhill >= 0, mhill, c), hill)
    # four neighbours of the same biome type as the centre
    cnt = np.zeros(c.shape, np.int64)
    for q in _cross(p):
        cnt += _TYPE[_ix(q)] == _TYPE[ci]
    hill_out = np.where((hill2 != c) & (cnt > 2), hill2, c)
    out = np.where(run, hill_out, c)
    # mutate branch (a 1/29 share of the river noise values)
    mut = np.full(c.shape, -1, np.int64)
    for cid, entries in MUTATE_OF.items():
        m = c == cid
        if m.any():
            mut = np.where(m, entries[0][0] if len(entries) == 1 else weighted(cs, entries), mut)
    return np.where(mut_cond, np.where(mut >= 0, mut, c), out)


BIOMES_BY_ID = {o['id']: o for o in BIOMES.values()}
HILLS_OF = {o['id']: [(ID[b], w) for b, w in o['hills']] for o in BIOMES.values() if o['hills']}
MUTATE_OF = {o['id']: [(ID[b], w) for b, w in o['mutate']] for o in BIOMES.values() if o['mutate']}


def add_biome_island(n, x, z, w, h):
    p, c = _nb(n, x, z, w, h)
    tl, tr, bl, br = _corners(p)
    cs = n.cs(x, z, w, h)
    sh = SHALLOW[_ix(c)]
    cors = (tl, tr, bl, br)
    shc = [SHALLOW[_ix(q)] for q in cors]
    # shallow-sea centre with a non-shallow corner: reservoir pick, accepted with 1/3 (always when it is a forest)
    s = cs
    cnt = np.ones(c.shape, np.int64)
    ch = np.full(c.shape, PLAINS, np.int64)
    anyl = np.zeros(c.shape, bool)
    for q, sq in zip(cors, shc):
        m = ~sq
        r = first_int(s, cnt)
        s = np.where(m, n.nxt(s), s)
        ch = np.where(m & (r == 0), q, ch)
        cnt = cnt + m
        anyl |= m
    grow = sh & anyl & ((first_int(s, 3) == 0) | (ch == FOREST))
    # other centre with a shallow-sea corner: may sink (forests never do) into the first such corner's biome
    anysea = shc[0] | shc[1] | shc[2] | shc[3]
    sink = ~sh & anysea & (first_int(cs, 5) == 0) & (c != FOREST)
    first_sea = np.where(shc[0], tl, np.where(shc[1], tr, np.where(shc[2], bl, br)))
    return np.where(grow, ch, np.where(sink, first_sea, c))


def _shore_map():
    tgt = np.full(_N, BEACH, np.int64)
    for o in BIOMES.values():
        i, tags = o['id'], o['tags']
        if i == MUSHROOM:
            tgt[i] = MUSHROOM_SHORE
        elif o['type'] == 7:
            pass
        elif i in (3, 34, 20):
            tgt[i] = STONE_BEACH
        elif o['snow'] > 0 and 'ocean' not in tags:
            tgt[i] = COLD_BEACH
        elif i in (37, 38) or i in (RIVER, SWAMP) or 'ocean' in tags:
            tgt[i] = i
    return tgt


SHORE = _shore_map()


def shore(n, x, z, w, h):
    p, c = _nb(n, x, z, w, h)
    oc = np.zeros(c.shape, bool)
    for q in _cross(p):
        oc |= T_OCEAN[_ix(q)]
    return np.where(oc, SHORE[_ix(c)], c)


def river_mixer(n, x, z, w, h):
    b = n.p.area(x, z, w, h)
    r = n.p2.area(x, z, w, h)
    bi = _ix(b)
    new = np.where(b == 12, FROZEN_RIVER, np.where((b == MUSHROOM) | (b == MUSHROOM_SHORE), MUSHROOM_SHORE,
                                                  np.where(T_OCEAN[bi], b, RIVER)))
    return np.where(r != 0, new, b)


# -- ocean ---------------------------------------------------------------------------------------------------------
def ocean_temperature(n, x, z, w, h):
    r = first_int(n.cs(x, z, w, h), 100)
    return np.where(r < 8, 1, np.where(r < 40, 2, np.where(r < 68, 0, np.where(r < 95, 3, 4))))


def ocean_edge(n, x, z, w, h):
    p, c = _nb(n, x, z, w, h)
    ns = _cross(p)
    near_warm = (ns[0] == 1) | (ns[1] == 1) | (ns[2] == 1) | (ns[3] == 1)
    near_froz = (ns[0] == 4) | (ns[1] == 4) | (ns[2] == 4) | (ns[3] == 4)
    return np.where(c == 4, np.where(near_warm, 0, 4), np.where(c == 1, np.where(near_froz, 0, 1), c))


_OCEAN_SHALLOW = np.array([0, 40, 42, 44, 46])
_OCEAN_DEEP = np.array([24, 40, 43, 45, 47])


def ocean_mixer(n, x, z, w, h):
    b = n.p.area(x, z, w, h)
    t = n.p2.area(x, z, w, h)
    return np.where(b == OCEAN, _OCEAN_SHALLOW[t], np.where(b == DEEP_OCEAN, _OCEAN_DEEP[t], b))


# -- the 1:4 -> 1:1 zoom (the 1.14 "voronoi": four jittered cell centres) --------------------------------------------
_F = np.float32


def voronoi(n, x, z, w, h):
    x -= 2
    z -= 2
    px, pz = x >> 2, z >> 2
    pw, ph = ((x + w) >> 2) - px + 2, ((z + h) >> 2) - pz + 2
    p = n.p.area(px, pz, pw, ph)
    ii, jj = grid(0, 0, pw - 1, ph - 1)
    gx, gz = ii + px, jj + pz

    def jit(cx, cz, ox, oz):
        cs = chunk_seed(n.ss, cx * 4, cz * 4)
        a = first_int(cs, 1024).astype(np.float32)
        b = first_int(n.nxt(cs), 1024).astype(np.float32)
        k, half, c36 = _F(0.0009765625), _F(-0.5), _F(3.6)
        return ((a * k + half) * c36 + _F(ox)).astype(np.float32), ((b * k + half) * c36 + _F(oz)).astype(np.float32)

    c0 = jit(gx, gz, 0, 0)
    c1 = jit(gx + 1, gz, 4, 0)
    c2 = jit(gx, gz + 1, 0, 4)
    c3 = jit(gx + 1, gz + 1, 4, 4)
    v0, v1, v2, v3 = p[:-1, :-1], p[:-1, 1:], p[1:, :-1], p[1:, 1:]
    out = np.empty((4 * (ph - 1), 4 * (pw - 1)), np.int64)
    for j in range(4):
        for i in range(4):
            fi, fj = _F(i), _F(j)
            d = []
            for jx, jz in (c0, c1, c2, c3):
                dx = (jx - fi).astype(np.float32)
                dz = (jz - fj).astype(np.float32)
                d.append((dx * dx + dz * dz).astype(np.float32))
            d0, d1, d2, d3 = d
            v = np.where((d0 < d1) & (d0 < d2) & (d0 < d3), v0,
                         np.where((d1 < d0) & (d1 < d2) & (d1 < d3), v1,
                                  np.where((d2 < d0) & (d2 < d1) & (d2 < d3), v2, v3)))
            out[j::4, i::4] = v
    ox, oz = x - px * 4, z - pz * 4
    return out[oz:oz + h, ox:ox + w]


# ---------------------------------------------------------------- the graph
HZ = 2


def zoom_n(p, base, count, unseeded=False):
    """The graph builder's zoom helper: `count` voting zooms that all use the salt base + 1."""
    for _ in range(count):
        p = Node(_zoom, base + 1, p, fuzzy=False, unseeded=unseeded)
    return p


def build_graph(generator=1):
    N = Node
    normal, special = _climate_lists(generator)
    p = N(island, 1)
    p = N(_zoom, 2000, p, fuzzy=True)
    p = N(add_island, 1, p)
    p = N(_zoom, 2001, p, fuzzy=False)
    p = N(add_island, 2, p)
    p = N(add_island, 50, p)
    p = N(add_island, 70, p)
    p = N(remove_too_much_ocean, 2, p)
    p = N(add_snow, 2, p)
    p = N(add_island_temp, 3, p)
    p = N(edge_cool_warm, 2, p)
    p = N(edge_heat_ice, 2, p)
    p = N(edge_special, 3, p)
    p = N(_zoom, 2002, p, fuzzy=False)
    p = N(_zoom, 2003, p, fuzzy=False)
    p = N(add_island_temp, 4, p)
    p = N(biome_init, 200, p, normal=normal, special=special)
    p = N(add_mushroom, 5, p)
    deep = N(promote_center, 4, p)
    b = N(rare_spot, 1001, deep, src=21, dst=48, mod=10)                      # jungle -> bamboo jungle
    b = zoom_n(b, 1000, 2)                                    # the helper reuses salt 1001 for each step
    b = N(filtered_transformation, 1000, b, rules=PRE_HILLS_EDGE)
    rinit = N(river_init, 100, deep)
    hz = zoom_n(rinit, 1000, HZ, unseeded=True)           # RegionHills never seeds its noise input
    b = N(region_hills, 1000, b, hz)
    b = N(rare_spot, 1001, b, src=PLAINS, dst=SUNFLOWER_PLAINS, mod=57)
    b = N(_zoom, 1000, b, fuzzy=False)
    b = N(add_biome_island, 3, b)
    b = N(_zoom, 1001, b, fuzzy=False)
    b = N(shore, 1000, b)
    b = N(filtered_transformation, 1000, b, rules=POST_SHORE_EDGE)
    if generator == 1:
        b = N(_zoom, 1002, b, fuzzy=False)
        b = N(_zoom, 1003, b, fuzzy=False)
    b = N(smooth, 1000, b)
    r = zoom_n(zoom_n(rinit, 1000, 2), 1000, 4 if generator == 1 else 2)
    r = N(smooth, 1000, N(river, 1, r))
    mix = N(river_mixer, 100, b, r)
    o = N(ocean_edge, 2, N(ocean_temperature, 2))
    o = zoom_n(o, 2001, 6)
    mix = N(ocean_mixer, 100, mix, o)
    return mix, N(voronoi, 10, mix)


class BedrockBiomes:
    def __init__(self, seed: int, generator: int = 1):
        self.seed = int(seed) & 0xFFFFFFFF                # the level seed is an unsigned 32-bit value
        self.mix, self.vor = build_graph(generator)
        self.vor.seed(self.seed)

    def area4(self, x0, z0, w, h):
        """[h, w] biome ids of the 4x4 cells (cell = block >> 2): the grid before the final voronoi zoom."""
        return self.mix.area(x0, z0, w, h)

    def area(self, x0, z0, w, h):
        """[h, w] biome ids of the blocks (x0, z0 .. x0 + w - 1, z0 + h - 1); rows are z."""
        return self.vor.area(x0, z0, w, h)

    def chunk(self, cx, cz):
        """The 16 x 16 biomes of a chunk as stored in Data2D: index z * 16 + x of the flattened array."""
        return self.vor.area(cx * 16, cz * 16, 16, 16)

    def chunk4(self, cx, cz):
        """The 4 x 4 cells of a chunk read by the terrain generator (cell (i, j) = blocks 4i..4i+3 of the chunk)."""
        return self.mix.area(cx * 4, cz * 4, 4, 4)
