"""三份数据契约（pydantic v2）：index / layout / ChangeSet。

- index：派生缓存，真值在 md，服务只读（阶段 1 的 core 生成与校验）。
- layout：结构视图的用户数据，唯一可写入口是 PATCH，带 revision 乐观并发。
- ChangeSet：所有 Markdown 写回的唯一入口（阶段 3 使用，这里先把形状定下来）。

三者互不覆盖：改 layout 不碰 md，改 md 不动 layout（详见设计文档 3.4）。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

LAYOUT_SCHEMA_VERSION = 2
NODE_W, NODE_H = 160.0, 60.0


class Strict(BaseModel):
    """契约默认拒绝未知字段：拼错的键必须报错，不能被静默丢弃。"""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- layout

class Point(Strict):
    x: float
    y: float


class Viewport(Strict):
    zoom: float = 0.8
    cx: float = 0.0
    cy: float = 0.0


class GroupBox(Strict):
    name: str
    x: float
    y: float
    w: float
    h: float
    parent: str | None = None
    collapsed: bool = False
    pinned: Literal["expanded", "collapsed"] | None = None
    color: str | None = None


class NodeBox(Strict):
    x: float
    y: float
    w: float = NODE_W
    h: float = NODE_H
    group: str | None = None
    state: Literal["final", "draft"] = "final"
    placedAt: str | None = None   # noqa: N815  （layout.json 里就是这个键名）
    anchor: str | None = None


class RefCard(Strict):
    id: str
    target: str
    x: float
    y: float
    w: float = NODE_W
    h: float = NODE_H
    group: str | None = None


class StickyNote(Strict):
    id: str
    text: str
    x: float
    y: float
    w: float = 180.0
    h: float = 60.0
    group: str | None = None
    color: str | None = None


class ImageBox(Strict):
    id: str
    file: str
    x: float
    y: float
    w: float
    h: float
    group: str | None = None


class EdgeStyle(Strict):
    """只记录用户手工调过的边（拐点、路由）；key 为 `源->目标#类型`。"""

    vertices: list[Point] = Field(default_factory=list)
    router: str | None = None


class LayoutDoc(Strict):
    schema_version: int = LAYOUT_SCHEMA_VERSION
    revision: int = 0
    updated_at: str | None = None
    viewport: Viewport = Field(default_factory=Viewport)
    groups: dict[str, GroupBox] = Field(default_factory=dict)
    nodes: dict[str, NodeBox] = Field(default_factory=dict)
    refs: list[RefCard] = Field(default_factory=list)
    notes: list[StickyNote] = Field(default_factory=list)
    images: list[ImageBox] = Field(default_factory=list)
    edges: dict[str, EdgeStyle] = Field(default_factory=dict)


# ---------------------------------------------------------------- layout patch

class GroupPatch(Strict):
    """分组的部分更新：只发改动过的字段。"""

    name: str | None = None
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    parent: str | None = None
    collapsed: bool | None = None
    pinned: Literal["expanded", "collapsed"] | None = None
    color: str | None = None


class NodePatch(Strict):
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    group: str | None = None
    state: Literal["final", "draft"] | None = None
    placedAt: str | None = None   # noqa: N815
    anchor: str | None = None


class LayoutPatch(Strict):
    """JSON Merge Patch 风格：只发改动过的条目，条目值为 null 表示删除该条目。

    `groups` / `nodes` / `edges` 按条目合并（条目内再按字段合并）；
    `refs` / `notes` / `images` 是带 id 的小集合，给出时整体替换。
    """

    base_revision: int
    viewport: Viewport | None = None
    groups: dict[str, GroupPatch | None] | None = None
    nodes: dict[str, NodePatch | None] | None = None
    edges: dict[str, EdgeStyle | None] | None = None
    refs: list[RefCard] | None = None
    notes: list[StickyNote] | None = None
    images: list[ImageBox] | None = None


class LayoutSaved(Strict):
    revision: int
    updated_at: str
    orphans: list[dict[str, Any]] = Field(default_factory=list)
    backup: str | None = None   # 整体重排前的快照路径（vault 相对路径）


class LayoutRead(Strict):
    layout: LayoutDoc
    orphans: list[dict[str, Any]] = Field(default_factory=list)
    index_revision: int = 0
    generated: bool = False   # 本次读取时刚自动生成了初始布局


# ---------------------------------------------------------------- index（只读）

class IndexNode(BaseModel):
    model_config = ConfigDict(extra="allow")   # 派生字段可增长，前端按需取用

    id: str
    name: str | None = None
    field: str | None = None
    desc: str | None = None
    status: str = "active"
    year: int | None = None
    stub: bool = False
    out: list[str] = Field(default_factory=list)
    in_: list[str] = Field(default_factory=list, alias="in")
    degree: int = 0


class IndexEdge(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    source: str
    target: str
    type: str
    family: str
    year: int | None = None


class IndexDoc(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int
    revision: int
    generated_at: str
    content_hash: str
    nodes: list[IndexNode]
    edges: list[IndexEdge]
    families: list[dict[str, Any]]
    stubs: list[str]
    stats: dict[str, Any]
    errors: list[dict[str, Any]]
    warnings: list[dict[str, Any]]


# ---------------------------------------------------------------- ChangeSet（阶段 3）

class Change(Strict):
    type: Literal["add_edge", "remove_edge", "update_edge", "update_frontmatter"]
    source: str
    target: str | None = None
    relation: str | None = None
    from_relation: str | None = None   # update_edge 时用来定位原来那条边
    year: int | None = None
    note: str | None = None
    fields: dict[str, Any] | None = None
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 1.0


class ChangeSet(Strict):
    base_revision: int                 # 基于哪个 index revision 提出的变更
    changes: list[Change]
    dry_run: bool = True               # 默认只预览；确认后再发一次 dry_run=false


class FileDiff(Strict):
    path: str
    notes: list[str] = Field(default_factory=list)
    diff: str = ""                     # 统一 diff 片段，给人看"改了哪几行"


class ChangeResult(Strict):
    applied: bool
    files: list[FileDiff] = Field(default_factory=list)
    backup: str | None = None          # 写回前的原文快照目录
    index_revision: int = 0


class NodeDetail(Strict):
    id: str
    path: str
    raw: str                           # md 原文，逐字返回
    digest: str
    meta: dict[str, Any] = Field(default_factory=dict)
    out: list[dict[str, Any]] = Field(default_factory=list)
    in_edges: list[dict[str, Any]] = Field(default_factory=list)
    obsidian_uri: str = ""
