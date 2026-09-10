---
name: GraalVM
field: 计算机体系结构
year: 2018
tags:
  - 编译
  - JVM
  - 编译原理
desc: "基于跨平台的 hotspot jvm，上层的中间语言 IR 将各类语言都可以在 jvm 上运行，享有 jvm 的高性能跨平台 gc。https://www.gr…"
source: 知识图谱zhis.jpg
---
# GraalVM

基于跨平台的 hotspot jvm，上层的中间语言 IR 将各类语言都可以在 jvm 上运行，享有 jvm 的高性能跨平台 gc。https://www.graalvm.org/

分层（自下而上）：Java Hotspot VM → JVM CI（JVM Compiler Interface，Interface for Writing JIT Compiler in Java）→ Graal Compiler（JIT compiler written in Java）→ Truffle Framework → JavaScript / Ruby / R / Python / LLVM Interpreter；Java / Scala / Kotlin 直接走字节码。

对应编译原理：多种语言 → 中间结果 → 后端 → ISA 指令集。

## 关系
- 实现:: [[编译原理]]
- 基于:: [[JVM]]
- 包含:: [[JIT]]
- 包含:: [[解释器]]
- 部件:: [[字节码]]
- 依赖:: [[LLVM]]
