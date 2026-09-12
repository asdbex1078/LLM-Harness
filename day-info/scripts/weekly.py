#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Day-Info 周材料合并：把最近 N 天收集池中「必须看 + 值得看」的条目合并成一份原始材料。

输出：
- day-info/digests/raw/YYYY-Www.json
- day-info/digests/raw/YYYY-Www.md

周报的最终成稿（精炼、分类、学习雷达、入库草稿）由每周末的自动化任务在此材料基础上撰写。
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path


def norm_url(u):
    u = (u or "").strip().split("#", 1)[0]
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    root = Path(args.repo_dir).resolve()
    pooldir = root / "day-info" / "pool"
    outdir = root / "day-info" / "digests" / "raw"
    outdir.mkdir(parents=True, exist_ok=True)
    today = dt.date.today()
    days = [today - dt.timedelta(days=i) for i in range(args.days)]

    merged, seen_keys, sources, skipped, covered = [], set(), {}, 0, 0
    for d in days:
        p = pooldir / ("%s.json" % d)
        if not p.exists():
            continue
        covered += 1
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for it in data.get("items", []):
            if it.get("tier") == "仅存档":
                skipped += 1
                continue
            k = hashlib.sha1(norm_url(it.get("url", "")).encode("utf-8")).hexdigest()[:16]
            if k in seen_keys:
                continue
            seen_keys.add(k)
            it = dict(it)
            it["pool_date"] = d.isoformat()
            merged.append(it)
            sources[it.get("source", "")] = sources.get(it.get("source", ""), 0) + 1

    order = {"必须看": 0, "值得看": 1}
    merged.sort(key=lambda x: (order.get(x.get("tier"), 9), x.get("source", ""), x.get("title", "")))
    week = today.isocalendar()
    week_label = "%s-W%02d" % (week.year, week.week)
    counts = {"total": len(merged),
              "must": sum(1 for i in merged if i["tier"] == "必须看"),
              "worth": sum(1 for i in merged if i["tier"] == "值得看"),
              "archived_skipped": skipped,
              "days_covered": covered}

    payload = {"week": week_label, "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
               "range": [days[-1].isoformat(), days[0].isoformat()],
               "counts": counts, "sources": sources, "items": merged}
    json_path = outdir / ("%s.json" % week_label)
    md_path = outdir / ("%s.md" % week_label)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = ["# Day-Info 周材料 · %s（%s ~ %s）" % (week_label, days[-1], days[0]), "",
             "> 「必须看」%s 条 · 「值得看」%s 条（已合并去重；仅存档 %s 条未纳入）"
             % (counts["must"], counts["worth"], skipped), ""]
    for tier in ("必须看", "值得看"):
        group = [i for i in merged if i["tier"] == tier]
        lines += ["## %s（%s）" % (tier, len(group)), ""]
        for it in group:
            line = "- [%s](%s) · %s · %s" % (
                it["title"], it["url"], it.get("source", ""), it.get("published") or it.get("pool_date", ""))
            lines.append(line)
            if it.get("summary"):
                lines.append("  - %s" % it["summary"][:200])
        lines.append("")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("周材料已生成：%s" % json_path)
    print("统计：必须看 %s · 值得看 %s（覆盖 %s 天池数据）" % (counts["must"], counts["worth"], counts["days_covered"]))


if __name__ == "__main__":
    main()
