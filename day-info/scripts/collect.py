#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Knowrary day-info 收集器（零第三方依赖）。

扫描 → 分级打标 → 写入 day-info/pool/YYYY-MM-DD.json 与 .md。

数据源：
- arXiv RSS（cs.AI / cs.CL / cs.LG / cs.SE）
- HuggingFace（经 hf-mirror 镜像）：每日论文 + 新上传且有人气的模型
- GitHub：近 7 天新建的高星项目、热门活跃仓库、跟踪仓库（X6/G6/G6-extension-3d）的版本发布
- 官方博客：OpenAI / DeepMind / Anthropic
- 社区：Hacker News（AI 相关）、IT之家（AI 相关）、精选技术博客 RSS

分级（三档）：
- 必须看：① 与项目强相关（知识图谱 / 知识管理 / Agent / X6 / G6 / Obsidian / 图谱可视化）；
          ② 头部实验室的重大模型发布信号。
- 值得看：论文、新工具、教程、开源项目、博客。
- 仅存档：其它新闻与低相关内容。
- critical 标记 = 必须看且与项目强相关（或跟踪仓库新版本）→ 供「即时提醒」使用。

去重：state.json 记录 45 天内见过的 URL；同日重跑会与当天已有池合并（幂等）。
单源失败只记 error，不影响其它源。

用法：python3 day-info/scripts/collect.py [--repo-dir DIR]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) knowrary-dayinfo/0.1"}
TIMEOUT = 15
SEEN_DAYS = 45
SEEN_KEEP = 90

TRACKED_REPOS = ["antvis/X6", "antvis/G6", "antvis/G6-extension-3d"]

PROJECT_REGEX = re.compile(r"\b(x6|g6|antv|mcp)\b")
PROJECT_WORDS = [
    "知识图谱", "图谱可视化", "知识库", "第二大脑", "长程", "上下文工程", "智能体记忆",
    "agent 记忆", "agent memory", "long-horizon", "knowledge graph", "knowledge base",
    "obsidian", "knowrary", "graph visualization", "second brain", "context engineering",
]
LABS = ["openai", "anthropic", "google", "deepmind", "meta", "deepseek", "kimi", "minimax",
        "zhipu", "qwen", "通义", "月之暗面", "智谱", "字节", "豆包", "腾讯", "阿里", "百度",
        "文心", "混元", "grok", "xai", "mistral", "llama", "gpt", "claude", "gemini"]
RELEASE_WORDS = ["release", "launched", "launch", "introduc", "unveil", "announc", "upgrade",
                 "new version", "adds ", "now supports", "支持", "修复",
                 "发布", "推出", "开源", "上线", "开放", "更新", "generally available", "新增"]
MODEL_WORDS = ["model", "模型", "llm", "大模型", "frontier", "多模态", "multimodal",
               "reasoning", "推理", "agent", "智能体", "moe"]
WORTH_WORDS = ["paper", "论文", "arxiv", "tutorial", "教程", "指南", "guide", "open source",
               "开源", "github", "tool", "工具", "library", "框架", "framework", "benchmark",
               "survey", "综述", "visualization", "可视化", "render", "渲染", "plugin", "插件",
               "sdk", "cli"]
WORTH_SOURCES = {"HF 每日论文", "HF 新模型", "GitHub 新项目", "GitHub 热门",
                 "Simon Willison", "Latent Space", "MarkTechPost", "Raschka", "LangChain",
                 "AWS ML", "OpenAI", "DeepMind", "Anthropic"}

FEEDS = [
    ("Simon Willison", "https://simonwillison.net/atom/everything/"),
    ("Latent Space", "https://www.latent.space/feed"),
    ("MarkTechPost", "https://www.marktechpost.com/feed/"),
    ("Raschka", "https://magazine.sebastianraschka.com/feed"),
    ("LangChain", "https://blog.langchain.dev/rss/"),
    ("AWS ML", "https://aws.amazon.com/blogs/machine-learning/feed/"),
]


def short(e, n=90):
    s = re.sub(r"\s+", " ", str(e))
    return s[:n]


def clean_text(s, limit=None):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit] if limit else s


def fetch(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def parse_date(s):
    s = (s or "").strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3))
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except Exception:
        return ""


