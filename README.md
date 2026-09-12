# Knowrary

**Knowrary = know + library**，我的个人知识库：学习笔记、认知图谱，以及后续的 agent 能力与分享输出。这个仓库同时是一个 Obsidian vault：用 Obsidian 直接打开仓库根目录。

## ⚠️ 先配 LLM（每个人自己的模型和密钥，不在仓库里）

调用大模型的功能（`knowrary article`、后续的审核 / 分组 / 去重）读的是 **`.knowrary/llm.local.json`**。这个文件被 `.gitignore` 忽略（规则 `*.local.json`），仓库里只有模板：

```bash
cp .knowrary/llm.example.json .knowrary/llm.local.json   # 然后编辑：填模型名、密钥或 env:变量名
python3 tools/knowrary/knowrary.py llm list --vault .      # 看当前配置
python3 tools/knowrary/knowrary.py llm test --vault .      # 连通性测试（每个角色用到的 provider 各问一句）
```

- **provider 三种类型**：`claude-cli`（复用本机 Claude Code 登录，零配置）、`anthropic`（官方 API）、`openai`（OpenAI 兼容协议：OpenAI / DeepSeek / 通义 / Ollama / vLLM 都是它）。
- **两个角色**：`learn`（文章拆节点、关系抽取）和 `review`（校验、分组判断、去重）。可以指向不同模型，用第二个模型审第一个的产出，减少单一模型的偏差。
- 不建配置文件也能用：默认全部走 `claude -p`。
- `knowrary check` 会在任何 `*.local.json` 被 git 跟踪时报错，防止密钥被提交。
- 前端设置页（页面上配置多个 LLM、指派角色）在计划中，见 `doc/设计文档/第二版设计文档.md` 3.11。

## 目录

| 目录 | 内容 |
| --- | --- |
| `nodes/` | 认知图谱的知识节点，一个知识点一个 md，按领域分子目录（`01-理论基础` … `AI-Agent`，`_stubs` 是待补的空壳） |
| `fields/` | 领域总览（每个顶层领域一个文件） |
| `assets/` | 节点引用的图片 |
| `.knowrary/` | 图谱的机器数据：`llm.example.json`（LLM 配置模板，本地副本 `llm.local.json` 不入库）、`index.json`（解析索引，`knowrary index` 生成，不入库）、`layout.json`（结构视图的位置 / 分组 / 折叠状态）、`review-log.json`（复习记录，待建）、`imports/`（每次导入的方案）、`MIGRATION-REPORT.md` |
| `relation-types.json` | 关系类型表：5 个族，具体类型可增长 |
| `tools/knowrary/` | CLI 与核心库（解析、索引、布局生成），见其 README |
| `server/` | 本地服务（FastAPI）：只读 index、读写 layout、托管前端产物，见其 README |
| `web/` | 结构视图前端（Vue 3 + Vite + X6）；`web/dist/` 是入库的构建产物，运行期零 Node |
| `.claude/skills/knowrary-import/` | Claude Code skill：把文章拆成节点存进 Knowrary |
| `doc/` | 规范文档、设计文档、开发实施计划 |
| `harness/`、`llm/` | 学习笔记原文（不是图谱节点，导入图谱靠 knowrary-import） |

## 节点约定（摘要，全文见 `doc/规范文档/Markdown文档规范.md`）

- frontmatter 必填 `name`、`field`、`desc`；`year` 可选，只有填了才进入历史视图。
- 关系写在 `## 关系` 段：`- 类型:: [[目标]] (年份)? — 说明?`，方向从本节点指向目标，反链由解析器推导。
- 坐标、分组、折叠状态不进 md，统一在 `.knowrary/layout.json`；复习记录不进 md，在 `.knowrary/review-log.json`（`learned` 只记首次入库）。

## 常用命令

```bash
./server/dev.sh                                                # 启动本地服务，打开 http://127.0.0.1:8765/ 看结构视图
#   画布操作：拖空白平移 / 滚轮缩放 / shift+拖空白框选 / 拖节点进别的分组框即改归属（自动保存）
#   连线：结构族默认不画（嵌套已表达，工具条可勾开）；跨分组边聚合成「分组→分组 (n)」一束，点开看明细；悬停节点高亮它的边
#   缩小自动折叠成簇卡片（点卡片放大进该域，Esc 回全景）· 搜索框定位 · ＋便签 · 详情面板「放引用卡」
#   改关系/改摘要 → 先预览 diff → 确认才写回 md（自动备份到 .knowrary/backup/）
#   视图切换下拉里有「3D 总览」，或直接开 http://127.0.0.1:8765/3d/
python3 tools/knowrary/knowrary.py index --vault .             # 重建 .knowrary/index.json（结构视图/服务的数据源）
python3 tools/knowrary/knowrary.py layout check --vault .      # 布局引用校验：孤立记录 / Inbox 统计
python3 tools/knowrary/knowrary.py check .                     # 按规范校验全部节点（含密钥泄露检查）
python3 tools/knowrary/tests/run.py                            # core 自测（零依赖，25 个用例）
.venv/bin/python server/tests/run.py                           # 服务层自测（16 个用例）
.venv/bin/python web/tests/e2e_canvas.py                       # 画布端到端自测（真无头 Chrome 拖拽 → 落盘，临时 vault，不碰你的布局）
cd web && npm run dev                                          # 改前端（5173，/api 代理到 8765）；改完 npm run build 提交 dist
python3 tools/knowrary/knowrary.py article <文章.md> --vault . --field <领域> [--dry-run] [--llm <provider>]   # 无人值守：文章 → 节点
# 在 Claude Code 里：/knowrary-import <文章路径>  或  "把这篇文章融入我的图谱"
```
