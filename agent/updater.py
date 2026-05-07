import hashlib
import json
import os
import shutil
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path


class ResourceUpdater:
    """增量更新：下载 zip 全量业务包，解压覆盖"""

    MIRROR_PREFIXES = [
        "",
        "https://gh-proxy.com/",
        "https://v6.gh-proxy.org/",
        "https://fastly.gh-proxy.org/",
        "https://edgeone.gh-proxy.org/",
    ]

    MANIFEST_URL = (
        "https://github.com/tomato90s/maa-lostsword"
        "/releases/latest/download/resource-manifest.json"
    )

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.manifest_path = root_dir / ".manifest.json"
        self.tmp_dir = root_dir / ".update_tmp"
        self.pending_flag = self.tmp_dir / ".pending"

    # ------------------------------------------------------------------ #
    # 对外 API
    # ------------------------------------------------------------------ #

    def check_and_update(self) -> bool:
        """检查远程版本，如有更新则下载应用。返回是否实际更新了文件。"""
        try:
            remote = self._fetch_manifest()
            if not remote:
                return False

            local = self._load_local_manifest()
            if local.get("version") == remote.get("version"):
                return False

            print(f"[Updater] {local.get('version', 'none')} -> {remote['version']}")

            if not self._need_update(remote, local):
                self._save_manifest(remote)
                return False

            self._download_and_apply(remote["update_url"])
            self._save_manifest(remote)
            print("[Updater] 更新完成")
            return True

        except Exception as e:
            print(f"[Updater] 失败: {e}")
            return False

    @classmethod
    def apply_pending(cls, root_dir: Path) -> bool:
        """在 agent 启动前调用：完成上次因文件锁定未做完的替换。"""
        tmp_dir = root_dir / ".update_tmp"
        pending_flag = tmp_dir / ".pending"
        if not pending_flag.exists():
            return False

        print("[Updater] 发现未完成的更新，继续应用...")
        try:
            for item in tmp_dir.iterdir():
                if item.name == ".pending":
                    continue
                target = root_dir / item.name
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                os.replace(item, target)

            shutil.rmtree(tmp_dir)
            print("[Updater] 未完成更新已应用")
            return True

        except Exception as e:
            print(f"[Updater] 应用未完成更新失败（将在下次启动重试）: {e}")
            return False

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #

    def _load_local_manifest(self) -> dict:
        if self.manifest_path.exists():
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"version": "none", "files": {}}

    def _save_manifest(self, manifest: dict):
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    def _fetch_manifest(self) -> dict | None:
        last_error = None
        for prefix in self.MIRROR_PREFIXES:
            url = prefix + self.MANIFEST_URL
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "maa-lostsword-updater/1.0"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                last_error = e
                continue
        print(f"[Updater] manifest 拉取失败: {last_error}")
        return None

    def _need_update(self, remote: dict, local: dict) -> bool:
        """对比 hash，确认文件是否真的变了"""
        remote_files = remote.get("files", {})
        local_files = local.get("files", {})

        for path, info in remote_files.items():
            if local_files.get(path, {}).get("hash") == info["hash"]:
                continue
            local_file = self.root_dir / path
            if local_file.exists() and self._hash_file(local_file) == info["hash"]:
                continue
            return True
        return False

    def _hash_file(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return f"sha256:{h.hexdigest()}"

    def _download_zip(self, url: str, tmp):
        """分块下载 ZIP，打印进度和速度"""

        def _fmt_size(b: int) -> str:
            if b < 1024:
                return f"{b} B"
            if b < 1024 * 1024:
                return f"{b / 1024:.1f} KB"
            return f"{b / (1024 * 1024):.1f} MB"

        req = urllib.request.Request(
            url, headers={"User-Agent": "maa-lostsword-updater/1.0"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 64 * 1024  # 64KB
            start_time = time.monotonic()
            last_print_time = start_time

            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                tmp.write(chunk)
                downloaded += len(chunk)

                now = time.monotonic()
                if now - last_print_time >= 0.5 or downloaded == total:
                    elapsed = now - start_time
                    speed = downloaded / elapsed if elapsed > 0 else 0
                    pct = downloaded / total * 100 if total else 0

                    total_str = _fmt_size(total) if total else "未知"
                    dl_str = _fmt_size(downloaded)
                    speed_str = _fmt_size(speed) + "/s"

                    print(
                        f"\r[Updater] 下载中... {pct:.1f}% "
                        f"({dl_str} / {total_str}) {speed_str}",
                        end="",
                        flush=True,
                    )
                    last_print_time = now

            print()  # 换行

    def _download_and_apply(self, url: str):
        """下载 zip -> 临时解压 -> 覆盖本地文件。失败时保留临时目录，下次启动再试。"""
        tmp_path = None
        last_error = None

        # 尝试多镜像下载
        for prefix in self.MIRROR_PREFIXES:
            mirror_url = prefix + url
            try:
                # 清理上一次的临时文件
                if tmp_path:
                    Path(tmp_path).unlink(missing_ok=True)
                    tmp_path = None
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                    self._download_zip(mirror_url, tmp)
                    tmp_path = tmp.name
                break
            except Exception as e:
                last_error = e
                print(f"[Updater] 镜像下载失败，尝试下一个... ({e})")
                continue

        if not tmp_path:
            raise last_error or Exception("所有镜像下载均失败")

        # 清理旧临时目录（如果上次有残留）
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(tmp_path, "r") as zf:
                zf.extractall(self.tmp_dir)

            for item in self.tmp_dir.iterdir():
                target = self.root_dir / item.name
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                os.replace(item, target)

            # 成功：清理临时目录
            shutil.rmtree(self.tmp_dir)

        except OSError:
            # Windows 文件锁定等导致替换失败：保留临时目录，设置标记
            self.pending_flag.touch()
            raise

        finally:
            Path(tmp_path).unlink(missing_ok=True)