def parse_feed(xml_text, limit=12):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        rec = {"title": "", "link": "", "desc": "", "published": ""}
        for child in el:
            ctag = child.tag.rsplit("}", 1)[-1]
            text = "".join(child.itertext()).strip()
            if ctag == "title":
                rec["title"] = clean_text(text)
            elif ctag == "link":
                href = child.attrib.get("href")
                rec["link"] = href or rec["link"] or (text if text.startswith("http") else "")
            elif ctag in ("description", "summary", "content"):
                if not rec["desc"]:
                    rec["desc"] = clean_text(text)
            elif ctag in ("pubDate", "published", "updated", "date"):
                if not rec["published"]:
                    rec["published"] = parse_date(text)
        if rec["title"] and rec["link"]:
            items.append(rec)
        if len(items) >= limit:
            break
    return items


def stale(rec, today, days):
    pub = rec.get("published") or ""
    if not pub:
        return False
    try:
        return (today - dt.date.fromisoformat(pub)).days > days
    except Exception:
        return False


def norm_url(u):
    u = (u or "").strip().split("#", 1)[0]
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def url_key(u):
    return hashlib.sha1(norm_url(u).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- 各数据源

def src_arxiv(errors):
    out = []
    for cat in ("cs.AI", "cs.CL", "cs.LG", "cs.SE"):
        try:
            for rec in parse_feed(fetch("https://rss.arxiv.org/rss/%s" % cat), limit=8):
                rec["source"] = "arXiv %s" % cat
                rec["desc"] = rec["desc"].split("Abstract:", 1)[-1].strip()
                out.append(rec)
        except Exception as e:
            errors.append("arXiv %s: %s" % (cat, short(e)))
    return out


def src_hf(errors):
    out = []
    try:
        j = json.loads(fetch("https://hf-mirror.com/api/daily_papers?limit=15"))
        for p in j:
            paper = p.get("paper") or {}
            title = clean_text(p.get("title") or paper.get("title") or "")
            pid = paper.get("id") or ""
            link = "https://huggingface.co/papers/%s" % pid if pid else ""
            if title and link:
                out.append({"source": "HF 每日论文", "title": title, "link": link,
                            "desc": clean_text(p.get("summary") or "", 220),
                            "published": (p.get("publishedAt") or "")[:10]})
    except Exception as e:
        errors.append("HF daily_papers: %s" % short(e))
    try:
        j = json.loads(fetch("https://hf-mirror.com/api/models?sort=lastModified&limit=40"))
        cand = [m for m in j if (m.get("likes") or 0) > 0]
        cand.sort(key=lambda m: -(m.get("likes") or 0))
        for m in cand[:8]:
            mid = m.get("id") or m.get("modelId") or ""
            if not mid:
                continue
            out.append({"source": "HF 新模型", "title": mid,
                        "link": "https://huggingface.co/%s" % mid,
                        "desc": "likes %s · downloads %s" % (m.get("likes"), m.get("downloads")),
                        "published": (m.get("lastModified") or "")[:10]})
    except Exception as e:
        errors.append("HF models: %s" % short(e))
    return out


def src_gh_new(errors, today):
    out = []
    try:
        since = (today - dt.timedelta(days=7)).isoformat()
        q = urllib.parse.quote("created:>%s stars:>80" % since)
        j = json.loads(fetch("https://api.github.com/search/repositories?q=%s&sort=stars&order=desc&per_page=10" % q))
        for r in (j.get("items") or []):
            out.append({"source": "GitHub 新项目",
                        "title": "%s · ⭐%s" % (r.get("full_name"), r.get("stargazers_count", 0)),
                        "link": r.get("html_url", ""),
                        "desc": (r.get("description") or "")[:200],
                        "published": (r.get("created_at") or "")[:10]})
    except Exception as e:
        errors.append("GitHub search: %s" % short(e))
    return out


def src_gh_trending(errors, today):
    """GitHub「热门活跃」：近 10 天有提交、star>800 的 llm 主题仓库（ossinsight 数据源不可用，已弃用）。"""
    out = []
    try:
        since = (today - dt.timedelta(days=10)).isoformat()
        q = urllib.parse.quote("topic:llm pushed:>%s stars:>800" % since)
        j = json.loads(fetch("https://api.github.com/search/repositories?q=%s&sort=stars&order=desc&per_page=10" % q))
        for r in (j.get("items") or []):
            out.append({"source": "GitHub 热门",
                        "title": "%s · ⭐%s" % (r.get("full_name"), r.get("stargazers_count", 0)),
                        "link": r.get("html_url", ""),
                        "desc": (r.get("description") or "")[:200],
                        "published": (r.get("pushed_at") or "")[:10]})
    except Exception as e:
        errors.append("GitHub 热门: %s" % short(e))
    return out


def src_releases(errors, state, today):
    out = []
    releases = state.setdefault("releases", {})
    for repo in TRACKED_REPOS:
        try:
            j = json.loads(fetch("https://api.github.com/repos/%s/releases?per_page=3" % repo))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                errors.append("releases %s: %s" % (repo, short(e)))
            continue
        except Exception as e:
            errors.append("releases %s: %s" % (repo, short(e)))
            continue
        if not isinstance(j, list) or not j:
            continue
        newest = j[0]
        tag = newest.get("tag_name") or ""
        prev = releases.get(repo)
        if not tag or tag == prev:
            continue
        releases[repo] = tag
        published = (newest.get("published_at") or "")[:10]
        try:
            fresh = bool(published) and (today - dt.date.fromisoformat(published)).days <= 30
        except Exception:
            fresh = False
        if fresh:
            out.append({"source": "版本发布",
                        "title": "%s 发布 %s" % (repo, tag),
                        "link": newest.get("html_url") or "https://github.com/%s/releases" % repo,
                        "desc": clean_text(newest.get("name") or "", 200) or ("%s 最新版本 %s" % (repo, tag)),
                        "published": published})
    return out


def src_hn(errors):
    out = []
    try:
        recs = parse_feed(fetch("https://hnrss.org/frontpage"), limit=30)
        keep = []
        for rec in recs:
            t = rec["title"].lower()
            if re.search(r"\b(ai|llm|gpt|ml|rag|mcp|agent)\b", t) or any(
                    w in t for w in ["model", "visualization", "graph", "compiler", "database", "memory", "inference"]):
                keep.append(rec)
        for rec in keep[:12]:
            rec["source"] = "Hacker News"
            out.append(rec)
    except Exception as e:
        errors.append("HN: %s" % short(e))
    return out


def src_blogs(errors, today):
    out = []
    for name, url in FEEDS:
        try:
            for rec in parse_feed(fetch(url), limit=4):
                if stale(rec, today, 12):
                    continue
                rec["source"] = name
                out.append(rec)
        except Exception as e:
            errors.append("%s: %s" % (name, short(e)))
    return out


def src_labs(errors):
    out = []
    try:
        for rec in parse_feed(fetch("https://openai.com/news/rss.xml"), limit=8):
            rec["source"] = "OpenAI"
            out.append(rec)
    except Exception as e:
        errors.append("OpenAI: %s" % short(e))
    try:
        for rec in parse_feed(fetch("https://deepmind.google/blog/rss.xml"), limit=5):
            rec["source"] = "DeepMind"
            out.append(rec)
    except Exception as e:
        errors.append("DeepMind: %s" % short(e))
    try:
        t = fetch("https://www.anthropic.com/news")
        slugs = []
        for m in re.finditer(r'href="(/news/[a-z0-9-]+)"', t):
            s = m.group(1)
            if s not in slugs:
                slugs.append(s)
        for s in slugs[:6]:
            title, desc = "", ""
            try:
                page = fetch("https://www.anthropic.com%s" % s, timeout=10)
                tm = re.search(r"<title[^>]*>(.*?)</title>", page, re.S)
                if tm:
                    title = clean_text(tm.group(1))
                    title = re.sub(r"\s*[\\|·\-–]\s*Anthropic\s*$", "", title).strip()
                dm = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', page)
                if dm:
                    desc = clean_text(dm.group(1))
            except Exception:
                pass
            if not title:
                title = s.split("/news/")[-1].replace("-", " ")
            out.append({"source": "Anthropic", "title": title,
                        "link": "https://www.anthropic.com%s" % s,
                        "desc": desc, "published": ""})
    except Exception as e:
        errors.append("Anthropic: %s" % short(e))
    return out


def src_ithome(errors):
    out = []
    try:
        recs = parse_feed(fetch("https://www.ithome.com/rss/"), limit=40)
        keep = []
        for rec in recs:
            t = rec["title"]
            if re.search(r"(?i)\b(ai|aigc|llm)\b", t) or any(
                    w in t for w in ["人工智能", "大模型", "机器人", "芯片", "算力", "智能体", "英伟达", "机器学习"]):
                keep.append(rec)
        for rec in keep[:10]:
            rec["source"] = "IT之家"
            out.append(rec)
    except Exception as e:
        errors.append("IT之家: %s" % short(e))
    return out


# ---------------------------------------------------------------- 分级

def classify(rec):
    title_l = (rec.get("title") or "").lower()
    blob = title_l + " " + (rec.get("desc") or "").lower()
    source = rec.get("source", "")
    proj = [w for w in PROJECT_WORDS if w in blob]
    if PROJECT_REGEX.search(blob):
        proj.append("x6/g6/antv/mcp")
    lab = [w for w in LABS if w in blob]
    rel_title = [w for w in RELEASE_WORDS if w in title_l]
    mod = [w for w in MODEL_WORDS if w in blob]
    worth = [w for w in WORTH_WORDS if w in blob]

    if source == "版本发布":
        return "必须看", True, ["跟踪仓库新版本"]
    if proj and rel_title:
        return "必须看", True, ["项目相关+更新:" + ",".join(proj[:2] + rel_title[:2])]
    if proj:
        return "必须看", False, ["项目相关:" + ",".join(proj[:3])]
    if lab and rel_title and mod:
        return "必须看", False, ["发布信号:" + ",".join(lab[:2] + rel_title[:1] + mod[:1])]
    if worth or source in WORTH_SOURCES or source.startswith("arXiv "):
        return "值得看", False, (["命中:" + ",".join(worth[:3])] if worth else ["论文/工具类"])
    return "仅存档", False, []


# ---------------------------------------------------------------- 输出

def render_md(p):
    c = p["counts"]
    lines = ["# Day-Info 收集池 · %s" % p["date"], "",
             "> 共 %s 条：**必须看 %s** · 值得看 %s · 仅存档 %s；critical %s"
             % (c["total"], c["must"], c["worth"], c["archive"], c["critical"]), ""]

    def sec(name, items, detail=True):
        rows = ["## %s（%s）" % (name, len(items)), ""]
        for it in items:
            line = "- %s[%s](%s)" % ("⚡ " if it.get("critical") else "", it["title"], it["url"])
            if it.get("published"):
                line += " · %s" % it["published"]
            line += " · <sub>%s</sub>" % it["source"]
            rows.append(line)
            if detail and it.get("summary"):
                rows.append("  - %s" % it["summary"])
        rows.append("")
        return rows

    must = [i for i in p["items"] if i["tier"] == "必须看"]
    worth = [i for i in p["items"] if i["tier"] == "值得看"]
    arch = [i for i in p["items"] if i["tier"] == "仅存档"]
    lines += sec("⚡ 必须看", must, True)
    lines += sec("值得看", worth, True)
    lines += sec("仅存档", arch, False)
    if p.get("errors"):
        lines += ["## 源告警", ""] + ["- %s" % e for e in p["errors"]]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", default=str(Path(__file__).resolve().parents[2]))
    args = ap.parse_args()
    root = Path(args.repo_dir).resolve()
    daydir = root / "day-info"
    pooldir = daydir / "pool"
    pooldir.mkdir(parents=True, exist_ok=True)
    today = dt.date.today()

    state_path = daydir / "state.json"
    state_raw = ""
    state = {}
    if state_path.exists():
        try:
            state_raw = state_path.read_text(encoding="utf-8")
            state = json.loads(state_raw)
        except Exception:
            state = {}
    seen = state.setdefault("seen", {})

    errors = []
    raw = []
    raw += src_arxiv(errors)
    raw += src_hf(errors)
    raw += src_gh_new(errors, today)
    raw += src_gh_trending(errors, today)
    raw += src_releases(errors, state, today)
    raw += src_hn(errors)
    raw += src_blogs(errors, today)
    raw += src_labs(errors)
    raw += src_ithome(errors)

    raw_counts = {}
    for rec in raw:
        s = rec.get("source", "")
        raw_counts[s] = raw_counts.get(s, 0) + 1

    # 同日重跑：以当天已有池为底，合并新条目（幂等、不丢内容）
    pool_json = pooldir / ("%s.json" % today)
    pool_md = pooldir / ("%s.md" % today)
    base_items = []
    if pool_json.exists():
        try:
            base_items = json.loads(pool_json.read_text(encoding="utf-8")).get("items", [])
        except Exception:
            base_items = []
    base_keys = {url_key(i.get("url", "")) for i in base_items}

    items = []
    used_urls = set(base_keys)
    used_titles = {(i.get("title") or "").lower()[:80] for i in base_items}
    for rec in raw:
        url = (rec.get("link") or "").strip()
        title = (rec.get("title") or "").strip()
        if not url or not title:
            continue
        key = url_key(url)
        tkey = title.lower()[:80]
        if key in used_urls or tkey in used_titles:
            continue
        if key in seen and key not in base_keys:
            try:
                if (today - dt.date.fromisoformat(seen[key])).days < SEEN_DAYS:
                    continue
            except Exception:
                pass
        used_urls.add(key)
        used_titles.add(tkey)
        seen[key] = today.isoformat()
        tier, critical, reasons = classify(rec)
        items.append({
            "url": url, "title": title[:180], "source": rec.get("source", ""),
            "published": rec.get("published", ""),
            "summary": re.sub(r"\s+", " ", rec.get("desc") or "").strip()[:220],
            "tier": tier, "critical": bool(critical), "reasons": reasons,
        })

    merged = list(base_items)
    existing = set(base_keys)
    for it in items:
        k = url_key(it["url"])
        if k in existing:
            continue
        existing.add(k)
        merged.append(it)
    order = {"必须看": 0, "值得看": 1, "仅存档": 2}
    merged.sort(key=lambda x: (order.get(x["tier"], 9), x.get("source", ""), x.get("title", "")))
    counts = {
        "total": len(merged),
        "must": sum(1 for i in merged if i["tier"] == "必须看"),
        "worth": sum(1 for i in merged if i["tier"] == "值得看"),
        "archive": sum(1 for i in merged if i["tier"] == "仅存档"),
        "critical": sum(1 for i in merged if i.get("critical")),
    }

    # 清理 seen（保留 SEEN_KEEP 天，总量封顶）
    cutoff = today - dt.timedelta(days=SEEN_KEEP)
    for k in list(seen):
        try:
            if dt.date.fromisoformat(seen[k]) < cutoff:
                del seen[k]
        except Exception:
            del seen[k]
    if len(seen) > 20000:
        for k in list(seen)[: len(seen) - 15000]:
            del seen[k]

    stable = False
    if pool_json.exists():
        try:
            old = json.loads(pool_json.read_text(encoding="utf-8"))
            if old.get("items") == merged and old.get("counts") == counts and old.get("errors") == errors:
                stable = True
        except Exception:
            stable = False
    if not stable:
        payload = {"date": today.isoformat(),
                   "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                   "counts": counts, "errors": errors, "items": merged}
        pool_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        pool_md.write_text(render_md(payload), encoding="utf-8")

    state["updated"] = today.isoformat()
    new_state_text = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    if new_state_text != state_raw:
        state_path.write_text(new_state_text, encoding="utf-8")

    if raw_counts:
        print("抓取原始：" + "；".join("%s %s" % (k, v) for k, v in sorted(raw_counts.items())))
    if items:
        print("本次新增 %s 条：%s" % (len(items), "；".join(
            "%s %s" % (k, v) for k, v in sorted({it["source"]: sum(1 for x in items if x["source"] == it["source"]) for it in items}.items()))))
    else:
        print("本次未发现新增条目")
    print("池内累计 %s 条（必须看 %s / 值得看 %s / 仅存档 %s；critical %s）"
          % (counts["total"], counts["must"], counts["worth"], counts["archive"], counts["critical"]))
    for it in merged:
        if it.get("critical"):
            print("CRITICAL: %s → %s" % (it["title"], it["url"]))
    print("池文件：%s%s" % (pool_json, "（无变化）" if stable else ""))
    if errors:
        print("源告警（%s）：" % len(errors))
        for e in errors[:12]:
            print("  ! %s" % e)


if __name__ == "__main__":
    main()
