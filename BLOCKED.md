# BLOCKED.md — 待裁决清单

> 当前依据：`docs/superpowers/plans/2026-09-18-storage-migration-v2-implementation-plan.md`
> 任务 2.1 / 2.2（"第二步·第一刀"）。本文件只列**需要所有者或更高权威裁决**的事；
> 执行者按默认走完的部分不在此列。
> 上一轮（第一步任务 1.1 / 1.2 / 1.3）的清单保留在第四节末尾，未闭合项已并入。

## 一、阻塞 2.1 / 2.2 本身的事项

**无。** 两个任务的验收命令全部退出码 0、测试全绿且 skipped=0，反向验证与行为不变
硬证据都已落盘（见 `PROGRESS.md` 与 `docs/REVIEW_NOTES.md` 第二十五、二十六节）。

## 二、本轮点名的"顺手活"——**不许做**，等裁决

以下四项是本切片明确不许碰的，全部照做（未动）：

| 项 | 为什么必须等裁决 |
| --- | --- |
| 修 `snapshots/duckdb_store.py` 读路径里的 `CREATE TABLE IF NOT EXISTS` | 属任务 2.5；在"只做读取边界"这刀里改它，等于在一次结构重构里夹带存储写入行为 |
| 删 `data/normalized/` 里的 4 个旧扁平 `.parquet` 与 `quality_findings.json` | 属历史遗留清理，先要确认它们不再被任何读取路径引用；而且 `docs/STORAGE.md` §6 的目录布局尚未裁决，删了没有"新布局"可指 |
| 装 `pyarrow` / `polars` | 2.3 才需要；本机现有 `duckdb 1.5.5` 足够。装依赖会改动 `uv.lock`，超出白名单 |
| 改任何业务规则（阈值、权重、PEG/估值口径） | 与存储迁移无关；第二步 §一 明确"迁移必须保存现有结果，行为修复在第三阶段另建基线" |

## 三、顺手发现、需要裁决是否处理（本轮未动）

1. **CLI 命令现在依赖配置文件可读。** `_store()` / `_job_store()` 以前只读环境变量，
   现在会经 `resolve_storage_paths()` 加载 `configs/app.yaml`。这是"指定配置文件
   缺失必须报错，不许静默走默认"的直接后果（任务 2.1 的死规矩），但它同时意味着：
   **在没有 `configs/` 的目录里跑 CLI 会失败**，除非显式设 `ASTOCK_CONFIG`。
   是否符合你的使用方式，需要你确认。证据见 `docs/REVIEW_NOTES.md` §25.2。
2. **非法 YAML 由 `yaml.YAMLError` 改报 `ValueError`**（原始异常挂在 `__cause__`）。
   原因是 `astock doctor` 只捕获 `OSError` / `ValueError` / `ValidationError`，不
   包装就会以一条回溯结束。异常类型变了，报错这件事没变。若你有别处按
   `YAMLError` 捕获，需要知会。
3. **`RawDataset.fetched_at` 是墙钟，导致 `NormalizeOutcome` 两次调用永不相等。**
   实测：provider 用 `datetime.now(UTC)` 打这个字段，于是计划 2.2 给的
   `assert actual == expected` 按字面过不去。本次比对改为"摘掉 `fetched_at` 一个
   字段、其余逐字段相等"。**这不是放宽断言**——留着它等于断言两次调用发生在同一
   微秒。需要你确认这个口径；将来任何"比对两份归一化结果"的代码都要先决定要不要
   看这个字段，默认比较会永远不相等。详见 `docs/REVIEW_NOTES.md` §26.2。
4. **`ruff format --check .` 原先那一处红已闭合**：上一轮遗留的
   `tests/unit/test_bootstrap_sync.py:158` 超长断言已在 `fbeba36` 拆行修正，
   本切片开工时 `ruff check` / `ruff format --check` / `mypy` / `git diff --check`
   全绿。此项无需再裁决。
