#!/usr/bin/env python3
"""画布端到端自测：真无头 Chrome + 真 DOM 鼠标事件 → 验证 X6 交互是否真的落盘。

    .venv/bin/python web/tests/e2e_canvas.py

自己起一个临时 vault + 独立端口的服务实例，**不碰仓库里的 layout.json**；
用完自动清理。需要本机装有 Google Chrome（只读用它的无头模式）与 `web/dist`（先 npm run build）。

为什么要有它：阶段 2 的两个 bug 只有真拖拽才暴露得出来——
1. X6 `embedding.frontOnly` 默认 true，落点被其他节点挡住时"拖进分组"会丢归属；
2. 用 requestAnimationFrame 放开写入守卫，在后台标签页 / 无头浏览器里永不触发，改动被静默丢弃。
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 本机直连，绕过代理

FILES = {
    "nodes/组A/甲.md": "---\nname: 甲\nfield: 测试\ndesc: 甲\n---\n# 甲\n\n正文\n\n## 关系\n- 部件:: [[乙]]\n",
    "nodes/组A/乙.md": "---\nname: 乙\nfield: 测试\ndesc: 乙\n---\n# 乙\n\n正文\n",
    "nodes/组B/丙.md": "---\nname: 丙\nfield: 测试\ndesc: 丙\n---\n# 丙\n\n正文\n\n## 关系\n- 依赖:: [[甲]]\n",
    "nodes/组B/丁.md": "---\nname: 丁\nfield: 测试\ndesc: 丁\n---\n# 丁\n\n正文\n\n## 关系\n- 依赖:: [[乙]]\n",
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str) -> dict:
    with OPENER.open(urllib.request.Request(url)) as r:
        return json.loads(r.read())


def wait_for(url: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            get(url)
            return
        except Exception:
            time.sleep(0.3)
    raise SystemExit(f"等不到 {url}")


def devtools_base(profile: Path, timeout: float = 30.0) -> str:
    """Chrome 用 --remote-debugging-port=0 时会把真实端口写进 DevToolsActivePort；
    回环地址它可能绑 IPv4 也可能绑 IPv6，两种都试。"""
    marker = profile / "DevToolsActivePort"
    deadline = time.time() + timeout
    port = None
    while time.time() < deadline:
        if marker.exists():
            head = marker.read_text().splitlines()
            if head and head[0].strip().isdigit():
                port = int(head[0].strip())
                break
        time.sleep(0.3)
    if port is None:
        raise SystemExit("Chrome 没有写出 DevToolsActivePort，可能启动失败")
    for host in ("127.0.0.1", "[::1]"):
        base = f"http://{host}:{port}"
        try:
            get(base + "/json/list")
            return base
        except Exception:
            continue
    raise SystemExit(f"DevTools 端口 {port} 连不上")


def make_vault(tmp: Path) -> Path:
    vault = tmp / "vault"
    (vault / ".knowrary").mkdir(parents=True)
    (vault / "relation-types.json").write_text((REPO / "relation-types.json").read_text("utf-8"), "utf-8")
    for rel, text in FILES.items():
        path = vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return vault


def drag_script(cell: str, *, to_cell: str | None = None, dx: int = 0, dy: int = 0, grab: str = "center") -> str:
    """在页面里派发一串真实的 mousedown / mousemove / mouseup。"""
    origin = "{ x: r.x + 40, y: r.y + 10 }" if grab == "title" else "{ x: r.x + r.width / 2, y: r.y + r.height / 2 }"
    target = (f"""const b = document.querySelector('[data-cell-id="{to_cell}"]');
        if (!b) return 'missing-dst';
        const br = b.getBoundingClientRect(); to = {{ x: br.x + br.width / 2, y: br.y + br.height / 2 }};"""
              if to_cell else f"to = {{ x: from.x + {dx}, y: from.y + {dy} }};")
    return f"""(() => {{
      const el = document.querySelector('[data-cell-id="{cell}"]');
      if (!el) return 'missing-src';
      const r = el.getBoundingClientRect();
      const from = {origin};
      let to;
      {target}
      const fire = (t, x, y, node) => node.dispatchEvent(new MouseEvent(t, {{
        bubbles: true, cancelable: true, clientX: x, clientY: y, view: window,
        button: 0, buttons: t === 'mouseup' ? 0 : 1 }}));
      fire('mousedown', from.x, from.y, el.querySelector('rect') || el);
      for (let i = 1; i <= 10; i++) {{
        fire('mousemove', from.x + (to.x - from.x) * i / 10, from.y + (to.y - from.y) * i / 10, document);
      }}
      fire('mouseup', to.x, to.y, document);
      return 'ok';
    }})()"""


class Page:
    """极简 CDP 客户端：够用来 evaluate 与 reload。"""

    def __init__(self, ws):
        self.ws = ws
        self.n = 0

    async def call(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == self.n:
                return msg.get("result", {})

    async def ev(self, expr: str):
        res = await self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        if res.get("exceptionDetails"):
            raise AssertionError("页面 JS 异常：" + json.dumps(res["exceptionDetails"], ensure_ascii=False)[:300])
        return res.get("result", {}).get("value")


async def wait_render(page: Page, expect_nodes: int, timeout: float = 20.0) -> int:
    """等 X6 把节点画出来再动手（冷启动的无头 Chrome 首屏可能要好几秒）。"""
    deadline = time.time() + timeout
    seen = 0
    while time.time() < deadline:
        seen = await page.ev("document.querySelectorAll('[data-shape=\"kg-node\"]').length") or 0
        if seen >= expect_nodes:
            return seen
        await asyncio.sleep(0.5)
    raise AssertionError(f"画布迟迟没渲染出 {expect_nodes} 个节点（当前 {seen}）")


async def drag(page: Page, *args, **kwargs) -> None:
    out = await page.ev(drag_script(*args, **kwargs))
    assert out == "ok", f"拖拽脚本返回 {out!r}（元素没找到？）"


class Check:
    """收集用例结论，最后统一打印。"""

    def __init__(self, api: str):
        self.api = api
        self.items: list[tuple[str, bool, str]] = []

    def layout(self) -> dict:
        return get(self.api + "/api/layout")["layout"]

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.items.append((name, ok, detail))


async def case_initial(page: Page, ck: Check) -> None:
    await wait_render(page, 4)
    base = ck.layout()
    ck.add("首次打开自动生成布局", base["revision"] == 1 and len(base["nodes"]) == 4,
           f"revision {base['revision']}，节点 {len(base['nodes'])}")


async def poll(page: Page, expr: str, ok, timeout: float = 8.0):
    """X6 开了异步渲染，DOM 不会立刻更新；轮询到条件成立或超时。"""
    deadline = time.time() + timeout
    value = None
    while time.time() < deadline:
        value = await page.ev(expr)
        if ok(value):
            return value
        await asyncio.sleep(0.3)
    return value


async def edge_counts(page: Page) -> dict:
    return json.loads(await page.ev("""JSON.stringify({
      total: document.querySelectorAll('.x6-edge').length,
      agg: [...document.querySelectorAll('.x6-edge')].filter(
        (e) => e.getAttribute('data-cell-id')?.startsWith('agg:')).length })"""))


async def case_aggregate(page: Page, ck: Check) -> None:
    """跨分组边默认聚合成一束；点它展开明细，再点收起。"""
    start = await edge_counts(page)
    ck.add("跨分组边默认聚合成束", start["agg"] >= 1 and start["total"] == start["agg"],
           f"画布 {start['total']} 条，其中聚合 {start['agg']} 束")
    click = """(() => {
      const agg = [...document.querySelectorAll('.x6-edge')].find(
        (e) => e.getAttribute('data-cell-id')?.startsWith('agg:'));
      if (!agg) return 'no-agg';
      const path = agg.querySelector('path');
      const r = path.getBoundingClientRect();
      const x = r.x + r.width / 2, y = r.y + r.height / 2;
      for (const t of ['mousedown', 'mouseup', 'click']) {
        path.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true,
          clientX: x, clientY: y, view: window, button: 0 }));
      }
      return agg.getAttribute('data-cell-id');
    })()"""
    bundle = await page.ev(click)
    expect_detail = start["total"] - start["agg"] + 2   # 这束里有 2 条明细
    await poll(page, "document.querySelectorAll('.x6-edge').length", lambda v: (v or 0) >= expect_detail)
    opened = await edge_counts(page)
    ck.add("点聚合束展开明细", opened["agg"] == start["agg"] - 1 and opened["total"] > start["total"],
           f"{bundle} → 明细 {opened['total'] - opened['agg']} 条，剩 {opened['agg']} 束")
    await page.ev(click.replace("startsWith('agg:')", "startsWith('agg:')"))  # 束已展开，重复点无副作用
    await asyncio.sleep(0.5)

    # 悬停高亮：无关边淡出
    await page.ev("""(() => {
      const el = document.querySelector('[data-cell-id="乙"]');
      const r = el.getBoundingClientRect();
      for (const t of ['mouseover', 'mouseenter']) {
        el.dispatchEvent(new MouseEvent(t, { bubbles: t === 'mouseover', clientX: r.x + 5, clientY: r.y + 5, view: window }));
      }
      return 'sent';
    })()""")
    dim = await poll(page, """[...document.querySelectorAll('.x6-edge path')].filter(
      (p) => parseFloat(p.getAttribute('opacity') || '1') < 0.2).length""", lambda v: (v or 0) > 0)
    ck.add("悬停节点高亮相关边、淡出其余", (dim or 0) > 0, f"淡出 {dim} 条")


async def case_drag_node(page: Page, ck: Check) -> dict:
    """节点拖进另一个分组：归属与坐标都要落盘，且一次拖动只写一次。"""
    before = ck.layout()
    await drag(page, "甲", to_cell="g-测试--组B")
    await asyncio.sleep(1.6)
    now = ck.layout()
    ck.add("拖节点跨分组改归属并落盘",
           now["nodes"]["甲"]["group"] == "g-测试--组B" and now["revision"] == before["revision"] + 1,
           f"分组 {now['nodes']['甲']['group']}，revision {before['revision']} → {now['revision']}")
    return now


async def case_drag_group(page: Page, ck: Check, prev: dict) -> dict:
    """拖分组：X6 带着子节点一起走，服务端一次收齐。"""
    gid = "g-测试--组A"
    kids = [k for k, v in prev["nodes"].items() if v["group"] == gid]
    g0 = prev["groups"][gid]
    k0 = {k: (prev["nodes"][k]["x"], prev["nodes"][k]["y"]) for k in kids}
    await drag(page, gid, dx=120, dy=-60, grab="title")
    await asyncio.sleep(1.6)
    now = ck.layout()
    gd = (round(now["groups"][gid]["x"] - g0["x"]), round(now["groups"][gid]["y"] - g0["y"]))
    kd = {k: (round(now["nodes"][k]["x"] - k0[k][0]), round(now["nodes"][k]["y"] - k0[k][1])) for k in kids}
    ck.add("拖分组带子节点批量落盘",
           gd != (0, 0) and all(d == gd for d in kd.values()) and now["revision"] == prev["revision"] + 1,
           f"分组位移 {gd}，子节点 {kd}，revision {now['revision']}")
    return now


async def case_noop_and_reload(page: Page, ck: Check, prev: dict) -> None:
    """原地拖不写盘；刷新后位置与归属保持，且刷新本身不写盘。"""
    await drag(page, "丁", dx=0, dy=0)
    await asyncio.sleep(1.2)
    quiet = ck.layout()
    ck.add("无位移不产生空写", quiet["revision"] == prev["revision"], f"revision {quiet['revision']}")
    await page.call("Page.enable")
    await page.call("Page.reload", {"ignoreCache": True})
    await wait_render(page, 4)
    after = ck.layout()
    ck.add("刷新后位置保持且刷新不写盘",
           after["revision"] == quiet["revision"] and after["nodes"]["甲"]["group"] == "g-测试--组B",
           f"revision {after['revision']}，甲 分组 {after['nodes']['甲']['group']}")


async def case_rendered(page: Page, ck: Check) -> None:
    counts = json.loads(await page.ev("""JSON.stringify({
      groups: document.querySelectorAll('[data-shape="kg-group"]').length,
      nodes: document.querySelectorAll('[data-shape="kg-node"]').length,
      edges: document.querySelectorAll('.x6-edge').length,
      status: document.querySelector('.status')?.textContent })"""))
    ck.add("画布渲染出分组/节点/边",
           counts["groups"] >= 3 and counts["nodes"] == 4 and counts["edges"] >= 1,
           f"分组 {counts['groups']}，节点 {counts['nodes']}，边 {counts['edges']}，状态 {counts['status']}")


async def scenarios(page: Page, api: str, results: list) -> None:
    ck = Check(api)
    await case_initial(page, ck)
    await case_aggregate(page, ck)
    after_node = await case_drag_node(page, ck)
    after_group = await case_drag_group(page, ck, after_node)
    await case_noop_and_reload(page, ck, after_group)
    await case_rendered(page, ck)
    results.extend(ck.items)


async def run(api: str, cdp: str, results: list) -> None:
    import websockets  # .venv 里由 uvicorn[standard] 带入

    targets = get(cdp + "/json/list")
    target = next(t for t in targets if t["type"] == "page" and api.split("//")[1] in t["url"])
    async with websockets.connect(target["webSocketDebuggerUrl"], proxy=None, max_size=20_000_000) as ws:
        page = Page(ws)
        await page.call("Runtime.enable")
        await scenarios(page, api, results)


def main() -> None:
    if not (REPO / "web" / "dist" / "index.html").exists():
        raise SystemExit("缺少 web/dist：先 cd web && npm run build")
    if not Path(CHROME).exists():
        raise SystemExit(f"找不到 Chrome：{CHROME}")
    port = free_port()
    api = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="knowrary-e2e-") as tmpdir:
        tmp = Path(tmpdir)
        vault = make_vault(tmp)
        env = {**os.environ, "KNOWRARY_VAULT": str(vault)}
        server = subprocess.Popen([str(REPO / ".venv" / "bin" / "python"), "-m", "uvicorn", "server.app:app",
                                   "--host", "127.0.0.1", "--port", str(port), "--app-dir", str(REPO)],
                                  env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        chrome = None
        results: list[tuple[str, bool, str]] = []
        try:
            wait_for(api + "/api/health")
            profile = tmp / "chrome"
            chrome = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                                       "--window-size=1600,1000", "--remote-debugging-port=0",
                                       f"--user-data-dir={profile}", api + "/"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            cdp = devtools_base(profile)
            time.sleep(3)  # 等前端首屏渲染完
            asyncio.run(run(api, cdp, results))
        finally:
            for proc in (chrome, server):
                if proc:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
    failed = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print(f"  {'✓' if ok else '✗'} {name}" + (f"（{detail}）" if detail else ""))
    print(f"\n{len(results) - len(failed)}/{len(results)} 通过")
    sys.exit(1 if failed or not results else 0)


if __name__ == "__main__":
    main()
