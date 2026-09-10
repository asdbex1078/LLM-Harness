# server —— Knowrary 本地服务（FastAPI）

只做三件事：**只读** index、**读写** layout、静态托管前端产物。
**这一层永远不改 Markdown**——改 md 只能走阶段 3 的 ChangeSet（`POST /api/changes`，待建）。

## 启动

```bash
python3 -m venv .venv                                  # 只需一次
.venv/bin/pip install -r server/requirements-dev.txt   # 运行期依赖 + 自测依赖
./server/dev.sh            # 默认 127.0.0.1:8765，vault = 仓库根目录
KNOWRARY_VAULT=/别的/vault ./server/dev.sh 9000
```

浏览器打开 <http://127.0.0.1:8765/>（托管 `web/dist`）。改前端时另开一个终端：
`cd web && npm run dev`（5173，`/api` 代理到 8765）。

## 接口（阶段 2 已实现）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | vault 路径、index / layout revision、节点边统计 |
| GET | `/api/index` | 派生索引全量（阶段 1 的 core 生成，md 变化时自动重建并落盘） |
| GET | `/api/layout` | `{layout, orphans, index_revision, generated}`；没有 layout.json 时按 field / 目录自动生成 |
| PATCH | `/api/layout` | 部分文档合并写入，带 `base_revision` 乐观并发 |

`PATCH` 语义（JSON Merge Patch 风格）：

```jsonc
{
  "base_revision": 7,
  "nodes":  { "cpu": { "x": 120, "y": 40 },     // 字段级合并，其余字段保留
              "旧节点": null },                  // 条目置 null = 删除该条目
  "groups": { "g-JVM": { "collapsed": true } },
  "edges":  { "cpu->寄存器#部件": { "vertices": [{ "x": 1, "y": 2 }] } },
  "refs": [], "notes": [], "images": [],        // 带 id 的小集合：给出即整体替换
  "viewport": { "zoom": 0.6, "cx": 1200, "cy": 800 }
}
```

- `base_revision` 与服务端不一致 → **409**，响应带 `current_revision`，客户端重新 GET 后重放。
- 新增条目字段不全、引用不存在的分组、未知字段 → **422**，不写盘。
- 写盘走临时文件 + rename（原子），崩溃不会留半个 JSON。
- 引用不到的节点 / 分组 / 图片 / 边只进 `orphans` 报告，**绝不自动删除**用户数据。

## 文件

| 文件 | 作用 |
| --- | --- |
| `paths.py` | vault 解析（`KNOWRARY_VAULT`）与 `tools/knowrary/core` 注入 |
| `contracts.py` | 三份契约的 pydantic v2 模型：index（只读）、layout + LayoutPatch、ChangeSet（阶段 3） |
| `index_service.py` | 按 md 文件指纹缓存索引，变化即重建并写 `.knowrary/index.json` |
| `layout_store.py` | layout 读写：初始生成、部分合并、revision 校验、原子写、孤立引用 |
| `app.py` | FastAPI 路由与静态托管 |
| `tests/run.py` | 服务层自测（TestClient + 临时 vault，16 个用例） |

初始布局生成与孤立引用判定住在 `tools/knowrary/core/layout.py`（零第三方依赖），
所以 `python3 tools/knowrary/knowrary.py layout init/check` 不需要 .venv 也能用。

## 自测

```bash
.venv/bin/python server/tests/run.py          # 16 个用例
.venv/bin/python server/tests/run.py revision # 只跑名字含 revision 的
```
