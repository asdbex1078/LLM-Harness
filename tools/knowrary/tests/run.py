#!/usr/bin/env python3
"""Knowrary core 自测（零第三方依赖）：python3 tools/knowrary/tests/run.py [关键字]

每个用例在临时目录里搭一个最小 vault，跑 build_index 并断言节点/边/诊断/契约。
覆盖阶段 1 验收点：索引可重建且结果一致、非法 YAML / 未知目标 / 非法年份都有诊断、
改文件后节点和边正确更新。
"""
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import core  # noqa: E402  （必须先注入 sys.path）

REPO = HERE.parent.parent.parent
TYPES_TABLE = REPO / "relation-types.json"
CASES: list = []
_TMPDIRS: list[tempfile.TemporaryDirectory] = []


def case(fn):
    CASES.append(fn)
    return fn


# ---------------------------------------------------------------- 夹具

def make_vault(files: dict[str, str]) -> Path:
    """按 {相对路径: 内容} 建一个临时 vault，并放入真实的关系类型表。"""
    tmp = tempfile.TemporaryDirectory(prefix="knowrary-test-")
    _TMPDIRS.append(tmp)
    vault = Path(tmp.name)
    (vault / "relation-types.json").write_text(TYPES_TABLE.read_text(encoding="utf-8"), encoding="utf-8")
    for rel, text in files.items():
        core.write(vault / rel, text)
    return vault


def node_md(name: str, *, rels: str = "", field: str = "测试", extra: str = "", body: str = "正文") -> str:
    fm = f"---\nname: {name}\nfield: {field}\ndesc: {name} 的一句话摘要\n{extra}---\n"
    rel_block = f"\n## 关系\n{rels}\n" if rels else ""
    return f"{fm}# {name}\n\n{body}\n{rel_block}"


def build(files: dict[str, str]) -> tuple[Path, core.IndexResult]:
    vault = make_vault(files)
    result = core.build_index(vault)
    problems = core.validate_index(result.data)
    assert not problems, f"索引契约不合法：{problems}"
    return vault, result


def codes(result: core.IndexResult, level: str) -> list[str]:
    items = result.diags.errors if level == "error" else result.diags.warnings
    return [d.code for d in items]


def edge_ids(result: core.IndexResult) -> list[str]:
    return [e["id"] for e in result.data["edges"]]


def node_by_id(result: core.IndexResult, nid: str) -> dict:
    for n in result.data["nodes"]:
        if n["id"] == nid:
            return n
    raise AssertionError(f"节点 {nid} 不在索引里：{[n['id'] for n in result.data['nodes']]}")


# ---------------------------------------------------------------- 用例：解析与结构

@case
def 基本解析与邻接():
    _, r = build({
        "nodes/a.md": node_md("A", rels="- 部件:: [[b]] (2018) — 说明文字"),
        "nodes/b.md": node_md("B"),
    })
    assert edge_ids(r) == ["a->b#部件"], edge_ids(r)
    edge = r.data["edges"][0]
    assert (edge["family"], edge["year"], edge["note"]) == ("结构", 2018, "说明文字"), edge
    assert edge["declared_in"] == ["nodes/a.md"], edge
    assert node_by_id(r, "a")["out"] == ["a->b#部件"] and node_by_id(r, "a")["in"] == []
    assert node_by_id(r, "b")["in"] == ["a->b#部件"] and node_by_id(r, "b")["degree"] == 1
    assert r.stats["by_field"] == {"测试": 2}, r.stats


@case
def 旧箭头语法兼容():
    _, r = build({"nodes/a.md": node_md("A", rels="- 部件 → [[b]] 旧说明"), "nodes/b.md": node_md("B")})
    assert edge_ids(r) == ["a->b#部件"], edge_ids(r)
    assert not codes(r, "error"), codes(r, "error")


@case
def 显式_id_优先于文件名():
    _, r = build({"nodes/x.md": node_md("A", extra="id: alpha\n", rels="- 部件:: [[b]]"),
                  "nodes/b.md": node_md("B")})
    assert edge_ids(r) == ["alpha->b#部件"], edge_ids(r)
    assert node_by_id(r, "alpha")["path"] == "nodes/x.md"


@case
def 只读关系区块以外不入图():
    _, r = build({"nodes/a.md": node_md("A", body="正文里写 - 部件:: [[b]] 不算关系", rels="- 依赖:: [[b]]"),
                  "nodes/b.md": node_md("B")})
    assert edge_ids(r) == ["a->b#依赖"], edge_ids(r)


