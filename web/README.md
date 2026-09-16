# Web 前端（规划）

V1 计划使用 React + FastAPI，实现 6 个页面：

1. **Today**：Market Regime、当日扫描计数、新增与移除的 Candidate、Watchlist 状态变化、待处理研究、数据健康。
2. **Screener**：策略模式与因子过滤模式，二者概念上分开。
3. **Strategy**：策略目的、持有周期、适配的市场环境、失效模式、当前优先级与当前结果。
4. **Stock Profile**：Overview、Strategy Map、Factor 明细、Market Validation、Signals、Research、Timeline；每个分数都能下钻到因子级解释。
5. **Watchlist**：观察池与状态机、Timeline。
6. **Data Health**：Provider 与 Dataset 新鲜度、错误分级。

## 为什么现在不初始化 React

前端尚未开始，原因是它依赖的领域 API 还不存在：Web 不得直接访问 DuckDB，也不得重新计算因子，所以必须先有领域查询接口，页面才有真实内容可渲染。

在 API 就绪前搭建脚手架，只会得到一个没有真实数据源的演示外壳，并且会锁定当时的接口猜测。因此本目录当前只记录页面规划。

## 边界

- 前端只通过 FastAPI 访问数据；
- 不在前端重算 ROE / PE 等因子；
- 页面展示 Candidate 时不得改写为推荐口径。
