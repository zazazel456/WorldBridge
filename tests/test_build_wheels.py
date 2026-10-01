import base64
import csv
import hashlib
import importlib.util
import io
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("build_wheels", os.path.join(HERE, "..", "tools", "build_wheels.py"))
build_wheels = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_wheels)


def _make_wheel(path):
    wheel_meta = ("Wheel-Version: 1.0\nGenerator: setuptools\nRoot-Is-Purelib: false\n"
                  "Tag: cp311-cp311-linux_x86_64\n\n")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("pkg/_ext.so", b"\x7fELF")
        z.writestr("pkg-1.0.dist-info/WHEEL", wheel_meta)
        z.writestr("pkg-1.0.dist-info/RECORD", "")


def test_retag_manylinux(tmp_path):
    src = tmp_path / "pkg-1.0-cp311-cp311-linux_x86_64.whl"
    _make_wheel(src)
    out = build_wheels.retag(str(src), "manylinux_2_17_x86_64.manylinux2014_x86_64")
    assert os.path.basename(out) == "pkg-1.0-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
    assert not src.exists()
    with zipfile.ZipFile(out) as z:
        meta = z.read("pkg-1.0.dist-info/WHEEL").decode()
        # tags must stay in the header block (no blank line before them)
        assert "\n\n" not in meta
        assert sorted(l for l in meta.splitlines() if l.startswith("Tag: ")) == [
            "Tag: cp311-cp311-manylinux2014_x86_64", "Tag: cp311-cp311-manylinux_2_17_x86_64"]
        rows = list(csv.reader(io.StringIO(z.read("pkg-1.0.dist-info/RECORD").decode())))
        for name, digest, size in rows:
            if name.endswith("RECORD"):
                continue
            data = z.read(name)
            want = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            assert digest == f"sha256={want}" and int(size) == len(data)