@case
def 关系段之后的章节不当关系解析():
    """规范 4 允许 `## 关系` 后接 `## 参考资料` / `## 待办`，它们既不是关系也不能被吞掉。"""
    md = ("---\nname: A\nfield: 测试\ndesc: A 摘要\n---\n# A\n\n正文\n\n## 关系\n- 部件:: [[b]]\n\n"
          "## 参考资料\n- [某文档](https://example.com)\n\n## 待办\n- [ ] 核实年份\n")
    vault, r = build({"nodes/a.md": md, "nodes/b.md": node_md("B")})
    assert edge_ids(r) == ["a->b#部件"], edge_ids(r)
    assert not codes(r, "error"), codes(r, "error")
    node, _ = core.load_node(vault, vault / "nodes/a.md")
    assert node.rel_tail.startswith("## 参考资料"), repr(node.rel_tail)
    assert "## 待办" in node.rel_tail and "核实年份" in node.rel_tail
    assert "## 参考资料" not in node.body, node.body


@case
def 扫描忽略备份与非节点文件():
    vault, r = build({
        "nodes/a.md": node_md("A"),
        "README.md": "# 说明",
        ".knowrary/backup/20260910/a.md": node_md("旧A"),
        "nodes/.trash/b.md": node_md("B"),
        "nodes/empty.md": "   \n",
        "doc/设计.md": "# 文档",
    })
    assert [n["id"] for n in r.data["nodes"]] == ["a"], r.data["nodes"]
    assert "empty_file" in codes(r, "warning"), codes(r, "warning")


# ---------------------------------------------------------------- 用例：归一与去重

@case
def 互逆类型归一到正向():
    _, r = build({"nodes/a.md": node_md("A", rels="- 属于:: [[b]]"), "nodes/b.md": node_md("B")})
    assert edge_ids(r) == ["b->a#包含"], edge_ids(r)
    assert r.data["edges"][0]["raw_types"] == ["属于"]


@case
def 两侧重复维护合并为一条边():
    _, r = build({"nodes/a.md": node_md("A", rels="- 属于:: [[b]]"),
                  "nodes/b.md": node_md("B", rels="- 包含:: [[a]]")})
    assert edge_ids(r) == ["b->a#包含"], edge_ids(r)
    edge = r.data["edges"][0]
    assert sorted(edge["declared_in"]) == ["nodes/a.md", "nodes/b.md"], edge
    assert sorted(edge["raw_types"]) == ["包含", "属于"], edge
    assert codes(r, "warning").count("duplicate_relation") == 1, codes(r, "warning")


@case
def 对称关系按_id_排序定向():
    _, r = build({"nodes/b.md": node_md("B", rels="- 对比:: [[a]]"),
                  "nodes/a.md": node_md("A", rels="- 对比:: [[b]]")})
    assert edge_ids(r) == ["a->b#对比"], edge_ids(r)
    assert r.data["edges"][0]["symmetric"] is True
    assert codes(r, "warning").count("duplicate_relation") == 1


@case
def 同文件重复声明与自环():
    _, r = build({"nodes/a.md": node_md("A", rels="- 部件:: [[b]]\n- 部件:: [[b]]\n- 相关:: [[a]]"),
                  "nodes/b.md": node_md("B")})
    assert edge_ids(r) == ["a->b#部件"], edge_ids(r)
    assert "duplicate_relation" in codes(r, "warning") and "self_loop" in codes(r, "warning")


@case
def 未登记类型落默认族并警告():
    _, r = build({"nodes/a.md": node_md("A", rels="- 疑似:: [[b]]"), "nodes/b.md": node_md("B")})
    assert r.data["edges"][0]["family"] == "弱关联", r.data["edges"][0]
    assert "unknown_type" in codes(r, "warning")
    fam = {f["name"]: f for f in r.data["families"]}["弱关联"]
    assert fam["default"] is True and "疑似" in fam["types"], fam


# ---------------------------------------------------------------- 用例：stub 与诊断

@case
def 未知目标占位为虚拟_stub():
    _, r = build({"nodes/a.md": node_md("A", rels="- 依赖:: [[ghost]]")})
    assert edge_ids(r) == ["a->ghost#依赖"], edge_ids(r)
    ghost = node_by_id(r, "ghost")
    assert ghost["virtual"] is True and ghost["stub"] is True and ghost["referrers"] == ["nodes/a.md"]
    assert r.data["stubs"] == ["ghost"] and r.stats["missing_targets"] == 1
    assert codes(r, "error") == ["unknown_target"], codes(r, "error")


@case
def status_stub_计入_stub_列表():
    _, r = build({"nodes/a.md": node_md("A", extra="status: stub\n")})
    assert r.data["stubs"] == ["a"] and node_by_id(r, "a")["stub"] is True


@case
def 非法_yaml_有诊断且不丢节点():
    _, r = build({"nodes/a.md": "---\nname: A\n  bad: [1, 2\nfield: 测试\n---\n# A\n"})
    assert codes(r, "error").count("bad_yaml") == 1, codes(r, "error")
    assert node_by_id(r, "a")["id"] == "a"


@case
def 非法年份与区间反转():
    _, r = build({"nodes/a.md": node_md("A", extra="year: 20177\n"),
                  "nodes/b.md": node_md("B", extra="start_year: 2020\nend_year: 2010\n"),
                  "nodes/c.md": node_md("C", extra="year: 2017\n")})
    assert codes(r, "error").count("bad_year") == 1, codes(r, "error")
    assert codes(r, "error").count("year_range_inverted") == 1, codes(r, "error")
    assert r.stats["with_year"] == 2, r.stats  # 20177 仍保留原值，只是报错