5. **`tests/stress/` 有一条用例对机器快慢敏感：快环境下稳定红，更慢的运行方式下曾绿——
   需要你裁决怎么处理。**
   `test_mixed_failures_stay_explicit_and_the_run_still_converges` 断言"1% 超时 + 1% 来源
   错误 + 1% 空历史的标的不丢不伪装、循环收敛"。本轮实测：

   - 剥离 shim（快）串行单跑：**连续两次失败**（118.00s / 78.20s，断言都在第 252 行；
     单跑那次打印出的偏差标的是 `003500.SZ`）；
   - 剥离 shim（快）并行全量：同一条失败（`916 passed, 1 failed`，711.29s）；
   - 更慢的运行方式下它是绿的（管理者的 917 passed 记录，以及本机上一轮 582.30s 那次）。

   机制：假源对"超时"标的 `time.sleep(0.2)` 之后**仍返回正常数据**
   （`FakeMarketSource._answer`），而调度器每一轮**先查消息、再判 deadline**
   （`bootstrap_scheduler.fetch_symbols_bounded` 第 152–167 行）。机器一快，迟到结果更容易
   在判超时之前进队列，于是本该记超时的标被记成成功。该文件第 274–278 行的注释自己承认
   "假源没有进程隔离，超时被放弃的调用还在线程里跑"；AkShare 真实路径走可终止子进程，
   不存在这个迟到通道。

   **不是本切片引入的**：本切片只动 `data/repository`、`storage/paths.py`、`pipelines`、
   `settings.py` 与新增测试，没碰 `bootstrap*`；串行跑时 xdist 也不参与。我没有擅自改这条
   用例（改断言是敏感操作）。**请裁决**：① 让假源对超时标的永不返回（堵掉迟到通道）；
   ② 让调度器先判 deadline 再查消息（改实现语义）；③ 或者接受它"只在慢环境绿"，把它标记
   成环境敏感用例。
6. **`tests/conftest.py` 的 `local_tmp` 该不该恢复成 `tmp_path`？** 它 docstring 写的理由是
   "系统临时根被沙箱拒绝"，本轮看**只对了一半**：真正坏的是 broker 的 mkdir 补丁（第 3 条），
   不是临时根本身。候选做法：恢复 `tmp_path`（配合剥离 shim 跑），或把 `local_tmp` 挪到
   `tempfile.gettempdir()` 之下（shim 对 `/tmp` 下的路径会整条绕过 safe-delete）。
   本轮未改任何测试夹具，等你定。
7. **`pytest-xdist` 已被移除——实测对本仓库无收益，且会多制造一条假失败。** 本轮按"装并行
   插件"的建议实测（12 核机器，`-n auto`，全部剥离 shim）：

   | 跑法 | 结果 | 耗时 |
   | --- | --- | --- |
   | 非 stress 子集 + `-n auto` | 912 passed + 1 failed | 350.97s |
   | 全量 + 串行 | 916 passed + 1 failed（第三节第 5 条那条） | **560.90s** |
   | 全量 + `-n auto` | 916 passed + 1 failed（同一条） | 711.29s |

   并行**比串行更慢**（711.29s 对 560.90s：用例多为真实计算，12 个 worker 互相争抢），
   并且**多制造一条假失败**：
   `tests/unit/test_akshare_provider.py::test_process_isolation_bounds_a_non_returning_live_transport`
   （`spawn` 起子进程后断言 `elapsed < 1.0`）在争抢下超时，而**串行时它是绿的**。
   已执行 `uv remove --dev pytest-xdist`，结论写进 `docs/DEVELOPMENT.md` §7.1。

## 四、仍然开放的历史项（来自第一步，未闭合）

1. **9 只研究池标没有行业归属**：`000592.SZ`、`000968.SZ`、`002679.SZ`、
   `300896.SZ`、`600158.SH`、`600185.SH`、`600938.SH`、`601888.SH`、`689009.SH`。
   补法有两种（重新抓取 / 人工指派），选哪种决定这 9 只的行业归属算不算"证据"。
2. **`data/watchlist/` 目录在本机不存在**（还没有 tracked 标的）。清单如实记成
   `present=false, files=0`，没有伪造空目录。若要求"五类根目录必须都存在"，那是
   另一条产品规则。
