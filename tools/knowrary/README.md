# knowrary.py —— Knowrary 迁移 / 导入 / 校验工具

vault = 本仓库根目录；解析器只扫 `nodes/` 和 `fields/`。

零第三方依赖（Python ≥ 3.10）。规范见 `doc/规范文档/Markdown文档规范.md`。

```bash
KG=/Users/moka/IdeaProjects/Knowrary/tools/knowrary/knowrary.py

# 1. 旧 vault（- 类型 → [[目标]]）→ 第二版结构
python3 $KG vault /Users/moka/IdeaProjects/knowage <新目录> --field 计算机体系结构   # 已于 2026-09-10 执行，结果即本仓库 nodes/ fields/
#    报告：<dst>/.knowrary/MIGRATION-REPORT.md（未映射类型 / 翻转 / 去重 / stub）
#    旧类型映射表：legacy-types.json（改完重跑，加 --force 覆盖）

# 2. 索引（阶段 1）：全量重建 <vault>/.knowrary/index.json
python3 $KG index --vault /Users/moka/IdeaProjects/Knowrary
#    内容不变则不落盘、不动 revision（幂等）；--stdout 只打印不写盘，--force 强制重写，
#    --strict 有 error 时退出码 1，--out 换输出路径，--max-warn 控制警告条数
#    契约：schema_version / revision / generated_at / content_hash / nodes / edges / families / stubs / stats / errors / warnings
#    边只存归一化正向边（互逆归 canonical、对称按 id 定向），反链在节点的 in / out 邻接表里

# 2a. 布局（阶段 2）：初始布局生成 / 引用校验（零依赖，不需要 .venv）
python3 $KG layout init  --vault /Users/moka/IdeaProjects/Knowrary [--force]   # 按 field / nodes 子目录两级分组 + 组内网格
python3 $KG layout check --vault /Users/moka/IdeaProjects/Knowrary            # 孤立记录、Inbox 统计
#    服务启动时若无 layout.json 会自动生成同样的初始布局

# 2b. 校验（错误退出码 1）——与 index 共用同一套解析和诊断，额外查密钥泄露与索引契约
python3 $KG check /Users/moka/IdeaProjects/Knowrary

# 2c. 自测（零依赖，覆盖幂等、诊断、归一、契约）
python3 /Users/moka/IdeaProjects/Knowrary/tools/knowrary/tests/run.py [关键字]

# 3. 文章 → 节点
#    3a. 在 Claude Code 里用 skill（推荐）：/knowrary-import <文章路径>，或直接说"把这篇文章融入我的图谱"
#        skill 内部调用：
python3 $KG context --vault <vault> --article <文章>          # 类型表 + 全部 id + 相关节点
python3 $KG apply plan.json --vault <vault> --field <领域> --source <文章名> [--dry-run]
#    3b. 无人值守（cron / 脚本）：脚本自己调 LLM，用配置里的 learn 角色
python3 $KG article <文章> --vault <vault> --field <领域> [--dry-run] [--llm <provider>] [--model ...]
#        提示词：prompts/article.md

# 4. LLM 配置：<vault>/.knowrary/llm.local.json（gitignore 忽略 *.local.json），模板 <vault>/.knowrary/llm.example.json
python3 $KG llm list --vault <vault>            # 看 provider / 角色
python3 $KG llm test --vault <vault> [--llm x]  # 连通性测试；退出码非 0 表示有 provider 不通
#    provider 类型：claude-cli（复用 Claude Code 登录）/ anthropic / openai（OpenAI 兼容：DeepSeek、通义、Ollama…）
#    角色：learn（拆节点）/ review（审核）；api_key 可写 env:VAR 引用环境变量；环境变量 KNOWRARY_LLM_CONFIG 可改配置路径
#    没有配置文件时默认全部走 claude -p
```

文件：

| 文件 | 作用 |
| --- | --- |
| `knowrary.py` | 全部命令（CLI 薄壳，解析与校验都调 `core/`） |
| `core/` | 核心库：`mdio.py`（IO / frontmatter / 目录扫描）、`relations.py`（类型表、关系解析、方向归一）、`parser.py`（节点与 frontmatter 校验）、`index.py`（index.json 生成、内容哈希与 revision）、`layout.py`（初始布局生成、孤立引用判定）、`schema.py`（index 契约校验）、`diagnostics.py`（结构化诊断）。`server/` 直接 import，避免两套实现漂移 |
| `tests/run.py` | 零依赖自测（24 个用例）|
| `llm_backend.py` | LLM 后端：读配置、按角色选 provider、claude-cli / anthropic / openai 三种调用（零依赖，urllib） |
| `relation-types.v2.json` | 第二版类型表（5 族），迁移时复制到 `<vault>/relation-types.json` |
| `legacy-types.json` | 旧类型 → 新类型映射（`flip` 表示方向反转） |
| `prompts/article.md` | 文章拆节点的提示词模板，与 skill `.claude/skills/knowrary-import/SKILL.md` 保持一致 |
