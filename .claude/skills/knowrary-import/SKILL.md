---
name: knowrary-import
description: 把一篇文章 / 一段笔记 / 一次学习心得拆成知识节点，存进 Knowrary 个人知识库 vault（第二版 Markdown 规范：一节点一 md、`- 类型:: [[目标]]` 带类型边、5 个关系族）。触发：用户说"导入到知识图谱"、"融入我的体系"、"把这篇文章拆成节点"、"knowrary import"、"存进 Knowrary"、"学到了 X，记进图谱"。
---

# knowrary-import：文章 → Knowrary 知识节点

## 固定路径

- 迁移/校验脚本：`/Users/moka/IdeaProjects/Knowrary/tools/knowrary/knowrary.py`
- 规范原文：`/Users/moka/IdeaProjects/Knowrary/doc/规范文档/Markdown文档规范.md`
- 提示词全文（拆分原则与输出 JSON 结构）：`/Users/moka/IdeaProjects/Knowrary/tools/knowrary/prompts/article.md`
- 默认 vault：仓库根目录 `/Users/moka/IdeaProjects/Knowrary`（节点在 `nodes/`，领域总览在 `fields/`；解析器只扫这两个目录，`doc/ harness/ llm/` 里的 md 不是节点）

## 流程

1. **确认输入**：文章路径（或用户直接贴的文本，先写到 scratchpad 一个 .md）、目标 vault、`field`（顶层领域，如 `计算机体系结构` / `AI-Agent` / `JVM`）。field 用户没说就从文章主题判断并在结果里说明。
2. **拿上下文**（不要自己遍历 vault）：
   ```bash
   python3 /Users/moka/IdeaProjects/Knowrary/tools/knowrary/knowrary.py context --vault <vault> --article <文章>
   ```
   输出三段：可用关系类型、已有节点全部 id、与文章最相关的已有节点及其边。
3. **读文章，写方案 JSON**：按 `prompts/article.md` 里的拆分原则和输出结构，直接在 scratchpad 写 `plan.json`。要点：
   - 3～10 个节点，一个节点 = 一个可独立复习的概念；文章章节不等于节点。
   - 正文以原文为主体，保留作者原话和例子；从 `## 描述` 开始，不含 H1 / frontmatter / `## 关系`。
   - 关系优先连到**已有节点**，类型只从类型表选；方向从本节点指向目标；不要两侧重复写。
   - 正文里只能 `[[链接]]` 已有节点、本次新节点或 stubs；其余概念要么进 stubs，要么不链接。
   - 和已有节点是同一概念的，放 `merge_into`，不新建。
   - `year` 只在有明确年代且值得进历史视图时填，不猜。
4. **先 dry-run 给用户看**：
   ```bash
   python3 /Users/moka/IdeaProjects/Knowrary/tools/knowrary/knowrary.py apply plan.json --vault <vault> --field <field> --source "<文章名>" --dry-run
   ```
   脚本会校验 id 合法性、目标是否存在、类型是否登记，并打印将生成的每个文件。把摘要（节点数、最重要的新边、被丢弃的边、并入建议）讲给用户。
5. **用户确认后**去掉 `--dry-run` 写入；方案自动存到 `<vault>/.knowrary/imports/`。
6. **校验**：`python3 /Users/moka/IdeaProjects/Knowrary/tools/knowrary/knowrary.py check <vault>`，错误必须为 0；警告（未登记类型、演化边缺 year）如实汇报。
7. `merge_into` 里的内容不要自动改已有文件，列给用户，由用户决定是否并入。

## 不做的事

- 不改已有节点正文、不回填反向边（反链由解析器推导）。
- 不写坐标 / 分组进 frontmatter。
- 不为凑数拆节点；文章只有一个新概念就只建一个节点。
