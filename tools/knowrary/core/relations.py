"""关系类型表与关系解析、方向归一。

渲染与分析只认 5 个族（结构/依赖/演化/对照/弱关联）；具体类型可增长，由
`<vault>/relation-types.json` 维护。互逆类型（属于/包含、源自/演化为…）在索引阶段
统一归一到 canonical 正向类型，对称类型（对比/类比/争议）按 id 排序定向，
这样"两侧都写"的关系在图里只有一条边。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .mdio import RE_NEW_REL, RE_OLD_REL, load_json, strip_md

HERE = Path(__file__).resolve().parent.parent  # tools/knowrary


class RelationTypes:
    def __init__(self, table: dict):
        self.families: list[str] = table["families"]
        self.default_family: str = table["default_family"]
        self.types: dict[str, dict] = table["types"]

    def family(self, t: str) -> str:
        return self.types.get(t, {}).get("family", self.default_family)

    def known(self, t: str) -> bool:
        return t in self.types

    def canonical(self, t: str) -> str | None:
        return self.types.get(t, {}).get("canonical")

    def inverse(self, t: str) -> str | None:
        return self.types.get(t, {}).get("inverse")

    def symmetric(self, t: str) -> bool:
        return bool(self.types.get(t, {}).get("symmetric"))

    def describe(self) -> str:
        by_fam: dict[str, list[str]] = defaultdict(list)
        for t, meta in self.types.items():
            by_fam[meta["family"]].append(t)
        return "\n".join(f"- {fam}：{' / '.join(by_fam[fam])}" for fam in self.families)


def load_relation_types(vault: Path) -> RelationTypes:
    for cand in (vault / "relation-types.json", vault / ".knowrary" / "relation-types.json",
                 HERE / "relation-types.v2.json"):
        if cand.exists():
            return RelationTypes(load_json(cand))
    raise SystemExit("找不到 relation-types.json")


@dataclass
class Edge:
    source: str
    type: str
    target: str
    year: int | None = None
    note: str = ""
    origin: str = ""  # 迁移时记录旧类型

    def line(self) -> str:
        s = f"- {self.type}:: [[{self.target}]]"
        if self.year:
            s += f" ({self.year})"
        if self.note:
            s += f" — {self.note}"
        return s


@dataclass
class NormalizedEdge:
    """索引里的一条边：方向已归一，key 与 layout.json 的 edges key 一致（源->目标#类型）。"""

    source: str
    target: str
    type: str                  # 归一后的正向类型
    family: str
    raw_types: list[str] = field(default_factory=list)   # 原文写法（互逆/对称时可能两种）
    year: int | None = None
    note: str = ""
    declared_in: list[str] = field(default_factory=list)  # 声明该关系的文件（相对路径）
    symmetric: bool = False

    @property
    def id(self) -> str:
        return f"{self.source}->{self.target}#{self.type}"

    def to_dict(self) -> dict:
        d = {"id": self.id, "source": self.source, "target": self.target,
             "type": self.type, "family": self.family}
        if self.raw_types != [self.type]:
            d["raw_types"] = self.raw_types
        if self.year is not None:
            d["year"] = self.year
        if self.note:
            d["note"] = self.note
        if self.symmetric:
            d["symmetric"] = True
        d["declared_in"] = self.declared_in
        return d


def parse_relations(section: str, source: str) -> tuple[list[Edge], list[str]]:
    """解析 `## 关系` 区块。返回 (边, 无法解析的行)。新旧两种语法都接受。"""
    edges, bad = [], []
    for line in section.splitlines():
        t = line.strip()
        if not t or not t.startswith("-"):
            continue
        m = RE_NEW_REL.match(t)
        if m:
            edges.append(Edge(source, m["type"], m["target"].strip(),
                              int(m["year"]) if m["year"] else None, (m["note"] or "").strip()))
            continue
        m = RE_OLD_REL.match(t)
        if m:
            edges.append(Edge(source, m.group(1).strip(), m.group(2).strip(), None, strip_md(m.group(3))))
            continue
        bad.append(t)
    return edges, bad


def normalize_direction(e: Edge, rt: RelationTypes) -> tuple[str, str, str]:
    """返回归一后的 (source, target, type)。

    canonical 表示该类型是反向写法（如 `属于` → `包含`），翻转两端并换成正向类型；
    对称类型无方向，按 id 字典序定端，保证两侧写法落到同一条边。
    """
    src, tgt, typ = e.source, e.target, e.type
    canon = rt.canonical(typ)
    if canon:
        src, tgt, typ = tgt, src, canon
    if rt.symmetric(typ) and src > tgt:
        src, tgt = tgt, src
    return src, tgt, typ
