# makes test zips for bulk mode using random photos from picsum.photos
#   python scripts/make_sample_zip.py              -> 20 photos
#   python scripts/make_sample_zip.py -n 60        -> more load
#   python scripts/make_sample_zip.py --edge-cases -> adds junk files to test skipping

import argparse
import random
import urllib.request
import zipfile
from pathlib import Path

OUT = Path("sample_data")
SIZES = [(640, 480), (1024, 768), (1920, 1080), (800, 800), (3000, 2000), (480, 640)]


def fetch(seed, w, h):
    url = f"https://picsum.photos/seed/da3408-{seed}/{w}/{h}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


parser = argparse.ArgumentParser()
parser.add_argument("-n", type=int, default=20)
parser.add_argument("--edge-cases", action="store_true")
args = parser.parse_args()

single_dir = OUT / "single"
single_dir.mkdir(parents=True, exist_ok=True)
rng = random.Random(42)

zpath = OUT / f"photos_{args.n}{'_edge_cases' if args.edge_cases else ''}.zip"
with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for i in range(args.n):
        w, h = rng.choice(SIZES)
        data = fetch(i, w, h)
        folder = "nested/" if args.edge_cases and i % 5 == 0 else ""
        zf.writestr(f"{folder}photo_{i:03d}.jpg", data)
        if i < 3:
            (single_dir / f"photo_{i:03d}.jpg").write_bytes(data)
        print(f"[{i + 1}/{args.n}] {w}x{h} {len(data) // 1024} KB")

    if args.edge_cases:
        zf.writestr("README.txt", "not an image")
        zf.writestr("data.csv", "a,b\n1,2\n")
        zf.writestr("corrupt_photo.jpg", b"\xff\xd8\xff\xe0 not really a jpeg")
        zf.writestr("__MACOSX/._photo_000.jpg", b"mac junk")
        zf.writestr(".hidden.png", b"hidden")

(single_dir / "corrupt.jpg").write_bytes(b"\xff\xd8\xff\xe0 broken")
print(f"\nsaved {zpath} ({zpath.stat().st_size / 1e6:.1f} MB)")
