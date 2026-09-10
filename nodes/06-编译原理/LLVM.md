---
name: LLVM
field: 计算机体系结构
year: 2003
tags:
  - 编译
  - 工具链
  - 编译原理
desc: LLVM 一切组件皆可独立，单独出来使用，全部路程均可使用插拔机制来配置使用 ——》高度可定制 ——》开源后所有语言皆可按照模块化接入
source: 知识图谱zhis.jpg
---
# LLVM

LLVM 一切组件皆可独立，单独出来使用，全部路程均可使用插拔机制来配置使用 ——》高度可定制 ——》开源后所有语言皆可按照模块化接入。

流水线：源程序 → Clang 前端或带 Dragon Egg 的 GCC → LLVM IR 链接器 → LLVM IR 优化器 → LLVM 后端 → LLVM 集成汇编器 → GCC 链接器或 LLD（开发中）→ 二进制程序（链接 Compiler-RT 运行时库、libc++ 标准库、系统库）。

C Lang 前端 → LLVM 后端 → ISA 指令集。

## 关系
- 实现:: [[编译原理]]
- 部件:: [[Clang]]
- 部件:: [[编译器后端]]
- 部件:: [[IR]]
- 产出:: [[ISA]]
- 演化为:: [[eBPF]]