@case
def 缺字段_非法status_布局字段_非法关系行():
    _, r = build({"nodes/a.md": "---\nname: A\n---\n# A\n\n## 关系\n- 这行不合法\n",
                  "nodes/b.md": node_md("B", extra="status: 存疑\nx: 100\n")})
    got = sorted(set(codes(r, "error")))
    assert got == ["bad_relation_line", "bad_status", "layout_in_frontmatter", "missing_field"], got


@case
def 重复_id_报错():
    _, r = build({"nodes/a.md": node_md("A", extra="id: same\n"),
                  "nodes/b.md": node_md("B", extra="id: same\n")})
    assert "duplicate_id" in codes(r, "error"), codes(r, "error")


@case
def 演化无年份与正文死链警告():
    _, r = build({"nodes/a.md": node_md("A", rels="- 演化为:: [[b]]", body="正文引用 [[nowhere]]"),
                  "nodes/b.md": node_md("B")})
    warns = codes(r, "warning")
    assert "evolution_without_year" in warns and "dead_body_link" in warns, warns


@case
def 演化边有年份则不警告():
    _, r = build({"nodes/a.md": node_md("A", rels="- 演化为:: [[b]] (2018)"), "nodes/b.md": node_md("B")})
    assert "evolution_without_year" not in codes(r, "warning")


# ---------------------------------------------------------------- 用例：revision 与幂等

@case
def 重复生成结果逐字节一致():
    vault, first = build({"nodes/a.md": node_md("A", rels="- 部件:: [[b]]"), "nodes/b.md": node_md("B")})
    out = core.index_path(vault)
    core.write_json_atomic(out, first.data)
    second = core.build_index(vault, core.load_previous(out))
    assert second.changed is False, "内容未变却报 changed"
    assert second.data["revision"] == first.data["revision"] == 1
    assert second.data["generated_at"] == first.data["generated_at"]
    assert json.dumps(second.data, sort_keys=True) == json.dumps(first.data, sort_keys=True)


@case
def 改文件后节点与边更新且_revision_递增():
    vault, first = build({"nodes/a.md": node_md("A", rels="- 部件:: [[b]]"), "nodes/b.md": node_md("B")})
    out = core.index_path(vault)
    core.write_json_atomic(out, first.data)
    core.write(vault / "nodes/a.md", node_md("A", rels="- 依赖:: [[c]]"))
    core.write(vault / "nodes/c.md", node_md("C"))
    (vault / "nodes/b.md").unlink()
    second = core.build_index(vault, core.load_previous(out))
    assert second.changed is True and second.data["revision"] == 2, second.data["revision"]
    assert edge_ids(second) == ["a->c#依赖"], edge_ids(second)
    assert [n["id"] for n in second.data["nodes"]] == ["a", "c"], second.data["nodes"]
    assert not core.validate_index(second.data)


@case
def 索引损坏时退回全量重建():
    vault, first = build({"nodes/a.md": node_md("A")})
    out = core.index_path(vault)
    core.write(out, "{ 半个 JSON")
    assert core.load_previous(out) is None
    again = core.build_index(vault, core.load_previous(out))
    assert again.data["revision"] == 1 and again.data["content_hash"] == first.data["content_hash"]


@case
def 原子写后可回读且契约合法():
    vault, r = build({"nodes/a.md": node_md("A", rels="- 部件:: [[b]]"), "nodes/b.md": node_md("B")})
    out = core.index_path(vault)
    core.write_json_atomic(out, r.data)
    assert not list(out.parent.glob("index.json.*.tmp")), "临时文件没清掉"
    assert not core.validate_index(core.load_json(out))


@case
def 契约校验能抓出被改坏的索引():
    _, r = build({"nodes/a.md": node_md("A", rels="- 部件:: [[b]]"), "nodes/b.md": node_md("B")})
    broken = json.loads(json.dumps(r.data))
    broken["nodes"] = [n for n in broken["nodes"] if n["id"] != "b"]
    assert core.validate_index(broken), "删掉边端点却没报错"
    broken2 = json.loads(json.dumps(r.data))
    broken2["edges"][0]["type"] = "依赖"
    assert core.validate_index(broken2), "改坏 edge id 却没报错"


# ---------------------------------------------------------------- 用例：真实 vault

@case
def 真实_vault_无错误():
    if not (REPO / "nodes").is_dir():
        print("    （跳过：仓库里没有 nodes/）", end="")
        return
    r = core.build_index(REPO)
    assert not core.validate_index(r.data), core.validate_index(r.data)
    assert r.stats["errors"] == 0, [d.render() for d in r.diags.errors]
    assert r.stats["nodes"] > 50 and r.stats["edges"] > 100, r.stats


# ---------------------------------------------------------------- 执行

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
