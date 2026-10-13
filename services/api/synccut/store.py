"""Project storage: one JSON document per project plus its media folder.

v0 stand-in for Postgres + object storage (see docs/V0_TODAY.md).
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

DEFAULT_BRAND = {
    "name": "",
    "headline": "",
    "avatar_url": "",
    "accent": "#4F46E5",
    "booking_url": "",
    "profile_url": "",
    "rating_text": "",
    "portfolio": [],
}


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


def with_defaults(project: dict) -> dict:
    """Fields added after v0 shipped; older projects keep recording mode."""
    project.setdefault("mode", "record" if project.get("takes") else "generate")
    project.setdefault("actions", [])
    project.setdefault("actions_source", None)
    project.setdefault("capture", None)
    project.setdefault("browser_video", None)
    project.setdefault("layout", {"pip_corner": "bottom-left", "pip_width_pct": 0.22, "pip_visible": True, "camera_zoom": True})
    return project


class NotFound(KeyError):
    pass


class Store:
    def __init__(self, data_dir: Path):
        self.root = data_dir
        self.projects_dir = data_dir / "projects"
        self.cache_dir = data_dir / "cache"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    # paths -----------------------------------------------------------------
    def project_dir(self, pid: str) -> Path:
        if not pid.replace("_", "").isalnum():
            raise NotFound(pid)
        return self.projects_dir / pid

    def _file(self, pid: str) -> Path:
        return self.project_dir(pid) / "project.json"

    def _lock(self, key: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.RLock())

    # io --------------------------------------------------------------------
    @staticmethod
    def _write(path: Path, data: dict) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        for attempt in range(10):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:  # Windows: a reader has the file open
                time.sleep(0.05 * (attempt + 1))
        os.replace(tmp, path)

    @staticmethod
    def _read(path: Path) -> dict:
        for attempt in range(10):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        return json.loads(path.read_text(encoding="utf-8"))

    # projects ----------------------------------------------------------------
    def create(self, name: str) -> dict:
        pid = new_id("p")
        now = time.time()
        project = {
            "id": pid,
            "name": name.strip() or "Untitled video",
            "created_at": now,
            "updated_at": now,
            "master": None,
            "transcript": None,
            "beats": [],
            "beats_source": None,
            "takes": [],
            "timeline": None,
            "timeline_versions": [],
            "timeline_stale": False,
            "renders": [],
            "jobs": [],
            "share": {
                "slug": secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8].lower(),
                "published": False,
                "title": "",
                "message": "",
                "cta_label": "Book a call",
                "render_id": None,
            },
        }
        with_defaults(project)
        self.project_dir(pid).mkdir(parents=True)
        self._write(self._file(pid), project)
        return project

    def get(self, pid: str) -> dict:
        path = self._file(pid)
        if not path.exists():
            raise NotFound(pid)
        with self._lock(pid):
            return with_defaults(self._read(path))

    def update(self, pid: str, fn: Callable[[dict], object]) -> dict:
        with self._lock(pid):
            project = self.get(pid)
            fn(project)
            project["updated_at"] = time.time()
            self._write(self._file(pid), project)
            return project

    def list(self) -> list[dict]:
        out = []
        for path in self.projects_dir.glob("*/project.json"):
            try:
                out.append(with_defaults(self._read(path)))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(out, key=lambda p: p["updated_at"], reverse=True)

    def delete(self, pid: str) -> None:
        directory = self.project_dir(pid)
        if not directory.exists():
            raise NotFound(pid)
        with self._lock(pid):
            shutil.rmtree(directory)

    def find_by_slug(self, slug: str) -> dict:
        for project in self.list():
            if project.get("share", {}).get("slug") == slug:
                return project
        raise NotFound(slug)

    # brand settings ------------------------------------------------------------
    def get_brand(self) -> dict:
        path = self.root / "brand.json"
        if not path.exists():
            return dict(DEFAULT_BRAND)
        return {**DEFAULT_BRAND, **self._read(path)}

    def put_brand(self, brand: dict) -> dict:
        merged = {**DEFAULT_BRAND, **{k: v for k, v in brand.items() if k in DEFAULT_BRAND}}
        with self._lock("__brand__"):
            self._write(self.root / "brand.json", merged)
        return merged
