import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def generate(root: Path, patterns: list[str], version: str, out_dir: Path):
    """生成 manifest + 业务文件 zip（全量业务包，不是 diff）"""
    files = {}
    zip_path = out_dir / f"resource-update-{version}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for pattern in patterns:
            for path in root.glob(pattern):
                if not path.is_file():
                    continue
                rel = path.relative_to(root).as_posix()
                files[rel] = {
                    "hash": file_hash(path),
                    "size": path.stat().st_size,
                }
                zf.write(path, rel)

    manifest = {
        "version": version,
        "update_url": (
            f"https://github.com/tomato90s/maa-lostsword"
            f"/releases/download/{version}/resource-update-{version}.zip"
        ),
        "files": files,
    }

    manifest_path = out_dir / "resource-manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"manifest: {manifest_path} ({len(files)} files)")
    print(f"zip: {zip_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--include", nargs="+", required=True)
    args = parser.parse_args()

    generate(args.root, args.include, args.version, args.output_dir)
