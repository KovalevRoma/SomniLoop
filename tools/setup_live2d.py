"""Fetch pinned official assets and build the optional native renderer.

Downloading requires explicit acceptance of the licenses linked in docs/live2d.md.
This is a developer setup tool, never invoked automatically by the application.
"""

import argparse
import hashlib
import shutil
import stat
import subprocess
import urllib.request
import zipfile
from pathlib import Path

ARCHIVES = {
    "sdk": (
        "https://cubism.live2d.com/sdk-native/bin/CubismSdkForNative-5-r.4.1.zip",
        "b71ec6bafc6578cce3b4cbbaa42a1cb51ae6eb477557932b02d22af957e733c7",
    ),
    "epsilon": (
        "https://cubism.live2d.com/sample-data/bin/epsilon/epsilon_ja.zip",
        "a2e4d747bb0fca4f5920637ac8acc350b08c46e3275344a273cb9c37d405f9e1",
    ),
}


def extract(archive, target):
    target = target.resolve()
    with zipfile.ZipFile(archive) as bundle:
        if sum(item.file_size for item in bundle.infolist()) > 512 * 1024 * 1024:
            raise ValueError("Archive exceeds the extraction size limit")
        for item in bundle.infolist():
            if not (target / item.filename).resolve().is_relative_to(target) or stat.S_ISLNK(
                item.external_attr >> 16
            ):
                raise ValueError("Unsafe archive member")
        bundle.extractall(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accept-licenses", action="store_true", required=True)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1] / ".live2d"
    )
    args = parser.parse_args()
    root = args.root.resolve()
    downloads = root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    for name, (url, digest) in ARCHIVES.items():
        archive = downloads / f"{name}.zip"
        if not archive.exists():
            request = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.live2d.com/"}
            )
            pending = archive.with_suffix(".part")
            with (
                urllib.request.urlopen(request, timeout=60) as response,
                pending.open("wb") as output,
            ):
                shutil.copyfileobj(response, output)
            pending.replace(archive)
        with archive.open("rb") as source:
            actual_digest = hashlib.file_digest(source, "sha256").hexdigest()
        if actual_digest != digest:
            raise ValueError(
                f"{name}: checksum changed; review the official release before updating the pin"
            )
        print(f"Verified {name}", flush=True)
        extract(archive, root / name)
    sdk = root / "sdk/CubismSdkForNative-5-r.4.1"
    source = Path(__file__).resolve().parents[1] / "native/live2d"
    subprocess.run(
        [
            "cmake",
            "-S",
            str(source),
            "-B",
            str(root / "build"),
            "-DCMAKE_BUILD_TYPE=Release",
            f"-DCUBISM_SDK={sdk}",
        ],
        check=True,
    )
    subprocess.run(["cmake", "--build", str(root / "build"), "-j", "2"], check=True)
    print(f"Installed Live2D in {root}")


if __name__ == "__main__":
    main()
