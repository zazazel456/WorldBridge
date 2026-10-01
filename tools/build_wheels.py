#!/usr/bin/env python3
"""Build the Amulet packages that PyPI publishes only as source code, without a system compiler.

amulet-mutf8, amulet-nbt and amulet-leveldb have no Linux wheels on PyPI, so a plain
``pip install`` needs gcc/g++, the Python headers and zlib headers on the machine.  This
script compiles them with Zig (a self-contained C/C++ toolchain installed from PyPI into the
work folder) against glibc 2.17, with a static zlib and a static C++ runtime, so the result
runs on any Linux distribution released since ~2014 (manylinux2014).

It is used
  * by the maintainers to produce ``vendor/wheels`` (``--manylinux``), and
  * by ``run.sh`` as a fallback when no prebuilt wheel matches the machine.

Everything (Zig, zlib, build caches) stays inside ``--work``; nothing is written elsewhere.

    python tools/build_wheels.py --out vendor/wheels --work /tmp/wb-build --manylinux
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)

PACKAGES = ("amulet-mutf8", "amulet-nbt", "amulet-leveldb")
GLIBC = "2.17"

ZIG = "ziglang==0.16.0"
ZIG_HASHES = (
    "9fcda73f62b851dd72a54b710ad40a209896db14cfb13649e62191243556342b",  # manylinux x86_64
    "e27d409812b11e0fb89ed0200cf2e55b6464d43f9461553104e4a4f9a94a1fd5",  # manylinux aarch64
)
ZLIB_URL = "https://github.com/madler/zlib/releases/download/v1.3.1/zlib-1.3.1.tar.gz"
ZLIB_SHA256 = "9a93b2b7dfdac77ceba5a558a580e74667dd6fede4585b91eefb60f03b72df23"
ZLIB_SOURCES = ("adler32", "compress", "crc32", "deflate", "gzclose", "gzlib", "gzread", "gzwrite",
                "infback", "inffast", "inflate", "inftrees", "trees", "uncompr", "zutil")


def log(msg: str) -> None:
    print(f"[build_wheels] {msg}", file=sys.stderr, flush=True)


def pinned_versions() -> dict:
    out = {}
    with open(os.path.join(APP, "requirements.lock"), encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^\s*([A-Za-z0-9_.-]+)==([^\s;#]+)", line)
            if m:
                out[m.group(1).lower()] = m.group(2)
    return out


def arch() -> str:
    m = platform.machine().lower()
    return {"amd64": "x86_64", "arm64": "aarch64"}.get(m, m)


def install_zig(python: str, work: str, env: dict) -> str:
    zig_dir = os.path.join(work, "zig")
    if not os.path.isdir(os.path.join(zig_dir, "ziglang")):
        log(f"installo {ZIG} (compilatore C/C++ portatile) in {zig_dir}")
        req = os.path.join(work, "zig-requirements.txt")
        with open(req, "w", encoding="utf-8") as f:
            f.write(ZIG + "".join(f" --hash=sha256:{h}" for h in ZIG_HASHES) + "\n")
        subprocess.run([python, "-m", "pip", "install", "--no-user", "--no-deps", "--no-cache-dir",
                        "--require-hashes", "--target", zig_dir, "-r", req], check=True, env=env)
    return zig_dir


def write_wrappers(python: str, zig_dir: str, work: str, triple: str) -> tuple:
    bindir = os.path.join(work, "bin")
    os.makedirs(bindir, exist_ok=True)
    paths = []
    for name, mode in (("cc", "cc"), ("c++", "c++"), ("ar", "ar")):
        target = [] if mode == "ar" else ["-target", triple]
        path = os.path.join(bindir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n"
                    f"PYTHONPATH={shlex.quote(zig_dir)} exec {shlex.quote(python)} -m ziglang {mode} "
                    f"{' '.join(target)} \"$@\"\n")
        os.chmod(path, 0o755)
        paths.append(path)
    return tuple(paths)


def build_zlib(work: str, cc: str, ar: str, env: dict) -> str:
    libdir = os.path.join(work, "zlib", "lib")
    lib = os.path.join(libdir, "libz.a")
    if os.path.isfile(lib):
        return libdir
    log("compilo zlib 1.3.1 (statica)")
    data = urllib.request.urlopen(ZLIB_URL, timeout=120).read()
    if hashlib.sha256(data).hexdigest() != ZLIB_SHA256:
        raise SystemExit("checksum di zlib non valido")
    src = os.path.join(work, "zlib", "src")
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(src, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(src)
    zsrc = os.path.join(src, "zlib-1.3.1")
    objs = []
    for name in ZLIB_SOURCES:
        obj = os.path.join(zsrc, name + ".o")
        subprocess.run([cc, "-O2", "-fPIC", "-DHAVE_HIDDEN", "-DHAVE_UNISTD_H", "-DHAVE_STDARG_H",
                        "-D_LARGEFILE64_SOURCE=1", "-c", os.path.join(zsrc, name + ".c"), "-o", obj],
                       check=True, env=env)
        objs.append(obj)
    os.makedirs(libdir, exist_ok=True)
    subprocess.run([ar, "rcs", lib] + objs, check=True, env=env)
    return libdir


def retag(wheel: str, platform_tag: str) -> str:
    """Rename ``*-linux_<arch>.whl`` to the given platform tag, updating WHEEL and RECORD."""
    base = os.path.basename(wheel)
    m = re.match(r"^(.+-)linux_[^-]+\.whl$", base)
    if not m:
        return wheel
    new = os.path.join(os.path.dirname(wheel), m.group(1) + platform_tag + ".whl")
    with zipfile.ZipFile(wheel) as zin:
        items = [(i, zin.read(i.filename)) for i in zin.infolist()]
    record_name = next(i.filename for i, _ in items if i.filename.endswith(".dist-info/RECORD"))
    rows = []
    with zipfile.ZipFile(new, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in items:
            if info.filename == record_name:
                continue
            if info.filename.endswith(".dist-info/WHEEL"):
                text = data.decode()
                tags = {re.sub(r"linux_[A-Za-z0-9_]+$", t, line.split(": ", 1)[1])
                        for line in text.splitlines() if line.startswith("Tag: ")
                        for t in platform_tag.split(".")}
                text = "".join(l + "\n" for l in text.splitlines() if l.strip() and not l.startswith("Tag: "))
                text += "".join(f"Tag: {t}\n" for t in sorted(tags))
                data = text.encode()
            zout.writestr(info, data)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            rows.append((info.filename, f"sha256={digest}", str(len(data))))
        rows.append((record_name, "", ""))
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerows(rows)
        zout.writestr(record_name, buf.getvalue())
    os.remove(wheel)
    return new


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="cartella in cui salvare le wheel")
    ap.add_argument("--work", required=True, help="cartella di lavoro (Zig, zlib, cache)")
    ap.add_argument("--python", default=sys.executable, help="Python per cui compilare (default: questo)")
    ap.add_argument("--manylinux", action="store_true", help="etichetta le wheel come manylinux2014")
    ap.add_argument("packages", nargs="*", default=list(PACKAGES))
    args = ap.parse_args(argv)

    work = os.path.abspath(args.work)
    out = os.path.abspath(args.out)
    os.makedirs(work, exist_ok=True)
    os.makedirs(out, exist_ok=True)
    a = arch()
    triple = f"{a}-linux-gnu.{GLIBC}"

    env = dict(os.environ)
    env.update({
        "PIP_NO_CACHE_DIR": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_CONFIG_FILE": os.devnull,
        "PYTHONNOUSERSITE": "1",
        # Zig caches compiled runtimes (libc stubs, libc++) - keep them in the work folder
        "ZIG_GLOBAL_CACHE_DIR": os.path.join(work, "zig-cache"),
        "ZIG_LOCAL_CACHE_DIR": os.path.join(work, "zig-cache"),
    })
    zig_dir = install_zig(args.python, work, env)
    cc, cxx, ar = write_wrappers(args.python, zig_dir, work, triple)
    zlib_dir = build_zlib(work, cc, ar, env)

    versions = pinned_versions()
    env.update({
        "CC": cc, "CXX": cxx,
        # -s: no debug info / local symbols; -L: our static zlib for amulet-leveldb (links "-lz")
        "LDSHARED": f"{cc} -shared -s -L{zlib_dir}",
        "LDCXXSHARED": f"{cxx} -shared -s -L{zlib_dir}",
    })
    tmp_out = tempfile.mkdtemp(prefix="wheels-", dir=work)
    try:
        for pkg in args.packages:
            spec = f"{pkg}=={versions[pkg]}" if pkg in versions else pkg
            log(f"compilo {spec} per {triple}")
            subprocess.run([args.python, "-m", "pip", "wheel", "--no-cache-dir", "--no-deps",
                            "--no-binary", pkg, "-w", tmp_out, spec], check=True, env=env)
        for name in sorted(os.listdir(tmp_out)):
            whl = os.path.join(tmp_out, name)
            if args.manylinux:
                whl = retag(whl, f"manylinux_2_17_{a}.manylinux2014_{a}")
            dest = os.path.join(out, os.path.basename(whl))
            shutil.move(whl, dest)
            log(f"pronto: {dest}")
    finally:
        shutil.rmtree(tmp_out, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
