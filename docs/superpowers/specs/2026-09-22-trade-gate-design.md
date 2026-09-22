# Trade Gate V1 设计摘要

**日期：** 2026-09-22  
**状态：** 增量实现对应设计摘要；完整设计原文仍需归档。  
**来源：** 用户提供的 `2026-09-22-trade-gate-design (1).md`。

## 目标与边界

Trade Gate 针对一条明确的 ENTRY/ADD 意图判断当下是否 eligible，不是荐股系统。Candidate 仍是研究对象。V1 不自动下单、不管理退出、不接券商、不扩展 Watchlist 预留状态，也不加入 `astock daily`。

## 画像与裁决

支持 EVENT、SWING、POSITION 三种 Profile，配置权重合计 100。分数阈值固定：`>=80` 才可能 PASS，`70–<80` 为 WAIT，`<70` 为 NO_TRADE；硬 Veto 优先于分数。WAIT 必须保留重新评估触发条件。未知数据不得转成中性值。

## 事实、AI 与风险

确定性事实由规则计算；盘中事实必须由显式 `TradeMarketOverlay` 提供。两阶段 AI 审计先独立评估、再读取用户 thesis 做反方审计；AI 不能输出最终决定。AI 维度保存分数、置信度、证据与来源引用，采用 `score_ratio * (0.5 + 0.5 * confidence)` 调整。风险提案计算仓位金额和最大计划损失，不擅自添加账户风险上限。

## 持久化与生命周期

Trade Ledger 与正式 SnapshotStore 分离，按 ID append-only，同一意图可有多条评估。PASS 可形成计划；WAIT/NO_TRADE 仅可由显式 Override 进入执行路径。Override 要求理由、证据、FOMO 自评、更小仓位上限、止损规则与风险确认。执行和复盘为人工记录，不触发券商动作。

## 实施状态

截至 2026-09-22，核心模型、画像、快照上下文、AI Adapter、规则/裁决、Ledger、服务、CLI/API 基础入口及部分回放/校验器已实现。五个 Golden Scenario、全量生命周期覆盖、完整产物门禁与完整设计原文归档尚未完成；本摘要不构成 V1 完成交付声明。
