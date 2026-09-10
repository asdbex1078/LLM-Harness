"""索引服务：按 md 文件指纹缓存 index，变化时全量重建并落盘 .knowrary/index.json。

阶段 1 的 build_index 已经是幂等的（内容哈希决定 revision），这里只解决"什么时候
重建"：每次请求比对一次文件指纹（数量 + 最新 mtime），比 watchfiles 监听简单，
够 72～数千节点用；真正的文件监听与 WebSocket 推送在阶段 3 接。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from .paths import core

_LOCK = threading.Lock()


@dataclass
class _Cache:
    data: dict | None = None
    fingerprint: tuple = field(default_factory=tuple)


_CACHE: dict[Path, _Cache] = {}


def fingerprint(vault: Path) -> tuple:
    """vault 的 md 指纹：文件数 + 最新修改时间 + 类型表 mtime。"""
    paths = core.walk_md(vault)
    newest = max((p.stat().st_mtime_ns for p in paths), default=0)
    table = vault / "relation-types.json"
    return (len(paths), newest, table.stat().st_mtime_ns if table.exists() else 0)


def current_index(vault: Path) -> dict:
    """取当前索引；md 有变化则重建并写盘。"""
    with _LOCK:
        cache = _CACHE.setdefault(vault, _Cache())
        fp = fingerprint(vault)
        if cache.data is not None and cache.fingerprint == fp:
            return cache.data
        path = core.index_path(vault)
        result = core.build_index(vault, core.load_previous(path))
        problems = core.validate_index(result.data)
        if problems:
            raise RuntimeError(f"索引契约校验失败：{problems[:3]}")
        if result.changed or not path.exists():
            core.write_json_atomic(path, result.data)
        cache.data, cache.fingerprint = result.data, fp
        return result.data


def invalidate(vault: Path | None = None) -> None:
    with _LOCK:
        _CACHE.pop(vault, None) if vault else _CACHE.clear()
