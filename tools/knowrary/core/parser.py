"""节点解析与 frontmatter 校验：md 文件 → Node（frontmatter + 正文 + 关系）。

正文与关系区块严格分离：只有 `## 关系` 会被关系解析器读取，其余原文逐字保留，
写回时原样吐回去（见《Markdown 文档规范》4）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import hashlib

from .diagnostics import Diagnostics
from .mdio import RE_ID_OK, RE_NEXT_H2, RE_REL_HEADER, read, split_frontmatter, walk_md
from .relations import Edge, parse_relations

def digest_of(text: str) -> str:
    """文件内容指纹：写回前比对它，Obsidian 改过就拒绝覆盖。"""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


STATUS_VALUES = ("active", "deprecated", "disputed", "stub")
LAYOUT_KEYS = ("x", "y", "w", "h", "group", "collapsed", "pinned")
REQUIRED_FIELDS = ("name", "field", "desc")


@dataclass
class Node:
    id: str
    path: Path
    fm: dict
    body: str          # 不含 frontmatter、不含 ## 关系 段
    edges: list[Edge] = field(default_factory=list)
    rel_tail: str = "" # 关系段之后的残余文本（一般为空）
    raw: str = ""      # 文件原文，写回时用来比对"外部有没有改过"
    digest: str = ""   # 原文的 sha1 前 16 位

    @property
    def is_stub(self) -> bool:
        return self.fm.get("status") == "stub"


def load_node(vault: Path, p: Path) -> tuple[Node, Diagnostics]:
    """读单个 md。YAML 非法时按无 frontmatter 处理并给出 error，不丢节点。"""
    diags = Diagnostics()
    rel = p.relative_to(vault).as_posix()
    text = read(p)
    try:
        fm, rest = split_frontmatter(text)
    except ValueError as exc:
        diags.error("bad_yaml", f"frontmatter YAML 非法：{exc}", file=rel)
        fm, rest = {}, text
    parts = RE_REL_HEADER.split(rest, maxsplit=1)
    body = parts[0].rstrip() + "\n"
    section, tail = _cut_relation_section(parts[1]) if len(parts) > 1 else ("", "")
    node = Node(id=str(fm.get("id") or p.stem), path=p, fm=fm, body=body, rel_tail=tail,
                raw=text, digest=digest_of(text))
    edges, bad = parse_relations(section, node.id)
    node.edges = edges
    for b in bad:
        diags.error("bad_relation_line", f"无法解析的关系行 `{b}`", file=rel, node=node.id)
    return node, diags


def _cut_relation_section(rest: str) -> tuple[str, str]:
    """把 `## 关系` 之后的文本切成 (关系段, 后续原文)。

    规范 4 允许 `## 关系` 后面继续写 `## 参考资料`、`## 待办`；这些章节既不是关系，
    写回时也必须逐字保留，所以在这里就切开，不能整段丢给关系解析器。
    """
    m = RE_NEXT_H2.search(rest)
    return (rest, "") if m is None else (rest[:m.start()], rest[m.start():])


def load_vault(vault: Path) -> tuple[dict[str, Node], Diagnostics]:
    """扫约定目录并解析全部节点。重复 id 保留后者，同时报 error。"""
    nodes: dict[str, Node] = {}
    diags = Diagnostics()
    for p in walk_md(vault):
        rel = p.relative_to(vault).as_posix()
        if not read(p).strip():
            diags.warn("empty_file", "文件为空，已跳过", file=rel)
            continue
        node, node_diags = load_node(vault, p)
        diags.extend(node_diags)
        if node.id in nodes:
            other = nodes[node.id].path.relative_to(vault).as_posix()
            diags.error("duplicate_id", f"重复 id `{node.id}`，与 {other} 冲突", file=rel, node=node.id)
        nodes[node.id] = node
    return nodes, diags


def validate_frontmatter(vault: Path, node: Node, diags: Diagnostics) -> None:
    """按《Markdown 文档规范》3 与校验清单检查单节点的 frontmatter。"""
    rel = node.path.relative_to(vault).as_posix()
    loc = {"file": rel, "node": node.id}
    for k in REQUIRED_FIELDS:
        if not node.fm.get(k):
            diags.error("missing_field", f"frontmatter 缺少 `{k}`", **loc)
    if not RE_ID_OK.match(node.id):
        diags.error("bad_id", f"id `{node.id}` 含非法字符", **loc)
    status = node.fm.get("status")
    if status and status not in STATUS_VALUES:
        diags.error("bad_status", f"status `{status}` 不合法（可选 {'/'.join(STATUS_VALUES)}）", **loc)
    for k in LAYOUT_KEYS:
        if k in node.fm:
            diags.error("layout_in_frontmatter", f"frontmatter 混入布局字段 `{k}`，布局只存 layout.json", **loc)
    _validate_years(node, diags, loc)


def _validate_years(node: Node, diags: Diagnostics, loc: dict) -> None:
    for k in ("year", "start_year", "end_year"):
        v = node.fm.get(k)
        if v is None:
            continue
        if not isinstance(v, int) or isinstance(v, bool) or not 1000 <= v <= 2999:
            diags.error("bad_year", f"{k} `{v}` 不是四位整数", **loc)
    sy, ey = node.fm.get("start_year"), node.fm.get("end_year")
    if isinstance(sy, int) and isinstance(ey, int) and ey <= sy:
        diags.error("year_range_inverted", f"时间区间反转 {sy}..{ey}", **loc)
