# Web 前端 (A-Stock Lens Web)

A-Stock Lens 本地只读研究看板，基于 React + TypeScript + Vite 构建。
前端仅通过 FastAPI 消费正式发布的快照数据与分析接口，在浏览器中直观呈现当日市场状态、研究候选池、单股画像与策略筛选。

## 技术栈与约束

- **运行环境**：Node 22
- **框架库**：React 18、TypeScript、Vite、React Router (v6)
- **测试框架**：Vitest、React Testing Library、jsdom
- **样式方案**：原生 CSS (Slate 冷灰色调主题、1280px 桌面 / 768px 平板响应式基线)
- **架构边界**：
  - **纯只读应用**：前端仅通过 FastAPI 访问后端，不直连 DuckDB 或本地快照文件；
  - **严禁前端重算**：不重新计算因子、排名或门槛，严格展示后端权威计算产物；
  - **排序权威性**：候选股票池排序以发布快照为准，前端筛选仅隐藏行，绝不改变排序；
  - **去交易化用语**：Candidate 始终表示“研究候选”，页面不出现任何买入/卖出/交易引导用语。

## 页面与路由

| 路由 | 页面组件 | 职责说明 |
|---|---|---|
| `/` | `TodayPage` | 今日研究概览：市场状态 (Market Regime)、候选池规模、策略分布与 Top 10 候选股票 |
| `/candidates` | `CandidatesPage` | 候选股票池：最新发布的研究候选列表、主选策略、合格策略与市场验证状态 |
| `/stocks/:symbol` | `StockProfilePage` | 单股画像：个股在候选池中的状态、策略契合度、因子明细与血缘追溯 |
| `/strategies/:strategyId` | `StrategyPage` | 策略筛选：单策略全市场排序 (Ranking) 与双门槛合格池 (Qualified) |

## 开发常用命令

在 `web/` 目录下执行：

```bash
# 安装依赖
npm ci

# 启动本地开发服务 (默认 http://127.0.0.1:5173)
npm run dev

# 运行自动化测试
npm run test

# 运行监听模式测试
npm run test:watch

# TypeScript 类型检查
npm run typecheck

# 生产环境构建打包
npm run build
```
