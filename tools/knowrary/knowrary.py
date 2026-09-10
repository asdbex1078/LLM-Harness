#!/usr/bin/env python3
"""Knowrary · 迁移 / 导入 / 校验工具（第二版数据规范）

子命令：
  vault    把旧 vault（`- 类型 → [[目标]]`、frontmatter 只有 tags/source）迁移成第二版结构
  check    按《Markdown 文档规范》校验一个 vault，输出诊断
  context  输出类型表 / 全部 id / 与文章相关的节点（供 knowrary-import skill 使用）
  apply    把方案 JSON 校验后写入 vault（供 knowrary-import skill 使用）
  article  无人值守版：脚本自己调 LLM 把文章拆成节点并写入（提示词在 prompts/article.md）
  llm      查看 / 测试 LLM 配置（.knowrary/llm.local.json，见 llm.example.json）

零第三方依赖（有 pyyaml 时用它解析 frontmatter，没有则用内置的简易解析）。
LLM 后端见 llm_backend.py：配置文件里定义多个 provider（claude-cli / anthropic / openai 兼容），
按角色（learn 学习、review 审核）选用；没有配置文件时退回 `claude -p`。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import llm_backend  # 同目录模块
from core import (Diagnostics, Edge, Node, RelationTypes, build_index, build_initial_layout,
                  dump_frontmatter, find_orphans, first_paragraph, index_path, layout_path,
                  load_json, load_previous, load_relation_types, load_vault, read, stamp,
                  validate_index, write, write_json_atomic)
from core.mdio import RE_ID_OK, RE_LINK

HERE = Path(__file__).resolve().parent
TODAY = dt.date.today().isoformat()


# ---------------------------------------------------------------- vault 迁移

@dataclass
class MigrateReport:
    nodes: int = 0
    stubs_created: list[str] = field(default_factory=list)
    type_map: Counter = field(default_factory=Counter)
    unmapped: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    flipped: int = 0
    dedup_dropped: list[str] = field(default_factory=list)
    body_links_missing: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    warnings: list[str] = field(default_factory=list)


def map_legacy_edge(e: Edge, legacy: dict, rep: MigrateReport) -> Edge:
    """旧类型 → 新类型；flip 时交换方向。"""
    rule = legacy.get(e.type)
    rep.type_map[f"{e.type} → {rule['to'] if rule else e.type}"] += 1
    if not rule:
        rep.unmapped[e.type].append(f"{e.source} → {e.target}")
        return Edge(e.source, e.type, e.target, e.year, e.note, origin=e.type)
    if rule.get("flip"):
        rep.flipped += 1
        return Edge(e.target, rule["to"], e.source, e.year, e.note, origin=e.type)
    return Edge(e.source, rule["to"], e.target, e.year, e.note, origin=e.type)


def dedupe_edges(edges: list[Edge], rt: RelationTypes, rep: MigrateReport) -> list[Edge]:
    """去掉：完全重复；互逆重复（保留 canonical 一侧）；对称重复（保留 id 小的一侧）。"""
    seen: set[tuple] = set()
    keep: list[Edge] = []
    index = {(e.source, e.type, e.target) for e in edges}
    for e in edges:
        key = (e.source, e.type, e.target)
        if key in seen:
            continue
        seen.add(key)
        canon = rt.canonical(e.type)
        inv = rt.inverse(e.type)
        if canon and (e.target, canon, e.source) in index:
            rep.dedup_dropped.append(f"{e.source} {e.type} {e.target}（已有 {e.target} {canon} {e.source}）")
            continue
        if not canon and inv and rt.canonical(inv) == e.type:
            pass  # 我是正向，保留
        if rt.symmetric(e.type) and (e.target, e.type, e.source) in index and e.target < e.source:
            rep.dedup_dropped.append(f"{e.source} {e.type} {e.target}（对称边保留在 {e.target}）")
            continue
        keep.append(e)
    return keep


def build_frontmatter(node: Node, folder: str, field_name: str, rep: MigrateReport) -> dict:
    old = node.fm
    tags = [t for t in (old.get("tags") or []) if t not in ("待学", "MOC")]
    h1 = re.search(r"^# (.+)$", node.body, re.M)
    fm: dict = {
        "name": h1.group(1).strip() if h1 else node.id,
        "field": field_name,
    }
    if "待学" in (old.get("tags") or []):
        fm["status"] = "stub"
    if tags:
        fm["tags"] = tags
    fm["desc"] = first_paragraph(node.body) or "待补充"
    if fm["desc"] == "待补充" and fm.get("status") != "stub":
        rep.warnings.append(f"{node.id}: 正文为空或过短，desc 置为“待补充”")
    if old.get("source"):
        fm["source"] = old["source"]
    if folder:
        fm.setdefault("tags", [])
        sub = re.sub(r"^\d+-", "", folder)
        if sub not in fm["tags"]:
            fm["tags"].append(sub)
    return fm


def render_node(fm: dict, body: str, edges: list[Edge], rel_tail: str = "") -> str:
    """frontmatter + 正文 + `## 关系` + 关系段之后的原文（`## 参考资料` / `## 待办` 等，逐字保留）。"""
    body = body.rstrip() + "\n"
    rel = "\n## 关系\n" + ("\n".join(e.line() for e in edges) + "\n" if edges else "")
    tail = ("\n" + rel_tail.lstrip("\n")) if rel_tail.strip() else ""
    return dump_frontmatter(fm) + body + rel + tail


def stub_text(target: str, referrers: list[str], field_name: str) -> str:
    fm = {"name": target, "field": field_name, "status": "stub", "desc": "待补充"}
    body = (f"# {target}\n\n> 空壳节点（stub）：被 {', '.join(f'[[{r}]]' for r in referrers[:5])} 引用，"
            f"尚未学习补充。\n")
    return render_node(fm, body, [])


@dataclass
class MigratePaths:
    """一次迁移的源 / 目标 vault 与统一顶层领域。"""

    src: Path
    dst: Path
    field_name: str


def write_migrated_nodes(nodes: dict[str, Node], by_source: dict[str, list[Edge]],
                         paths: MigratePaths, rep: MigrateReport) -> None:
    """写节点：MOC（tags 含 MOC）落 fields/，其余按原子目录落 nodes/<子目录>/。"""
    for n in nodes.values():
        rel_folder = str(n.path.parent.relative_to(paths.src)) if n.path.parent != paths.src else ""
        is_moc = "MOC" in (n.fm.get("tags") or [])
        fm = build_frontmatter(n, "" if is_moc else rel_folder, paths.field_name, rep)
        if is_moc:
            fm["type"] = "领域总览"
            out = paths.dst / "fields" / f"{n.id}.md"
        else:
            out = paths.dst / "nodes" / rel_folder / f"{n.id}.md"
        write(out, render_node(fm, n.body, by_source.get(n.id, []), n.rel_tail))


def cmd_vault(args: argparse.Namespace) -> None:
    src, dst = Path(args.src).resolve(), Path(args.dst).resolve()
    if dst.exists() and any(dst.iterdir()) and not args.force:
        raise SystemExit(f"目标目录非空：{dst}（加 --force 覆盖其中的 nodes/ fields/）")
    rt = RelationTypes(load_json(HERE / "relation-types.v2.json"))
    legacy = load_json(HERE / "legacy-types.json")["map"]
    nodes, diags = load_vault(src)
    rep = MigrateReport(nodes=len(nodes))
    rep.warnings.extend(d.render() for d in diags.items)

    # 1. 边：映射 + 翻转 + 去重
    mapped: list[Edge] = []
    for n in nodes.values():
        mapped.extend(map_legacy_edge(e, legacy, rep) for e in n.edges)
    mapped = dedupe_edges(mapped, rt, rep)
    by_source: dict[str, list[Edge]] = defaultdict(list)
    for e in mapped:
        by_source[e.source].append(e)

    # 2. stub：所有边目标 + 正文链接里不存在的节点
    referrers: dict[str, list[str]] = defaultdict(list)
    for e in mapped:
        if e.target not in nodes:
            referrers[e.target].append(e.source)
    for n in nodes.values():
        for link in set(RE_LINK.findall(n.body)):
            if link not in nodes and link not in referrers:
                rep.body_links_missing[n.id].append(link)

    # 3. 写节点与 stub
    write_migrated_nodes(nodes, by_source, MigratePaths(src, dst, args.field), rep)
    for target, refs in sorted(referrers.items()):
        write(dst / "nodes" / "_stubs" / f"{target}.md", stub_text(target, refs, args.field))
        rep.stubs_created.append(target)

    # 4. 其他文件
    if (src / "assets").exists():
        shutil.copytree(src / "assets", dst / "assets", dirs_exist_ok=True)
    (dst / ".knowrary" / "backup").mkdir(parents=True, exist_ok=True)
    shutil.copy(HERE / "relation-types.v2.json", dst / "relation-types.json")
    report = dst / ".knowrary" / "MIGRATION-REPORT.md"
    write(report, migrate_report_md(rep, src, dst, mapped))
    print(read(report))


def migrate_report_md(rep: MigrateReport, src: Path, dst: Path, edges: list[Edge]) -> str:
    fam = Counter()
    rt = RelationTypes(load_json(HERE / "relation-types.v2.json"))
    for e in edges:
        fam[rt.family(e.type)] += 1
    L = [f"# 迁移报告 {TODAY}", "", f"- 源：`{src}`", f"- 目标：`{dst}`",
         f"- 节点：{rep.nodes} 个；新建 stub：{len(rep.stubs_created)} 个；边：{len(edges)} 条"
         f"（方向翻转 {rep.flipped} 条，去重丢弃 {len(rep.dedup_dropped)} 条）", "",
         "## 边按族分布", ""]
    L += [f"- {f}：{c}" for f, c in fam.most_common()]
    L += ["", "## 未映射的旧类型（原样保留，归弱关联族，需人工决定）", ""]
    L += [f"- `{t}`（{len(v)} 条）：{'；'.join(v[:4])}" for t, v in sorted(rep.unmapped.items(), key=lambda x: -len(x[1]))] or ["- 无"]
    L += ["", "## 新建的 stub", "", "- " + ("、".join(rep.stubs_created) or "无")]
    L += ["", "## 去重丢弃的边", ""] + ([f"- {d}" for d in rep.dedup_dropped] or ["- 无"])
    L += ["", "## 正文链接到不存在的节点（未建 stub，仅提示）", ""]
    L += [f"- {n}: {', '.join(v)}" for n, v in rep.body_links_missing.items()] or ["- 无"]
    L += ["", "## 其他警告", ""] + ([f"- {w}" for w in rep.warnings] or ["- 无"])
    L += ["", "## 类型映射明细", ""] + [f"- {k}: {c}" for k, c in rep.type_map.most_common()]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- check

def check_secret_leak(vault: Path) -> list[str]:
    """本地 LLM 配置（含密钥）不允许被 git 跟踪；仓库开源时这是最后一道闸。"""
    try:
        proc = subprocess.run(["git", "-C", str(vault), "ls-files", "--", "*.local.json", "**/*.local.json"],
                              capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    return [f"{f}: 本地配置被 git 跟踪，可能泄露密钥。执行 `git rm --cached {f}` 并确认 .gitignore 含 `*.local.json`"
            for f in proc.stdout.split()]


def print_diagnostics(diags: Diagnostics, extra_errors: list[str], max_warn: int) -> int:
    """统一的诊断输出（index / check 共用）。返回错误条数。"""
    errors = [d.render() for d in sorted(diags.errors, key=lambda d: (d.file, d.code))] + extra_errors
    warns = [d.render() for d in sorted(diags.warnings, key=lambda d: (d.file, d.code))]
    for e in errors:
        print("  \u2717", e)
    for w in warns[:max_warn]:
        print("  \u26a0", w)
    if len(warns) > max_warn:
        print(f"  \u2026 还有 {len(warns) - max_warn} 条警告（--max-warn 调整）")
    return len(errors)


def cmd_index(args: argparse.Namespace) -> None:
    """全量重建 index.json：内容不变则不落盘、不动 revision。"""
    vault = Path(args.vault).resolve()
    out = Path(args.out).resolve() if args.out else index_path(vault)
    result = build_index(vault, load_previous(out))
    problems = validate_index(result.data)
    if args.stdout:
        json.dump(result.data, sys.stdout, ensure_ascii=False, indent=2)
        print()
    written = False
    if not args.stdout and (result.changed or not out.exists() or args.force):
        write_json_atomic(out, result.data)
        written = True
    s = result.stats
    state = "内容有变化" if result.changed else "内容未变化"
    print(f"节点 {s['nodes']}（stub {s['stubs']}，缺失目标 {s['missing_targets']}），边 {s['edges']}，"
          f"错误 {s['errors']}，警告 {s['warnings']}")
    print(f"revision {result.data['revision']}（{state}），"
          f"{'已写入 ' + str(out.relative_to(vault) if out.is_relative_to(vault) else out) if written else '未写盘'}")
    print("  边分族：" + "，".join(f"{k} {v}" for k, v in s["by_family"].items()))
    errors = print_diagnostics(result.diags, [], args.max_warn)
    for prob in problems:
        print("  \u2717 索引契约：", prob)
    sys.exit(1 if problems or (args.strict and errors) else 0)


def cmd_layout(args: argparse.Namespace) -> None:
    """layout init：按 field / 子目录生成初始布局；layout check：校验引用列出孤立记录。"""
    vault = Path(args.vault).resolve()
    path = layout_path(vault)
    index = build_index(vault, load_previous(index_path(vault))).data
    if args.action == "init":
        if path.exists() and not args.force:
            raise SystemExit(f"{path.relative_to(vault)} 已存在（加 --force 重新生成，会丢弃现有位置）")
        doc = stamp(build_initial_layout(index))
        write_json_atomic(path, doc)
        print(f"已生成 {path.relative_to(vault)}：分组 {len(doc['groups'])}，节点 {len(doc['nodes'])}，"
              f"revision {doc['revision']}")
        return
    if not path.exists():
        raise SystemExit(f"{path.relative_to(vault)} 不存在，先跑 `layout init` 或启动服务")
    doc = load_json(path)
    orphans = find_orphans(doc, index, vault)
    inbox = sorted({n["id"] for n in index["nodes"] if not n.get("virtual")} - set(doc.get("nodes", {})))
    print(f"revision {doc.get('revision')}，分组 {len(doc.get('groups', {}))}，"
          f"已放置节点 {len(doc.get('nodes', {}))}，Inbox {len(inbox)}，孤立记录 {len(orphans)}")
    for o in orphans[: args.max_warn]:
        print(f"  ⚠ [{o['kind']}] {o['id']}：{o['reason']}")
    for nid in inbox[:10]:
        print(f"  · Inbox：{nid}")
    sys.exit(0)


def cmd_check(args: argparse.Namespace) -> None:
    """按规范校验 vault：复用 index 的解析与诊断，额外查密钥泄露与索引契约。"""
    vault = Path(args.vault).resolve()
    result = build_index(vault)
    s = result.stats
    extra = check_secret_leak(vault) + [f"索引契约：{p}" for p in validate_index(result.data)]
    print(f"节点 {s['nodes']}（stub {s['stubs']}），边 {s['edges']}，"
          f"错误 {s['errors'] + len(extra)}，警告 {s['warnings']}")
    sys.exit(1 if print_diagnostics(result.diags, extra, args.max_warn) else 0)


# ---------------------------------------------------------------- LLM 输出解析

def extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < 0:
            raise SystemExit("LLM 输出中找不到 JSON：\n" + text[:800])
        return json.loads(text[start:end + 1])


# ---------------------------------------------------------------- article

def select_related(nodes: dict[str, Node], text: str, limit: int = 60) -> list[Node]:
    toks = {t for t in re.findall(r"[a-z0-9_+#.-]+|[一-鿿]{2,4}", text.lower()) if len(t) >= 2}
    scored = []
    for n in nodes.values():
        names = " ".join([n.id, str(n.fm.get("name", "")), *(n.fm.get("aliases") or []),
                          *(n.fm.get("tags") or [])]).lower()
        desc = str(n.fm.get("desc", "")).lower()
        s = sum(3 * len(t) for t in toks if t in names) + sum(len(t) for t in toks if t in desc)
        if s >= 6:  # 至少命中名字里的一个词，或 desc 里的多个词
            scored.append((s, n))
    scored.sort(key=lambda x: -x[0])
    return [n for _, n in scored[:limit]]


def build_article_prompt(nodes: dict[str, Node], rt: RelationTypes, article: str, field_name: str) -> str:
    tpl = read(HERE / "prompts" / "article.md")
    related = select_related(nodes, article)
    rel_lines = [f"- {n.id}｜{n.fm.get('desc', '')}｜边: "
                 + ("; ".join(f"{e.type}→{e.target}" for e in n.edges[:8]) or "(无)") for n in related]
    return (tpl.replace("{{relation_types}}", rt.describe())
            .replace("{{field}}", field_name)
            .replace("{{all_ids}}", "、".join(sorted(nodes)) or "(空)")
            .replace("{{related_nodes}}", "\n".join(rel_lines) or "(无)")
            .replace("{{article}}", article))


@dataclass
class ImportTarget:
    """一次导入的落点：写进哪个 vault、算哪个领域、放哪个子目录、来源标记。"""

    vault: Path
    field_name: str
    folder: str | None
    source: str

    @property
    def node_dir(self) -> Path:
        return self.vault / "nodes" / (self.folder or self.field_name)


@dataclass
class ImportResult:
    written: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    dropped_edges: list[str] = field(default_factory=list)
    unknown_types: list[str] = field(default_factory=list)
    plan: dict = field(default_factory=dict)


def validate_plan(plan: dict, nodes: dict[str, Node], rt: RelationTypes, res: ImportResult) -> None:
    new_ids = {n["id"] for n in plan.get("nodes", [])}
    stub_ids = {s["id"] for s in plan.get("stubs", [])}
    legal = set(nodes) | new_ids | stub_ids
    for n in plan.get("nodes", []):
        if not RE_ID_OK.match(n["id"]):
            raise SystemExit(f"非法 id：{n['id']}")
        if n["id"] in nodes:
            res.skipped.append(f"{n['id']}（已存在，未覆盖；建议改为 merge_into）")
        kept = []
        for r in n.get("relations", []):
            if r["target"] not in legal or r["target"] == n["id"]:
                res.dropped_edges.append(f"{n['id']} {r['type']} → {r['target']}（目标不存在）")
                continue
            if not rt.known(r["type"]):
                res.unknown_types.append(f"{n['id']} {r['type']} → {r['target']}")
            kept.append(r)
        n["relations"] = kept
        for link in set(RE_LINK.findall(n.get("body", ""))):
            if link not in legal:
                plan.setdefault("stubs", []).append({"id": link, "name": link, "desc": "待补充",
                                                     "why": f"正文 [[{link}]] 引用但不存在"})
                legal.add(link)


def node_from_plan(n: dict, field_name: str, source: str) -> tuple[dict, str, list[Edge]]:
    fm = {"name": n.get("name") or n["id"], "field": field_name, "desc": n.get("desc") or "待补充",
          "learned": TODAY, "source": source}
    for k in ("type", "year", "aliases", "tags"):
        if n.get(k):
            fm[k] = n[k]
    body = f"# {fm['name']}\n\n" + (n.get("body") or "").strip() + "\n"
    edges = [Edge(n["id"], r["type"], r["target"], r.get("year"), (r.get("note") or "").strip())
             for r in n.get("relations", [])]
    return fm, body, edges


def plan_to_outputs(plan: dict, nodes: dict[str, Node], target: ImportTarget) -> list[tuple[Path, str]]:
    """方案 JSON → [(路径, 文件内容)]。已存在的节点跳过。"""
    outputs: list[tuple[Path, str]] = []
    for n in plan.get("nodes", []):
        if n["id"] in nodes:
            continue
        fm, body, edges = node_from_plan(n, target.field_name, target.source)
        outputs.append((target.node_dir / f"{n['id']}.md", render_node(fm, body, edges)))
    for s in plan.get("stubs", []):
        if s["id"] in nodes or any(p.stem == s["id"] for p, _ in outputs):
            continue
        fm = {"name": s.get("name") or s["id"], "field": target.field_name, "status": "stub",
              "desc": s.get("desc") or "待补充", "source": target.source}
        body = f"# {fm['name']}\n\n> 空壳节点（stub）：{s.get('why', '')}\n"
        outputs.append((target.vault / "nodes" / "_stubs" / f"{s['id']}.md", render_node(fm, body, [])))
    return outputs


def apply_plan(plan: dict, target: ImportTarget, dry_run: bool) -> None:
    vault = target.vault
    rt = load_relation_types(vault)
    nodes, _ = load_vault(vault)
    res = ImportResult(plan=plan)
    validate_plan(plan, nodes, rt, res)
    outputs = plan_to_outputs(plan, nodes, target)
    print_import_report(res, outputs, vault, dry_run)
    if dry_run:
        for p, text in outputs:
            print(f"\n{'=' * 70}\n{p.relative_to(vault)}\n{'=' * 70}\n{text}")
        return
    for p, text in outputs:
        write(p, text)
    stem = re.sub(r"[^\w一-鿿-]+", "-", target.source)[:60]
    log = vault / ".knowrary" / "imports" / f"{TODAY}-{stem}.json"
    write(log, json.dumps(plan, ensure_ascii=False, indent=2))
    print(f"\n已写入 {len(outputs)} 个文件；方案存于 {log.relative_to(vault)}")


def cmd_context(args: argparse.Namespace) -> None:
    """给 skill / 人用的上下文：类型表、全部 id、与文章最相关的节点。"""
    vault = Path(args.vault).resolve()
    rt = load_relation_types(vault)
    nodes, _ = load_vault(vault)
    text = read(Path(args.article)) if args.article else ""
    related = select_related(nodes, text) if text else []
    print("## 可用关系类型\n" + rt.describe())
    print(f"\n## 已有节点（{len(nodes)} 个，链接时必须精确使用）\n" + ("、".join(sorted(nodes)) or "(空)"))
    if related:
        print("\n## 与文章最相关的已有节点")
        for n in related:
            edges = "; ".join(f"{e.type}→{e.target}" for e in n.edges[:8]) or "(无)"
            print(f"- {n.id}｜{n.fm.get('desc', '')}｜边: {edges}")


def cmd_apply(args: argparse.Namespace) -> None:
    plan = extract_json(read(Path(args.plan)))
    source = args.source or f"plan {Path(args.plan).stem} {TODAY}"
    apply_plan(plan, ImportTarget(Path(args.vault).resolve(), args.field, args.folder, source), args.dry_run)


def cmd_article(args: argparse.Namespace) -> None:
    vault = Path(args.vault).resolve()
    art_path = Path(args.article).resolve()
    rt = load_relation_types(vault)
    nodes, _ = load_vault(vault)
    article = read(art_path)
    prompt = build_article_prompt(nodes, rt, article, args.field)
    if args.show_prompt:
        print(prompt)
        return
    cfg, _ = llm_backend.load_config(vault)
    name, provider = llm_backend.resolve_provider(cfg, "learn", args.llm)
    model = args.model or provider.get("model") or "默认模型"
    print(f"图谱 {len(nodes)} 个节点，文章 {len(article)} 字，调用 LLM {name}（{provider['type']} / {model}）…",
          file=sys.stderr)
    plan = extract_json(llm_backend.ask(prompt, provider, args.model))
    target = ImportTarget(vault, args.field, args.folder, f"article {art_path.name} {TODAY}")
    apply_plan(plan, target, args.dry_run)


def print_import_report(res: ImportResult, outputs: list, vault: Path, dry: bool) -> None:
    plan = res.plan
    print(f"\n{'(dry-run) ' if dry else ''}节点 {len(plan.get('nodes', []))} 个，stub {len(plan.get('stubs', []))} 个，"
          f"建议并入 {len(plan.get('merge_into', []))} 条，提议新类型 {len(plan.get('proposed_types', []))} 个")
    print("摘要：", plan.get("summary", ""))
    for p, _ in outputs:
        print("  +", p.relative_to(vault))
    for m in plan.get("merge_into", []):
        print(f"  ⇢ 并入 {m['existing']}：{m.get('why', '')}")
    for t in plan.get("proposed_types", []):
        print(f"  ？ 提议类型 `{t['type']}`（{t.get('family')}）：{t.get('why', '')}")
    for s in res.skipped:
        print("  - 跳过", s)
    for d in res.dropped_edges:
        print("  ✗ 丢弃边", d)
    for u in res.unknown_types:
        print("  ⚠ 未登记类型", u)


# ---------------------------------------------------------------- llm

def cmd_llm(args: argparse.Namespace) -> None:
    vault = Path(args.vault).resolve()
    cfg, path = llm_backend.load_config(vault)
    print(llm_backend.describe(cfg, path))
    if path is None:
        example = vault / ".knowrary" / llm_backend.EXAMPLE_NAME
        print(f"提示：复制 {example} 到 {llm_backend.config_path(vault)} 后编辑，即可切换 provider / 模型")
    if args.action != "test":
        return
    targets = [args.llm] if args.llm else sorted(set(cfg["roles"].values()))
    failed = 0
    for name in targets:
        _, provider = llm_backend.resolve_provider(cfg, "learn", name)
        try:
            reply = llm_backend.ping(provider, args.model)
            ok = "OK" in reply.upper()
            print(f"  {'✓' if ok else '⚠'} {name}: {reply[:80]!r}")
            failed += 0 if ok else 1
        except SystemExit as e:
            failed += 1
            print(f"  ✗ {name}: {e}")
    sys.exit(1 if failed else 0)


# ---------------------------------------------------------------- CLI

def add_data_parsers(sub: argparse._SubParsersAction) -> None:
    """数据层命令：迁移、索引、校验。"""
    v = sub.add_parser("vault", help="旧 vault → 第二版结构")
    v.add_argument("src")
    v.add_argument("dst")
    v.add_argument("--field", default="计算机体系结构", help="迁移节点统一的顶层领域")
    v.add_argument("--force", action="store_true")
    v.set_defaults(fn=cmd_vault)

    i = sub.add_parser("index", help="全量重建 .knowrary/index.json")
    i.add_argument("--vault", required=True)
    i.add_argument("--out", help="输出路径，默认 <vault>/.knowrary/index.json")
    i.add_argument("--stdout", action="store_true", help="只打印 index JSON，不写盘")
    i.add_argument("--force", action="store_true", help="内容未变化也重写文件")
    i.add_argument("--strict", action="store_true", help="有 error 时退出码 1")
    i.add_argument("--max-warn", type=int, default=20)
    i.set_defaults(fn=cmd_index)

    y = sub.add_parser("layout", help="初始布局生成 / 引用校验")
    y.add_argument("action", choices=["init", "check"], nargs="?", default="check")
    y.add_argument("--vault", required=True)
    y.add_argument("--force", action="store_true", help="init 时覆盖已有 layout.json")
    y.add_argument("--max-warn", type=int, default=20)
    y.set_defaults(fn=cmd_layout)

    c = sub.add_parser("check", help="按规范校验 vault")
    c.add_argument("vault")
    c.add_argument("--max-warn", type=int, default=40)
    c.set_defaults(fn=cmd_check)


def add_llm_parsers(sub: argparse._SubParsersAction) -> None:
    """LLM 链路命令：文章拆节点、上下文、写入、配置。"""
    a = sub.add_parser("article", help="文章 → 节点（LLM）")
    a.add_argument("article")
    a.add_argument("--vault", required=True)
    a.add_argument("--field", required=True, help="这批节点的顶层领域")
    a.add_argument("--folder", help="写入 nodes/ 下的子目录，默认同 field")
    a.add_argument("--llm", help="临时指定 provider 名（默认用配置里 roles.learn）")
    a.add_argument("--model", help="临时覆盖模型名")
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--show-prompt", action="store_true", help="只打印提示词，不调用 LLM")
    a.set_defaults(fn=cmd_article)

    x = sub.add_parser("context", help="输出类型表 / 全部 id / 相关节点（供 skill 使用）")
    x.add_argument("--vault", required=True)
    x.add_argument("--article", help="文章路径，用于筛选相关节点")
    x.set_defaults(fn=cmd_context)

    p = sub.add_parser("apply", help="把方案 JSON 校验后写入 vault（供 skill 使用）")
    p.add_argument("plan")
    p.add_argument("--vault", required=True)
    p.add_argument("--field", required=True)
    p.add_argument("--folder")
    p.add_argument("--source", help="写入 frontmatter source 字段，如文章名")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_apply)

    l = sub.add_parser("llm", help="查看 / 测试 LLM 配置")
    l.add_argument("action", choices=["list", "test"], nargs="?", default="list")
    l.add_argument("--vault", required=True)
    l.add_argument("--llm", help="只测试这个 provider（默认测试各角色用到的）")
    l.add_argument("--model")
    l.set_defaults(fn=cmd_llm)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    add_data_parsers(sub)
    add_llm_parsers(sub)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
