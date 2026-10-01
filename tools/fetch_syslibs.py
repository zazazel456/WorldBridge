"""Fetch the small X11/Wayland helper libraries Qt needs when the system lacks them.

Qt's X11 platform plugin links against several xcb helper libraries (xcb-cursor, icccm,
keysyms, xkbcommon-x11 ...) that many distributions do not install by default.  Instead of
asking for root to install them system wide, the missing ones are downloaded from the
Ubuntu 20.04 archive (glibc 2.31 baseline, SHA-256 pinned), unpacked from the .deb with
pure Python and stored in .runtime/syslibs, which run.sh adds to LD_LIBRARY_PATH.

Usage: python fetch_syslibs.py <dest dir>      (prints the libraries still missing, if any)
"""

import hashlib
import io
import lzma
import os
import platform
import subprocess
import sys
import tarfile
import urllib.request

import PySide6

LIBS = {
    ("x86_64", "libwayland-client.so.0"): ("http://archive.ubuntu.com/ubuntu/pool/main/w/wayland/libwayland-client0_1.18.0-1_amd64.deb", "dfd969c7fd287f00fb2f2565c570ee0ba73bc4442d86df0fdfdd5dcddb3b4cd1"),
    ("x86_64", "libwayland-cursor.so.0"): ("http://archive.ubuntu.com/ubuntu/pool/main/w/wayland/libwayland-cursor0_1.18.0-1_amd64.deb", "2ff67c8e62a266bf9f82237f933eaafed35a12534bd3779487c7e9db03e70e59"),
    ("x86_64", "libX11-xcb.so.1"): ("http://archive.ubuntu.com/ubuntu/pool/main/libx/libx11/libx11-xcb1_1.6.9-2ubuntu1_amd64.deb", "4b0f8b4e41da52225b8fe8da46f409e565abdce3bb07f510f109fc7a84fbae49"),
    ("x86_64", "libxcb-cursor.so.0"): ("http://archive.ubuntu.com/ubuntu/pool/universe/x/xcb-util-cursor/libxcb-cursor0_0.1.1-4ubuntu1_amd64.deb", "c9b5d1ad4af57397b1bd77e0a92750e34419def134c0282a0836ae9efc07cf64"),
    ("x86_64", "libxcb-glx.so.0"): ("http://archive.ubuntu.com/ubuntu/pool/main/libx/libxcb/libxcb-glx0_1.14-2_amd64.deb", "7c4b5d4a025a1ba37439a89dcf9f51ed031e038555759ce745072976b4f7b743"),
    ("x86_64", "libxcb-icccm.so.4"): ("http://archive.ubuntu.com/ubuntu/pool/main/x/xcb-util-wm/libxcb-icccm4_0.4.1-1.1_amd64.deb", "03cf5acb68f7d6bffa378f9d30e8d519ee3e5b10340df741af8c0d8bbaf5d3d4"),
    ("x86_64", "libxcb-image.so.0"): ("http://archive.ubuntu.com/ubuntu/pool/main/x/xcb-util-image/libxcb-image0_0.4.0-1build1_amd64.deb", "4002be5159fe91fcfbc6cdb68871163dbfd5c1092341bb51f26079e25b421d92"),
    ("x86_64", "libxcb-keysyms.so.1"): ("http://archive.ubuntu.com/ubuntu/pool/main/x/xcb-util-keysyms/libxcb-keysyms1_0.4.0-1build1_amd64.deb", "6cfbd86d2e1c66d2d8d0a6a17f27f0b825fc0d595647674714a2926a616bdae6"),
    ("x86_64", "libxcb-randr.so.0"): ("http://archive.ubuntu.com/ubuntu/pool/main/libx/libxcb/libxcb-randr0_1.14-2_amd64.deb", "508da595aaca39deb9ab09e3aad5619ad7b7703032413d39a226a72a28f36765"),
    ("x86_64", "libxcb-render-util.so.0"): ("http://archive.ubuntu.com/ubuntu/pool/main/x/xcb-util-renderutil/libxcb-render-util0_0.3.9-1build1_amd64.deb", "5486323b1a43b8d4d1f19986fac99a25c00676cd5596926d973e4966c8f05a84"),
    ("x86_64", "libxcb-render.so.0"): ("http://archive.ubuntu.com/ubuntu/pool/main/libx/libxcb/libxcb-render0_1.14-2_amd64.deb", "d5423de927f855b1a266b9b66e16e4ae9e067664c9337b5aaf57fb98b4791647"),
    ("x86_64", "libxcb-shape.so.0"): ("http://archive.ubuntu.com/ubuntu/pool/main/libx/libxcb/libxcb-shape0_1.14-2_amd64.deb", "d6699f1b0182e7175ec4df6dfd26d91a4b4cbf9fd6ab16b7b430aca1bd54092f"),
    ("x86_64", "libxcb-shm.so.0"): ("http://archive.ubuntu.com/ubuntu/pool/main/libx/libxcb/libxcb-shm0_1.14-2_amd64.deb", "776c691acd4fcdad314f0f09c98927a608cbc422007ce0f0c88e9d6711773217"),
    ("x86_64", "libxcb-sync.so.1"): ("http://archive.ubuntu.com/ubuntu/pool/main/libx/libxcb/libxcb-sync1_1.14-2_amd64.deb", "d79b16f888b16031cfc25bbf6f92b404f421d7965e625cede4825b15aa795e6e"),
    ("x86_64", "libxcb-util.so.1"): ("http://archive.ubuntu.com/ubuntu/pool/main/x/xcb-util/libxcb-util1_0.4.0-0ubuntu3_amd64.deb", "83f9a455c8c6e787fcad27a84108704c7aa7669405f2af097cd25cfeeb10d82a"),
    ("x86_64", "libxcb-xfixes.so.0"): ("http://archive.ubuntu.com/ubuntu/pool/main/libx/libxcb/libxcb-xfixes0_1.14-2_amd64.deb", "9fbb1bbb105749359d99580bd388bcfec472cf3c6ff7f3b353ee78e61ec1bb81"),
    ("x86_64", "libxcb-xkb.so.1"): ("http://archive.ubuntu.com/ubuntu/pool/main/libx/libxcb/libxcb-xkb1_1.14-2_amd64.deb", "300c205cf611ce1cfae89fb490c7aeec297aea0ccb82ea15d9941078a09882e3"),
    ("x86_64", "libxkbcommon-x11.so.0"): ("http://archive.ubuntu.com/ubuntu/pool/main/libx/libxkbcommon/libxkbcommon-x11-0_0.10.0-1_amd64.deb", "929d5e4ee88d6f5f3b09e238ffae60d667e4c9c4731a0210227b092fc578c6ac"),
    ("x86_64", "libxkbcommon.so.0"): ("http://archive.ubuntu.com/ubuntu/pool/main/libx/libxkbcommon/libxkbcommon0_0.10.0-1_amd64.deb", "b704ce1751dd938025b88a84c4054d4f36651661e473efeb3da8ed39aaf05868"),
    ("aarch64", "libwayland-client.so.0"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/w/wayland/libwayland-client0_1.18.0-1_arm64.deb", "8e2a40a07abd466a06db56ea1dff8fe92f8344a31baca3ca0a30912707a65f38"),
    ("aarch64", "libwayland-cursor.so.0"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/w/wayland/libwayland-cursor0_1.18.0-1_arm64.deb", "01a09497261244fba1440a4c60a9b116bda0bc7a020434dd17adf0f76afaf37e"),
    ("aarch64", "libX11-xcb.so.1"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/libx/libx11/libx11-xcb1_1.6.9-2ubuntu1_arm64.deb", "4d727b39abf7ac08d8db5db829339976c9e74a86b38dc68501d29dee1d1eb4b1"),
    ("aarch64", "libxcb-cursor.so.0"): ("http://ports.ubuntu.com/ubuntu-ports/pool/universe/x/xcb-util-cursor/libxcb-cursor0_0.1.1-4ubuntu1_arm64.deb", "cd51860d7a40be6fe72bf9f69aac60e7cf7ae70994d5a7ea3aa82dfe0232f96a"),
    ("aarch64", "libxcb-glx.so.0"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/libx/libxcb/libxcb-glx0_1.14-2_arm64.deb", "b638891eee30451c8148e2c6eb3523bdf629542f0d9bf9c748d6a1e3c45106a9"),
    ("aarch64", "libxcb-icccm.so.4"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/x/xcb-util-wm/libxcb-icccm4_0.4.1-1.1_arm64.deb", "be5e6a047c6a04b773b4c80d6fe7a5bc2001e9255177f58bd8825b8f02fedfa5"),
    ("aarch64", "libxcb-image.so.0"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/x/xcb-util-image/libxcb-image0_0.4.0-1build1_arm64.deb", "5b456392daf2fe3189bbb1a0e83d60d17960309a7255c7500d13b62445f145f4"),
    ("aarch64", "libxcb-keysyms.so.1"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/x/xcb-util-keysyms/libxcb-keysyms1_0.4.0-1build1_arm64.deb", "6967ec5329fc955838a5024ee0f8f1ffe54dd44ec2c13181f4ea74f10f6ba382"),
    ("aarch64", "libxcb-randr.so.0"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/libx/libxcb/libxcb-randr0_1.14-2_arm64.deb", "4d0439474f3bd76f5adf784d3d61ca10c293b1b11b984cfa0ed69f3fb55dca47"),
    ("aarch64", "libxcb-render-util.so.0"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/x/xcb-util-renderutil/libxcb-render-util0_0.3.9-1build1_arm64.deb", "0d6f5908040cb32531080d5c1fc07d8226ad64427198c039892629d201d2092e"),
    ("aarch64", "libxcb-render.so.0"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/libx/libxcb/libxcb-render0_1.14-2_arm64.deb", "4a82f349fc869c8f803c73fdd7e94a6ee1c06d6fb3f6ceab1227efee64828957"),
    ("aarch64", "libxcb-shape.so.0"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/libx/libxcb/libxcb-shape0_1.14-2_arm64.deb", "1666c04b5358510a70de0780464c8ac7853f6834b3a5d392fbf81c1f774509c9"),
    ("aarch64", "libxcb-shm.so.0"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/libx/libxcb/libxcb-shm0_1.14-2_arm64.deb", "e0eb8cad040933946459ff6d2116953a68ce149e9d695c28552a1d0beaa9a07b"),
    ("aarch64", "libxcb-sync.so.1"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/libx/libxcb/libxcb-sync1_1.14-2_arm64.deb", "835b88e97486db5e303a89f9d07a530ac182cb5b0b102776cf76b56a00340504"),
    ("aarch64", "libxcb-util.so.1"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/x/xcb-util/libxcb-util1_0.4.0-0ubuntu3_arm64.deb", "9ab6ec471f90b1cd71a20e627b2839195c3fe392a826568d4877123b424ba392"),
    ("aarch64", "libxcb-xfixes.so.0"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/libx/libxcb/libxcb-xfixes0_1.14-2_arm64.deb", "d334081b50fea5a3ca31e35efc8915b15d183d448fd9f8aa15dee05ff1c9fc1b"),
    ("aarch64", "libxcb-xkb.so.1"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/libx/libxcb/libxcb-xkb1_1.14-2_arm64.deb", "f599fd435d9a2f7296671f444fd8272ab50fb73750a58f0faef81aefcf6edd79"),
    ("aarch64", "libxkbcommon-x11.so.0"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/libx/libxkbcommon/libxkbcommon-x11-0_0.10.0-1_arm64.deb", "087b45873e4852c438a07101f409d417d2263a2cd9c7581bd5f5d9743559e7c3"),
    ("aarch64", "libxkbcommon.so.0"): ("http://ports.ubuntu.com/ubuntu-ports/pool/main/libx/libxkbcommon/libxkbcommon0_0.10.0-1_arm64.deb", "3f2620fa08f83a1d139dde4012c49519a96abd58f07a92945e0f16154096bb2a"),
}


# libxkbcommon-x11 uses libxkbcommon internals: the two must come from the same release,
# otherwise Qt crashes (verified: focal xkbcommon-x11 0.10 + system xkbcommon 1.6 -> SIGSEGV)
COMPANIONS = {"libxkbcommon-x11.so.0": ["libxkbcommon.so.0"]}


def _plugins():
    qt = os.path.join(os.path.dirname(PySide6.__file__), "Qt")
    out = [os.path.join(qt, "lib", "libQt6XcbQpa.so.6"), os.path.join(qt, "lib", "libQt6WaylandClient.so.6")]
    for sub in ("platforms", "xcbglintegrations", "wayland-shell-integration"):
        d = os.path.join(qt, "plugins", sub)
        if os.path.isdir(d):
            out += [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".so")]
    return [p for p in out if os.path.exists(p)]


def missing(dest):
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = dest + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    qtlib = os.path.join(os.path.dirname(PySide6.__file__), "Qt", "lib")
    env["LD_LIBRARY_PATH"] += ":" + qtlib
    names = set()
    for so in _plugins():
        try:
            out = subprocess.run(["ldd", so], capture_output=True, text=True, env=env).stdout
        except OSError:
            return set()
        for line in out.splitlines():
            if "not found" in line:
                names.add(line.split()[0])
    return names


def _deb_members(data: bytes):
    if data[:8] != b"!<arch>\n":
        raise ValueError("not a .deb")
    p = 8
    while p + 60 <= len(data):
        name = data[p:p + 16].decode().strip().rstrip("/")
        size = int(data[p + 48:p + 58].decode().strip())
        yield name, data[p + 60:p + 60 + size]
        p += 60 + size + (size & 1)


def extract(deb: bytes, dest: str):
    for name, body in _deb_members(deb):
        if name.startswith("data.tar"):
            if name.endswith(".xz"):
                body = lzma.decompress(body)
                mode = "r:"
            elif name.endswith(".gz"):
                mode = "r:gz"
            else:
                mode = "r:"
            with tarfile.open(fileobj=io.BytesIO(body), mode=mode) as tf:
                for m in tf.getmembers():
                    base = os.path.basename(m.name)
                    if ".so" not in base or not (m.isfile() or m.issym()):
                        continue
                    target = os.path.join(dest, base)
                    if m.issym():
                        if not os.path.lexists(target):
                            os.symlink(os.path.basename(m.linkname), target)
                    else:
                        with open(target, "wb") as f:
                            f.write(tf.extractfile(m).read())


def main():
    dest = os.path.abspath(sys.argv[1])
    os.makedirs(dest, exist_ok=True)
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(platform.machine())
    for _round in range(4):
        need = [n for n in sorted(missing(dest)) if (arch, n) in LIBS]
        if not need:
            break
        for n in list(need):
            need += [c for c in COMPANIONS.get(n, []) if c not in need and not os.path.exists(os.path.join(dest, c))]
        for n in need:
            url, sha = LIBS[(arch, n)]
            print(f"  scarico {n} …", file=sys.stderr)
            data = urllib.request.urlopen(url, timeout=60).read()
            if hashlib.sha256(data).hexdigest() != sha:
                raise SystemExit(f"checksum non valido per {url}")
            extract(data, dest)
    left = sorted(missing(dest))
    print(" ".join(left))


if __name__ == "__main__":
    main()
