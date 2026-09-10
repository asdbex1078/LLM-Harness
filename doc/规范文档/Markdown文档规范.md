# Knowrary Markdown 文档规范

> 版本：v1.0
> 适用范围：Knowrary vault（个人知识库）中的知识节点 Markdown 文件

## 1. 基本原则

1. 一个知识节点对应一个 Markdown 文件。
2. Markdown 保存知识内容和关系，是知识层唯一真相源。
3. 坐标、分组、折叠状态、便签和图片位置统一保存到 `.knowrary/layout.json`。
4. 文件必须能被 Obsidian 直接打开；关系语法兼容 Dataview 内联字段。
5. 机器生成内容必须标记为候选或草稿，不能默默覆盖人工内容。

## 2. 文件与命名

推荐目录结构：

```text
vault/
├── nodes/
├── fields/
├── assets/
└── .knowrary/
    ├── index.json
    ├── layout.json
    └── backup/
```

文件名使用小写英文、拼音或稳定的短横线标识，例如 `attention-mechanism.md`。文件名被引用后不应随意修改。节点 `id` 默认取文件名去掉 `.md` 的部分，也可以在 frontmatter 中显式指定；显式 `id` 必须全局唯一。

## 3. Frontmatter 规范

```yaml
---
id: transformer
name: Transformer
field: AI-LLM
type: 模型架构
status: active
year: 2017
start_year: 2017
end_year: null
aliases:
  - 自注意力模型
tags:
  - 深度学习
  - 序列建模
desc: 基于自注意力机制的序列建模架构
learned: 2026-09-10
---
```

| 字段 | 必填 | 类型 | 规则 |
| --- | --- | --- | --- |
| `id` | 否 | string | 缺省取文件名；显式值必须唯一 |
| `name` | 是 | string | 展示名称，不能为空 |
| `field` | 是 | string | 顶层领域，对应默认分组 |
| `type` | 否 | string | 节点类型 |
| `status` | 否 | enum | `active`、`deprecated`、`disputed`、`stub` |
| `year` | 否 | integer | 进入历史视图的核心年份 |
| `start_year/end_year` | 否 | integer/null | 有效期场景，区间左闭右开 |
| `aliases/tags` | 否 | string[] | 检索和合并，不承担布局语义 |
| `desc` | 是 | string | 一句话摘要 |
| `learned` | 否 | date | 首次加入知识库的日期；复习记录不进 md，在 `.knowrary/review-log.json` |

`year` 是可选的历史事件元数据；没有 `year` 的节点只进入结构视图。未来需要表达多个事件时扩展为 `events: [{ year, type, note }]`。未知年份留空，不填写猜测值。

## 4. 正文结构

推荐顺序：

```markdown
# 节点名称

## 描述
用自己的话说明这个知识点是什么、解决什么问题。

## 核心内容
记录原理、公式、代码、例子或个人理解。

## 关系
- 源自:: [[attention-mechanism]] (2014) — 核心思想来源
- 部件:: [[multi-head-attention]]

## 参考资料
- [资料标题](https://example.com)

## 待办
- [ ] 补充尚未理解的细节
```

只有 `## 关系` 区块会被关系解析器读取，其他正文由用户自由组织，写回时必须保留。

## 5. 关系语法

```markdown
- 类型:: [[目标 id]]
- 类型:: [[目标 id]] (2018)
- 类型:: [[目标 id]] — 关系说明
- 类型:: [[目标 id]] (2018) — 关系说明
```

规则：

1. 每行以 `- ` 开始，关系一行一个目标。
2. 类型和目标之间使用 `::`，目标使用稳定的 `[[id]]`。
3. 年份和说明可选，说明用 `—` 分隔。
4. 反向关系由解析器推导，不在目标节点中重复回填。
5. 目标不存在时生成 stub 或诊断项，不能静默丢边。
6. 未登记类型归入“弱关联”族并产生警告。

关系族固定为：结构（包含、部件、属于）、依赖（依赖、基于、实现）、演化（源自、演化为、修订、被激活）、对照（对比、类比、争议）、弱关联（影响、相关、参考）。具体类型由 `relation-types.json` 维护。

## 6. Stub 与编写规则

被引用但尚未创建的节点可作为 `stub`：状态为 `stub`，名称取引用文本，描述为“待补充”。补写后改为 `active` 并补齐 `desc`。

- 不把坐标、分组、折叠状态写进 frontmatter。
- 不重复维护反向关系。
- 不用关系类型表达纯视觉分组。
- 不确定的年份留空，并在正文或待办中记录待核实事项。
- 合并节点前保留原文件和引用迁移记录。

## 7. 校验清单

- [ ] frontmatter 合法，`name`、`field`、`desc` 非空。
- [ ] `id` 全局唯一，目标可解析或明确列为 stub。
- [ ] 年份为四位整数，时间区间没有反转。
- [ ] 关系符合 `- 类型:: [[目标]] (年份) — 说明` 格式。
- [ ] 关系类型已登记或已接受归入弱关联族。
- [ ] 没有重复维护反向边。
- [ ] 正文没有混入布局信息。
