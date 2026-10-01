# Prebuilt wheels

On PyPI, amulet-mutf8, amulet-nbt and amulet-leveldb exist only as source packages: installing them
would need gcc/g++ and the Python and zlib headers on the system. These wheels are built by
`tools/build_wheels.py` with Zig 0.16.0 (glibc 2.17, static zlib 1.3.1, static libc++) from the
same sources published on PyPI (versions in `requirements.lock`). They work on any x86_64 Linux from
2014 onwards without installing anything on the system. `run.sh` and the automatic installer use
them through `pip --find-links`.

To rebuild them (Python 3.11 and 3.12):

```bash
python3.11 tools/build_wheels.py --manylinux --out vendor/wheels --work /tmp/wb-build
python3.12 tools/build_wheels.py --manylinux --out vendor/wheels --work /tmp/wb-build
```

Checksums are in `SHA256SUMS`.

## Licences

- amulet-nbt, amulet-leveldb: **Amulet Team License 1.0.0** (non-commercial use; full text inside
  each wheel, in `*.dist-info/licenses/LICENSE`).
  Required Notice: Copyright Amulet Team. (https://www.amuletmc.com/)
- amulet-mutf8: MIT (© Tyler Kennedy).
- amulet-leveldb includes leveldb-mcpe (BSD 3-Clause, © The LevelDB Authors / Mojang) and zlib (zlib
  licence, © Jean-loup Gailly and Mark Adler).
