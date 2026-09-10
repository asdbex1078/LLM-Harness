#!/usr/bin/env python3
"""服务层自测：.venv/bin/python server/tests/run.py [关键字]

每个用例在临时目录里搭一个最小 vault，用 TestClient 打真实路由。
覆盖阶段 2 验收点：打开就有图、拖动后刷新/重启位置不变、layout 修改不碰 Markdown、
旧 revision 提交被拒绝。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from fastapi.testclient import TestClient  # noqa: E402

from server import index_service  # noqa: E402
from server.app import app  # noqa: E402
from server.paths import core  # noqa: E402

CASES: list = []
_TMPDIRS: list[tempfile.TemporaryDirectory] = []


def case(fn):
    CASES.append(fn)
    return fn


def node_md(name: str, *, rels: str = "", extra: str = "") -> str:
    body = f"---\nname: {name}\nfield: 测试\ndesc: {name} 的摘要\n{extra}---\n# {name}\n\n正文\n"
    return body + (f"\n## 关系\n{rels}\n" if rels else "")


DEFAULT_FILES = {
    "nodes/组A/a.md": node_md("A", rels="- 部件:: [[b]]\n- 演化为:: [[c]] (2020)"),
    "nodes/组A/b.md": node_md("B", rels="- 对比:: [[c]]"),
    "nodes/组B/c.md": node_md("C", extra="year: 2020\n"),
}


def make_vault(files: dict[str, str] | None = None) -> Path:
    tmp = tempfile.TemporaryDirectory(prefix="knowrary-server-")
    _TMPDIRS.append(tmp)
    vault = Path(tmp.name)
    (vault / "relation-types.json").write_text((REPO / "relation-types.json").read_text("utf-8"), "utf-8")
    for rel, text in (files or DEFAULT_FILES).items():
        core.write(vault / rel, text)
    os.environ["KNOWRARY_VAULT"] = str(vault)
    index_service.invalidate()
    return vault


def client(files: dict[str, str] | None = None) -> tuple[TestClient, Path]:
    vault = make_vault(files)
    return TestClient(app), vault


def md_digest(vault: Path) -> str:
    """vault 里所有 md 的内容指纹——用来证明 layout 操作没碰 Markdown。"""
    h = hashlib.sha256()
    for p in core.walk_md(vault):
        h.update(p.relative_to(vault).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def get_layout(c: TestClient) -> dict:
    r = c.get("/api/layout")
    assert r.status_code == 200, r.text
    return r.json()


def patch(c: TestClient, body: dict):
    return c.patch("/api/layout", json=body)


# ---------------------------------------------------------------- 用例

@case
def 首次打开自动生成初始布局():
    c, vault = client()
    assert not (vault / ".knowrary" / "layout.json").exists()
    data = get_layout(c)
    assert data["generated"] is True and data["layout"]["revision"] == 1
    groups, nodes = data["layout"]["groups"], data["layout"]["nodes"]
    assert set(nodes) == {"a", "b", "c"}, nodes
    assert "g-测试" in groups and groups["g-测试--组A"]["parent"] == "g-测试", groups
    assert all(n["state"] == "final" for n in nodes.values())
    assert (vault / ".knowrary" / "layout.json").exists()
    again = get_layout(c)
    assert again["generated"] is False and again["layout"]["revision"] == 1, "第二次不该重新生成"


@case
def 初始布局节点落在自己分组框内():
    c, _ = client()
    layout = get_layout(c)["layout"]
    for nid, n in layout["nodes"].items():
        g = layout["groups"][n["group"]]
        assert g["x"] <= n["x"] and g["y"] <= n["y"], (nid, "越界")
        assert n["x"] + n["w"] <= g["x"] + g["w"] and n["y"] + n["h"] <= g["y"] + g["h"], (nid, "越界")


@case
def 拖拽只发坐标其余字段保留():
    c, _ = client()
    before = get_layout(c)["layout"]
    node_before = before["nodes"]["a"]
    r = patch(c, {"base_revision": before["revision"], "nodes": {"a": {"x": 1234, "y": 567}}})
    assert r.status_code == 200, r.text
    assert r.json()["revision"] == before["revision"] + 1
    after = get_layout(c)["layout"]["nodes"]["a"]
    assert (after["x"], after["y"]) == (1234, 567), after
    for k in ("w", "h", "group", "state"):
        assert after[k] == node_before[k], (k, after[k], node_before[k])


@case
def 重启后位置保持():
    c, vault = client()
    rev = get_layout(c)["layout"]["revision"]
    patch(c, {"base_revision": rev, "nodes": {"b": {"x": 999, "y": 888}}})
    index_service.invalidate()
    fresh = TestClient(app)                       # 新进程等价：重新读盘
    node = get_layout(fresh)["layout"]["nodes"]["b"]
    assert (node["x"], node["y"]) == (999, 888), node
    on_disk = json.loads((vault / ".knowrary" / "layout.json").read_text("utf-8"))
    assert on_disk["nodes"]["b"]["x"] == 999


@case
def 旧_revision_被拒绝且不改文件():
    c, vault = client()
    rev = get_layout(c)["layout"]["revision"]
    assert patch(c, {"base_revision": rev, "nodes": {"a": {"x": 1, "y": 1}}}).status_code == 200
    before = (vault / ".knowrary" / "layout.json").read_text("utf-8")
    r = patch(c, {"base_revision": rev, "nodes": {"a": {"x": 2, "y": 2}}})
    assert r.status_code == 409, r.status_code
    detail = r.json()["detail"]
    assert detail["current_revision"] == rev + 1, detail
    assert (vault / ".knowrary" / "layout.json").read_text("utf-8") == before, "冲突时不该写盘"


@case
def layout_写入不碰_Markdown():
    c, vault = client()
    digest = md_digest(vault)
    rev = get_layout(c)["layout"]["revision"]
    patch(c, {"base_revision": rev, "nodes": {"a": {"x": 5, "y": 5}},
              "notes": [{"id": "nt1", "text": "便签", "x": 0, "y": 0}],
              "viewport": {"zoom": 1.5, "cx": 10, "cy": 20}})
    assert md_digest(vault) == digest, "layout 操作改动了 md"


@case
def 视口与列表整体替换():
    c, _ = client()
    rev = get_layout(c)["layout"]["revision"]
    patch(c, {"base_revision": rev, "viewport": {"zoom": 0.42, "cx": 1, "cy": 2},
              "refs": [{"id": "r1", "target": "c", "x": 10, "y": 10}]})
    layout = get_layout(c)["layout"]
    assert layout["viewport"]["zoom"] == 0.42, layout["viewport"]
    assert [r["id"] for r in layout["refs"]] == ["r1"]
    patch(c, {"base_revision": layout["revision"], "refs": []})
    assert get_layout(c)["layout"]["refs"] == []


@case
def 条目置_null_表示删除():
    c, _ = client()
    layout = get_layout(c)["layout"]
    r = patch(c, {"base_revision": layout["revision"], "nodes": {"a": None}})
    assert r.status_code == 200, r.text
    after = get_layout(c)
    assert "a" not in after["layout"]["nodes"]
    assert after["layout"]["nodes"].keys() == {"b", "c"}


@case
def 新增分组与节点():
    c, _ = client()
    layout = get_layout(c)["layout"]
    r = patch(c, {"base_revision": layout["revision"],
                  "groups": {"g-新": {"name": "新", "x": 0, "y": 3000, "w": 400, "h": 200}},
                  "nodes": {"a": {"x": 24, "y": 3044, "group": "g-新"}}})
    assert r.status_code == 200, r.text
    after = get_layout(c)["layout"]
    assert after["groups"]["g-新"]["collapsed"] is False        # 默认值补齐
    assert after["nodes"]["a"]["group"] == "g-新"


@case
def 非法补丁被拒绝():
    c, _ = client()
    rev = get_layout(c)["layout"]["revision"]
    bad = [
        ({"base_revision": rev, "nodes": {"新节点": {"x": 1}}}, "新增节点缺 y"),
        ({"base_revision": rev, "nodes": {"a": {"群组": "x"}}}, "未知字段"),
        ({"base_revision": rev, "nodes": {"a": {"group": "g-不存在"}}}, "引用不存在的分组"),
        ({"base_revision": rev, "groups": {"g-测试": {"parent": "g-测试"}}}, "自己当父分组"),
        ({"nodes": {"a": {"x": 1, "y": 1}}}, "缺 base_revision"),
    ]
    for body, why in bad:
        r = patch(c, body)
        assert r.status_code == 422, f"{why} 应被拒绝，实际 {r.status_code} {r.text[:120]}"


@case
def 孤立引用只报告不删除():
    c, vault = client()
    layout = get_layout(c)["layout"]
    patch(c, {"base_revision": layout["revision"],
              "nodes": {"幽灵": {"x": 10, "y": 10}},
              "edges": {"a->不存在#部件": {"vertices": [{"x": 1, "y": 2}]}},
              "images": [{"id": "im1", "file": "assets/无.png", "x": 0, "y": 0, "w": 10, "h": 10}]})
    data = get_layout(c)
    kinds = {o["kind"] for o in data["orphans"]}
    assert kinds == {"node", "edge", "image"}, data["orphans"]
    assert "幽灵" in data["layout"]["nodes"], "孤立记录被删掉了"


@case
def 删除_md_后节点变孤立但布局保留():
    c, vault = client()
    get_layout(c)
    (vault / "nodes/组B/c.md").unlink()
    index_service.invalidate()
    data = get_layout(c)
    assert [o["id"] for o in data["orphans"]] == ["c"], data["orphans"]
    assert "c" in data["layout"]["nodes"], "md 删了不代表可以丢用户布局"


@case
def layout_坏文件不被覆盖():
    c, vault = client()
    get_layout(c)
    path = vault / ".knowrary" / "layout.json"
    path.write_text("{ 半个 JSON", encoding="utf-8")
    r = c.get("/api/layout")
    assert r.status_code == 500, r.status_code
    assert path.read_text("utf-8") == "{ 半个 JSON", "坏文件被覆盖了"
    assert "保留" in r.json()["hint"]


@case
def index_接口符合契约():
    c, _ = client()
    data = c.get("/api/index").json()
    assert not core.validate_index(data), core.validate_index(data)
    assert data["stats"]["nodes"] == 3 and data["stats"]["edges"] == 3, data["stats"]
    fams = {f["name"] for f in data["families"]}
    assert {"结构", "依赖", "演化", "对照", "弱关联"} <= fams, fams


@case
def index_随_md_变化而更新():
    c, vault = client()
    assert c.get("/api/index").json()["stats"]["nodes"] == 3
    core.write(vault / "nodes/组B/d.md", node_md("D", rels="- 依赖:: [[c]]"))
    data = c.get("/api/index").json()
    assert data["stats"]["nodes"] == 4, data["stats"]
    assert any(e["id"] == "d->c#依赖" for e in data["edges"])


@case
def health_汇总可用():
    c, _ = client()
    h = c.get("/api/health").json()
    assert h["stats"]["nodes"] == 3 and h["layout_revision"] == 1, h
    assert h["index_revision"] >= 1


def main() -> None:
    keyword = sys.argv[1] if len(sys.argv) > 1 else ""
    picked = [c for c in CASES if keyword in c.__name__]
    failed = []
    for c in picked:
        name = c.__name__.replace("_", " ")
        try:
            c()
            print(f"  ✓ {name}")
        except Exception:
            failed.append(name)
            print(f"  ✗ {name}\n{traceback.format_exc()}")
    print(f"\n{len(picked) - len(failed)}/{len(picked)} 通过" + (f"，失败：{'、'.join(failed)}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
