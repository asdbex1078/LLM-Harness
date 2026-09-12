"""Markdown 写回：ChangeSet 是唯一入口，只改 `## 关系` 区块和白名单 frontmatter 字段。

三条硬约束（设计文档 3.4.3 / 阶段 3 验收）：
1. **其余原文逐字保留**——正文、代码块、列表、`## 参考资料`、`## 待办` 全都按原样吐回；
   没有 update_frontmatter 变更的文件，连 frontmatter 都不重新序列化。
2. **先预览后执行**：dry_run 返回每个文件的新内容与差异摘要，不碰磁盘。
3. **外部改过就拒绝**：比对文件指纹，Obsidian 里改过而索引还没更新时直接报冲突，不覆盖。
"""
from __future__ import annotations

import datetime as dt
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .mdio import RE_NEXT_H2, RE_REL_HEADER, dump_frontmatter, read, split_frontmatter, write
from .parser import LAYOUT_KEYS, STATUS_VALUES, digest_of
from .relations import Edge, parse_relations

# 允许通过 ChangeSet 修改的 frontmatter 字段；布局字段和 id 永远不许改
EDITABLE_FIELDS = ("name", "field", "type", "status", "year", "start_year", "end_year",
                   "aliases", "tags", "desc", "learned", "source")
CHANGE_TYPES = ("add_edge", "remove_edge", "update_edge", "update_frontmatter")


class ChangeRejected(Exception):
    """变更本身不合法（未知类型、改了不许改的字段、目标不存在…）。"""


class WriteConflict(Exception):
    """文件在索引生成之后被外部改过，拒绝覆盖。"""


@dataclass
class FileEdit:
    path: Path
    rel: str
    before: str
    after: str
    notes: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.before != self.after


def split_sections(text: str) -> tuple[str, str, str, str]:
    """把文件拆成 (frontmatter 原文, 正文, 关系段, 关系段之后的原文)。"""
    fm_text = ""
    rest = text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 3)
        if end != -1:
            fm_text, rest = text[: end + 5], text[end + 5:]
    parts = RE_REL_HEADER.split(rest, maxsplit=1)
    if len(parts) == 1:
        return fm_text, parts[0], "", ""
    body = parts[0]
    m = RE_NEXT_H2.search(parts[1])
    return (fm_text, body, parts[1], "") if m is None else (fm_text, body, parts[1][:m.start()], parts[1][m.start():])


def _relation_lines(section: str, node_id: str) -> tuple[list[Edge], list[str]]:
    """解析关系段，同时保留无法识别的行（注释、空行）原样。"""
    edges, _ = parse_relations(section, node_id)
    extras = [ln for ln in section.splitlines()
              if ln.strip() and not ln.strip().startswith("-")]
    return edges, extras


def _render_section(edges: list[Edge], extras: list[str]) -> str:
    lines = [e.line() for e in edges] + extras
    return "\n" + "\n".join(lines) + "\n" if lines else "\n"


def _same_edge(e: Edge, change: dict) -> bool:
    return e.target == change.get("target") and (
        change.get("relation") in (None, e.type) or change.get("from_relation") in (None, e.type))


def apply_to_text(text: str, node_id: str, changes: list[dict]) -> tuple[str, list[str]]:
    """把这一批变更作用到单个文件的原文上，返回 (新原文, 变更说明)。"""
    fm_text, body, section, tail = split_sections(text)
    edges, extras = _relation_lines(section, node_id)
    notes: list[str] = []
    fm_changed = False
    fm = split_frontmatter(text)[0] if fm_text else {}

    for change in changes:
        kind = change["type"]
        if kind == "add_edge":
            if any(e.type == change["relation"] and e.target == change["target"] for e in edges):
                raise ChangeRejected(f"关系已存在：{change['relation']} → {change['target']}")
            edges.append(Edge(node_id, change["relation"], change["target"],
                              change.get("year"), (change.get("note") or "").strip()))
            notes.append(f"+ {change['relation']}:: [[{change['target']}]]")
        elif kind == "remove_edge":
            hit = [e for e in edges if _same_edge(e, change)]
            if not hit:
                raise ChangeRejected(f"要删除的关系不存在：{change.get('relation')} → {change.get('target')}")
            for e in hit:
                edges.remove(e)
                notes.append(f"- {e.type}:: [[{e.target}]]")
        elif kind == "update_edge":
            hit = [e for e in edges if e.target == change["target"]
                   and e.type == (change.get("from_relation") or e.type)]
            if not hit:
                raise ChangeRejected(f"要修改的关系不存在：→ {change.get('target')}")
            for e in hit:
                old = e.line()
                e.type = change.get("relation") or e.type
                if "year" in change:
                    e.year = change["year"]
                if "note" in change:
                    e.note = (change["note"] or "").strip()
                notes.append(f"~ {old}  →  {e.line()}")
        elif kind == "update_frontmatter":
            for key, value in (change.get("fields") or {}).items():
                if key in LAYOUT_KEYS or key == "id":
                    raise ChangeRejected(f"不允许修改字段 `{key}`")
                if key not in EDITABLE_FIELDS:
                    raise ChangeRejected(f"未知 frontmatter 字段 `{key}`")
                if key == "status" and value not in STATUS_VALUES:
                    raise ChangeRejected(f"status `{value}` 不合法")
                fm[key] = value
                fm_changed = True
                notes.append(f"frontmatter {key} = {value!r}")
        else:
            raise ChangeRejected(f"未知变更类型 `{kind}`")

    head = dump_frontmatter(fm) if fm_changed else fm_text
    new_section = _render_section(edges, extras)
    rebuilt = head + body.rstrip("\n") + "\n\n## 关系" + new_section + tail
    return rebuilt, notes


def plan(vault: Path, changes: list[dict], index: dict) -> list[FileEdit]:
    """把 ChangeSet 变成"每个文件改成什么样"，不写盘。外部改过的文件直接报冲突。"""
    by_node: dict[str, list[dict]] = {}
    for change in changes:
        if change["type"] not in CHANGE_TYPES:
            raise ChangeRejected(f"未知变更类型 `{change['type']}`")
        by_node.setdefault(change["source"], []).append(change)

    nodes = {n["id"]: n for n in index["nodes"]}
    edits: list[FileEdit] = []
    for node_id, group in sorted(by_node.items()):
        meta = nodes.get(node_id)
        if not meta or not meta.get("path"):
            raise ChangeRejected(f"节点 `{node_id}` 不存在或没有对应文件")
        path = vault / meta["path"]
        if not path.exists():
            raise ChangeRejected(f"文件不存在：{meta['path']}")
        text = read(path)
        if meta.get("digest") and digest_of(text) != meta["digest"]:
            raise WriteConflict(f"{meta['path']} 在索引生成后被改过（可能是 Obsidian），请刷新后重试")
        after, notes = apply_to_text(text, node_id, group)
        edits.append(FileEdit(path=path, rel=meta["path"], before=text, after=after, notes=notes))
    return edits


def backup(vault: Path, edits: list[FileEdit]) -> str:
    """写回前把原文件整份快照到 .knowrary/backup/<时间戳>/。"""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    root = vault / ".knowrary" / "backup" / stamp
    for edit in edits:
        target = root / edit.rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(edit.path, target)
    return root.relative_to(vault).as_posix()


def commit(vault: Path, edits: list[FileEdit]) -> str:
    """备份后逐个写回。返回备份目录的相对路径。"""
    touched = [e for e in edits if e.changed]
    if not touched:
        return ""
    snapshot = backup(vault, touched)
    for edit in touched:
        write(edit.path, edit.after)
    return snapshot
