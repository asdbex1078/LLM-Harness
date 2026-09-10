"""Markdown / JSON 读写与 frontmatter 解析（零第三方依赖，有 pyyaml 时优先用它）。

只做 IO 与文本层的事：目录扫描、frontmatter 拆分与回写、行内 md 清洗。
知识层语义（关系、归族、校验）在 relations.py / parser.py。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path

NODE_DIRS = ("nodes", "fields")
IGNORE_DIRS = {".obsidian", ".knowrary", ".git", "tools", "assets", "node_modules", ".trash", "doc"}

# 旧语法：- 类型 → [[目标]]      新语法：- 类型:: [[目标]] (2018) — 说明
RE_OLD_REL = re.compile(r"^-\s*(.+?)\s*→\s*\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]\s*(.*)$")
RE_NEW_REL = re.compile(
    r"^-\s*(?P<type>[^:\s]+)::\s*\[\[(?P<target>[^\]|#]+)(?:[|#][^\]]*)?\]\]"
    r"\s*(?:\((?P<year>\d{4})\))?\s*(?:[—-]+\s*(?P<note>.*))?$"
)
RE_LINK = re.compile(r"\[\[([^\]|#]+)")
RE_REL_HEADER = re.compile(r"^## 关系\s*$", re.M)
RE_NEXT_H2 = re.compile(r"^##\s+", re.M)   # 关系段的下界：规范 4 里 `## 关系` 后面还能有 `## 参考资料` / `## 待办`
RE_ID_OK = re.compile(r"^[^\s/\\:*?\"<>|]+$")

FM_ORDER = ["id", "name", "field", "type", "status", "year", "start_year", "end_year",
            "aliases", "tags", "desc", "learned", "source"]


def json_safe(v):
    """把 frontmatter 里的值转成 JSON 可序列化形式（pyyaml 会把 `learned: 2026-09-10` 解析成 date）。"""
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [json_safe(x) for x in v]
    if isinstance(v, dict):
        return {str(k): json_safe(x) for k, x in v.items()}
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def load_json(p: Path) -> dict:
    return json.loads(read(p))


def write_json_atomic(p: Path, data: dict) -> None:
    """临时文件 + rename 原子写：崩溃或并发读都不会看到半个 JSON。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def parse_yaml(src: str) -> dict:
    """返回 dict；非 dict 的 YAML 视为空。解析失败抛 ValueError，由调用方转成诊断。"""
    try:
        import yaml  # type: ignore
    except ImportError:
        return _mini_yaml(src)
    try:
        data = yaml.safe_load(src) or {}
    except Exception as exc:  # yaml.YAMLError 及其子类
        raise ValueError(str(exc).replace("\n", " ")) from exc
    if not isinstance(data, dict):
        raise ValueError("frontmatter 顶层不是键值映射")
    return data


def _mini_yaml(src: str) -> dict:
    """够用的子集：`k: v`、`k: [a, b]`、块列表 `- x`。"""
    out: dict = {}
    key = None
    for line in src.splitlines():
        if re.match(r"^\s+-\s+", line) and key:
            out.setdefault(key, [])
            if isinstance(out[key], list):
                out[key].append(line.split("-", 1)[1].strip())
            continue
        m = re.match(r"^([\w_]+):\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        out[key] = _mini_scalar(val)
    return out


def _mini_scalar(val: str):
    if val.startswith("[") and val.endswith("]"):
        return [s.strip().strip("'\"") for s in val[1:-1].split(",") if s.strip()]
    if val == "":
        return []
    if val in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", val):
        return int(val)
    return val.strip("'\"")


def split_frontmatter(text: str) -> tuple[dict, str]:
    """拆出 frontmatter 与正文；没有 frontmatter 时返回空 dict。解析失败抛 ValueError。"""
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}, text
    return parse_yaml(m.group(1)), text[m.end():]


def yaml_scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    s = str(v)
    if s == "" or re.search(r"[:#\[\]{}&*!|>'\"%@`]|^\s|\s$|^-", s) or s in ("null", "true", "false", "~"):
        return json.dumps(s, ensure_ascii=False)
    return s


def dump_frontmatter(fm: dict) -> str:
    lines = ["---"]
    keys = [k for k in FM_ORDER if k in fm] + [k for k in fm if k not in FM_ORDER]
    for k in keys:
        v = fm[k]
        if v is None or v == [] or v == "":
            if k in ("end_year",):
                lines.append(f"{k}: null")
            continue
        if isinstance(v, list):
            lines.append(f"{k}:")
            lines.extend(f"  - {yaml_scalar(x)}" for x in v)
        else:
            lines.append(f"{k}: {yaml_scalar(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def strip_md(s: str) -> str:
    s = re.sub(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]", r"\1", s)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"\*\*([^*]*)\*\*", r"\1", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return s.strip()


def first_paragraph(body: str, limit: int = 80) -> str:
    main = RE_REL_HEADER.split(body)[0]
    para: list[str] = []
    for raw in main.splitlines():
        t = raw.strip()
        if not t or t.startswith("#") or t.startswith("```") or t.startswith(">"):
            if para:
                break
            continue
        para.append(strip_md(t.lstrip("-*0123456789. ")))
        if len("".join(para)) > limit:
            break
    text = " ".join(para)
    return text[:limit].rstrip("，,。；;：: ") + ("…" if len(text) > limit else "")


def walk_md(vault: Path) -> list[Path]:
    """vault 里有 nodes/ 或 fields/ 时只扫这两个约定目录（仓库里的其他 md 不是节点）；否则扫整个 vault。

    忽略 IGNORE_DIRS、隐藏目录（含 .knowrary/backup）、README 和编辑器临时文件。
    """
    roots = [vault / d for d in NODE_DIRS if (vault / d).is_dir()] or [vault]
    out = []
    for p in sorted(q for r in roots for q in r.rglob("*.md")):
        rel = p.relative_to(vault)
        if any(part in IGNORE_DIRS or part.startswith(".") for part in rel.parts[:-1]):
            continue
        if p.name == "README.md" or p.name.startswith(("~$", ".")) or p.name.endswith(".tmp.md"):
            continue
        out.append(p)
    return out
