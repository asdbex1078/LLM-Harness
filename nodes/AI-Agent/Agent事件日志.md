---
name: Agent 事件日志
field: AI-Agent
type: 模式
aliases:
  - Operation Log
  - 事件溯源
tags:
  - Agent
  - 可观测性
desc: 追加写入的事件表，服务端统一生成时间，保留请求 ID、幂等键和状态版本，用来区分“准备发送”和“已真正发出”
learned: 2026-09-10
source: 长程Agent任务生命周期与可控终止.md
---
# Agent 事件日志

## 描述

事件日志采用追加写入。事件时间由服务端统一生成，并保留请求 ID、幂等键和状态版本，这样才能区分“准备发送”和“请求已真正发出”。

## 核心内容

| 事件 | 含义 |
|---|---|
| `task_started` | 任务开始运行 |
| `cancel_requested` | 收到取消请求 |
| `llm_request_started` | 发起模型请求 |
| `tool_request_started` | 开始工具调用 |
| `external_request_sent` | 外部请求已写出 |
| `tool_result_received` | 收到工具结果 |
| `cancel_observed` | Worker 在检查点观察到取消 |
| `task_cancelled` | 任务完成取消收尾 |
| `task_recovered` | 任务从持久化状态恢复 |

`cancel_requested` 与 `cancel_observed` 分开记录，正好对应 [[任务取消语义]] 里“服务端标记”和“Worker 在 [[取消检查点]] 看到”两个时刻。

## 关系
- 属于:: [[长程Agent最小架构]] — 对应 Operation Log
