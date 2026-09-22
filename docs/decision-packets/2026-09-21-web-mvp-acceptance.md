# Web MVP 本地验收记录

**验收日期：** 2026-09-22
**验收基准：** `2026-09-17` 正式 Candidate v2 快照
**范围：** Today / Candidates / Stock Profile / Strategy，只读 Web MVP

## 验收结果

- Today 页面候选数为 50，市场环境为 `BEAR`；策略分布为 `value=1`、`momentum=32`、`quality=10`、`growth=7`；市场验证为 `NEUTRAL=50`；信号分布为 `BREAKOUT=19`、`NO_SIGNAL=15`、`TREND_CONTINUE=12`、`TREND_WEAKEN=3`、`VALUE_CONTRARIAN=1`。
- Candidates 页面显示 50 条；前十顺序为 `000001.SZ`、`300741.SZ`、`600519.SH`、`688137.SH`、`000993.SZ`、`601579.SH`、`688209.SH`、`600371.SH`、`603444.SH`、`688331.SH`。与 `astock today`、`astock candidates` 和 `/today`、`/candidates` API 结果一致。
- Stock Profile 页面可从候选行进入 `000001.SZ`，展示已入选 Candidate 状态、因子与血缘内容；对应 `/stocks/000001.SZ` API 查询成功。
- Strategy 页面 `value` 排名覆盖为 `2 / 2303`，与 `astock screen value` 及 `/strategies/value/results` 一致；Qualified 页显示 1 只，与 `astock qualified value` 及 `/qualifications/value/results` 一致。
- Playwright 本地浏览器验收通过 `/`、`/candidates`、`/stocks/000001.SZ`、`/strategies/value`，Qualified 标签可用；本次浏览无 HTTP 4xx/5xx。
- 浏览器验收前后对 `data/snapshots/`、`data/watchlist/`（若存在）和 `var/jobs/` 文件做 SHA-256 清单比对，结果一致。验收 API 使用 JSON 存储后端，未访问或改写 DuckDB 状态。

## 本地工程门禁

- `npm ci`：通过。
- `npm run test`：9 个测试文件、65 项测试全部通过，包含缺失覆盖度和过期请求回归。
- `npm run typecheck`：通过。
- `npm run build`：通过。
- `.github/workflows/ci.yml` 已新增 Node.js 22 的 Web job，包含依赖安装、测试、类型检查和生产构建；Python job 未改动。

## 未执行的远端步骤

代码已提交至 `67fb318` 并推送到 `feat-web-upgrade`。截至 2026-09-22，GitHub Actions 尚无该分支运行记录：`.github/workflows/ci.yml` 仅配置 `main` 推送与 PR 触发，且该分支目前没有 PR。创建面向 `main` 的 PR 后才能触发远端 job；在取得运行记录前，不把远端 CI 记作已通过。最终复审还补充验证：缺失覆盖度不被伪装为零、旧请求不能覆盖新路由结果，且 Qualified 项只展示 API 实际提供的字段。

本次验收仅证明本地 Web 对所选正式快照的只读查询与页面表现，不代表其他日期数据覆盖完整，也不构成投资建议。
