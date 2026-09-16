# A-Stock Lens — Design Package

这是 A-Stock Lens 的设计阶段产物，尚未进入业务实现。

当前包含：

- `docs/PRODUCT.md`：产品说明与 V1 范围
- `docs/ARCHITECTURE.md`：技术架构与模块边界
- `docs/superpowers/specs/2026-09-16-a-stock-lens-design.md`：完整设计规格（Superpowers）

## 当前状态

- 架构设计：已确认
- 正式 Spec：已生成
- Implementation Plan：待用户审核 Spec 后生成
- 业务代码：未开始

## 核心定位

A-Stock Lens 是一个本地优先、单用户、面向全 A 股的多策略选股与研究生命周期系统。

核心链路：

`Discover → Understand → Research → Track`

它负责从全市场发现候选并解释“为什么值得研究”；深度公司研究通过标准 `ResearchRequest` 松耦合集成现有 `a-share-deep-research`。