3. **全量 pytest 的时间坑来自"注入的删除 shim"，与沙箱开关无关——上一轮"必须无沙箱"的
   结论已被本轮实测修正。**

   **（a）`tmp_path` 夹具被 broker 的 mkdir 补丁挡住——与沙箱开关无关。** 4 个既有用例
   （`tests/integration/test_candidate_calibration_cli.py` 里除 `test_calibrate_cli_help`
   外的 4 条）用 pytest 的 `tmp_path`，它会去建
   `/private/var/folders/…/T/pytest-of-unknown`。该目录在本机**已存在**（更早的会话
   残留，属主显示为 `unknown`），而 `sitecustomize` 的 `Path.mkdir` 补丁
   （`sitecustomize.py:747`）在 `exist_ok=True` 时**跳过了存在性短路**，直接向 broker
   发 mkdir，broker 回 `EEXIST`，补丁把它变成
   `PermissionError: EEXIST: file already exists, mkdir '…/pytest-of-unknown'`。
   **`exist_ok=True` 的语义在这个补丁里是坏的**——不是本仓库的代码问题。本轮补正两点：
   这条**与沙箱开关无关**（`PYTHONPATH` 由 Bash 工具层注入，禁沙箱后仍在），而且
   **只要残留目录在就会红**——上一轮那次"无沙箱 917 passed"只是因为当时
   `pytest-of-unknown` 恰好不存在。本机现在有三个残留：`pytest-of-unknown`、
   `pytest-of-root`、`pytest-of-huangjinjin`。

   **（b）删除 shim 让 teardown 又慢又假红。** 沙箱通过 `PYTHONPATH` 注入的
   `sitecustomize` 把 `os.remove` / `os.rmdir` / `shutil.rmtree` / `Path.unlink` 全部
   改道，每条删除路径上叠三层成本：① **每条删除起一个 Node 子进程**做"批量删除守卫"
   检查（`subprocess.run([node, safe-delete-bulk-guard.cjs, "check", …], timeout=10)`）；
   ② 命中回收站（broker IPC → 宿主机）；③ 守卫按会话累计条目，超过阈值（默认 50）就
   要求人工确认，未确认时 `SystemExit(1)`。而 `tests/conftest.py` 的 `local_tmp`
   夹具**每个用例**都在 teardown 里 `shutil.rmtree(tests/.tmp/<uuid>)`，一次全量跑要
   走上万次第 ① 步。

   对照实测（同一文件 `tests/integration/test_calibration_readiness_cli.py`）：

   | 运行方式 | 结果 | 耗时 |
   | --- | --- | --- |
   | 默认（守卫阈值 50） | 9 passed + **9 ERROR** | — |
   | `CODEBUDDY_SAFE_DELETE_BULK_THRESHOLD=100000000` | 9 passed | 106.86s |
   | `CODEBUDDY_SAFE_DELETE_ENABLED=0` | 9 passed | 27.82s |
   | **注入 shim 的全量（上一轮）** | 917 passed / 0 ERROR | 582.30s |
   | **`PYTHONPATH=` 单文件（`test_calibration_readiness_cli.py`）** | 9 passed | 32.25s |
   | **`PYTHONPATH=` 全量串行（本轮最佳）** | 916 passed + **1 failed**（第三节第 5 条那条） | **560.90s** |

   新增量化：**同一次 `mkdir + write`，注入 shim 时 0.372s，剥离后 0.0125s——差 30 倍。**
   一次全量有上万次这类操作，这就是"全量跑不完"的真正单价。上一轮的 582.30s 说明当时
   shim 还没退化；本轮它已慢到单条 stress 用例 21 分钟跑不完。

   **已按所有者指示处理（本轮）**：`docs/DEVELOPMENT.md` 新增 §7（分层跑法 + 运行环境），
   `README.md` 的测试章节与 `AGENTS.md` 的命令节各留指针；`Makefile` 新增 `test-fast` /
   `test-stress`，并让 `PYTHONPATH` 可透传，于是 `make test PYTHONPATH=` 一键剥离 shim。
   `tests/conftest.py` 的 `local_tmp` **未改**——是否恢复 `tmp_path` 见第三节第 6 条。
   并行插件（`pytest-xdist`）实测无收益且会多制造一条假失败，已移除，见第三节第 7 条。

## 五、与所有者的约定一致、但值得记一笔的边界

- **不 push、不合并、不改 CI**：只做本地提交到 `main`，本切片两条提交
  （`6a824fe` 统一路径解析；归一化读取边界一条见 `git log`）。
- **`var/acceptance/**` 不入库**（`.gitignore:31`）。本切片证据都在
  `var/acceptance/storage-v2-20260919/` 下。
- **`data/normalized/` 的 4 个旧 `.parquet` + `quality_findings.json` 只读未动**：
  它们是旧扁平布局遗留，**不是"迁移已完成"的证据**。本切片不碰 Parquet。
- **`configs/**`、`data/**`、`var/**` 的既有内容零改动**：`configs` 未改一个字节；
  `data/raw` + `data/snapshots` + `data/watchlist` + `var/jobs` 共 5,021 个文件的
  sha256 与本轮开工时一致（见 `PROGRESS.md` 末节）。
- **一个与本任务无关的既有未跟踪文件** `var/industry-map-2026-09-18.csv`
  保持原样：未改动、未入库、未删除。
