---
name: 长程 Agent 最小架构
field: AI-Agent
type: 模式
tags:
  - Agent
  - Harness
  - 架构
desc: 六个组件：Task Store、Worker、Cancellation Channel、Operation Log、Recovery Worker、Idempotency Layer
learned: 2026-09-10
source: 长程Agent任务生命周期与可控终止.md
---
# 长程 Agent 最小架构

## 描述

一个可落地的最小架构，把 [[长程任务生命周期]]、[[任务取消语义]]、[[外部副作用与幂等键]]、[[崩溃恢复]] 各自落到一个组件上。

## 核心内容

1. **Task Store**：保存任务状态、版本、阶段和截止时间；
2. **Worker**：执行 LLM 与工具循环，在 [[取消检查点]] 读取取消状态；
3. **Cancellation Channel**：通过数据库轮询、消息队列或进程内信号传递取消请求；
4. **Operation Log**：记录工具调用和外部请求生命周期（[[Agent事件日志]]）；
5. **Recovery Worker**：处理超时、崩溃和状态未知的操作；
6. **Idempotency Layer**：防止重试造成重复副作用。

## 验收清单

- 取消后不会再发起新的 LLM 或工具请求；
- 正在执行的请求有明确的取消结果或待确认状态；
- 外部副作用具备幂等键和结果查询路径；
- Worker 崩溃后不会盲目重复执行；
- 暂停恢复后任务能从明确的下一步继续；
- 所有关键时间点和状态转换可通过事件日志还原；
- 厂商特性与通用机制分开，并有官方资料或实测证据支持。

## 参考资料

- [Kubernetes Jobs：终止 Job](https://kubernetes.io/docs/concepts/workloads/controllers/job/#terminating-a-job)：删除工作负载不等同于业务副作用回滚。
- [Firecracker：Snapshots](https://github.com/firecracker-microvm/firecracker/blob/main/docs/snapshotting/snapshot-support.md)：快照只描述运行环境的保存与恢复。
- [vLLM：Stopping generation](https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html)：请求停止是推理服务接口能力。
- [PostgreSQL：MVCC](https://www.postgresql.org/docs/current/mvcc.html)：持久化状态更新要处理并发与一致性。

## 关系
- 包含:: [[取消检查点]] — Worker 内的检查点
- 包含:: [[崩溃恢复]] — Recovery Worker
- 包含:: [[任务暂停与恢复]]
- 包含:: [[任务取消语义]] — Cancellation Channel
- 依赖:: [[harness]] — Worker 就是 Harness 的 LLM/工具循环
