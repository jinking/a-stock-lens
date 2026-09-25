"""Universe configuration loading.

`configs/universe.yaml` is the only place the Universe thresholds live. These
tests pin the two rulings this slice records: the liquidity floor came from the
project owner (20,000,000 CNY), and the long-suspension day count is explicitly
deferred rather than guessed.
"""

import re
from pathlib import Path

import yaml

from astock_lens.universe.config import UniverseConfig, load_universe_config

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "universe.yaml"


def _load() -> UniverseConfig:
    return load_universe_config(CONFIG_PATH)


def test_repository_config_loads() -> None:
    config = _load()

    # 所有者 2026-09-18 决定：暂时只纳入沪深两市（北交所日线在现用接口上取不到）。
    assert config.exchanges == ("SSE", "SZSE")
    assert config.min_listing_days == 120


def test_liquidity_floor_carries_the_owner_supplied_value() -> None:
    """门槛是人的决定，记在配置里、不在代码里。

    2026-09-16 由所有者给定 20,000,000；2026-09-18 同一位所有者要求研究池约 2,000–3,000 只，
    实测 100M → 2,961、150M → 2,303、200M → 1,853，取中段 150,000,000。
    """
    assert _load().min_average_turnover_20d == 150_000_000.0


def test_long_suspension_is_deferred_not_defaulted() -> None:
    """The rule is switched on, but no day count has been reviewed."""
    config = _load()

    assert config.exclude_long_suspension is True
    assert config.long_suspension_days is None


def _payload_without_liquidity_floor() -> dict[str, object]:
    """第 1 行的载荷：删掉流动性门槛键（原用例语句逐字保留）。"""
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    del payload["min_average_turnover_20d"]
    return payload


def _payload_without_listing_age() -> dict[str, object]:
    """第 2 行的载荷：删掉上市天数键（原用例语句逐字保留）。"""
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    del payload["min_listing_days"]
    return payload


def _payload_with_unknown_key() -> dict[str, object]:
    """第 3 行的载荷：金额键拼错（原用例语句逐字保留）。"""
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    payload["min_average_turnover_2d"] = 5_000_000
    return payload


# 「配置损坏必须响亮失败」三行：行序与原用例一致，label 即原测试名，
# 原 docstring 逐字保留为行注释；`expected=None` 表示该行原本不断言消息。
# 列 = label, payload, expected：
#   - `payload` 为零参可调用，返回经就地改动后的 yaml 载荷；
#   - `expected` 逐字取自原 `pytest.raises(..., match=...)` 的片段，
#     比对方式与原断言同为 `re.search`。
UNIVERSE_CONFIG_ERROR_CASES = (
    # test_a_missing_liquidity_floor_is_an_error_not_a_fallback:
    #   Deleting the key must fail loudly; there is no code default.
    (
        "test_a_missing_liquidity_floor_is_an_error_not_a_fallback",
        _payload_without_liquidity_floor,
        "min_average_turnover_20d",
    ),
    # test_a_missing_listing_age_is_an_error_not_a_fallback
    (
        "test_a_missing_listing_age_is_an_error_not_a_fallback",
        _payload_without_listing_age,
        "min_listing_days",
    ),
    # test_an_unknown_key_is_rejected:
    #   A typo in the config must not be silently ignored.
    (
        "test_an_unknown_key_is_rejected",
        _payload_with_unknown_key,
        None,
    ),
)


def test_broken_configurations_are_refused() -> None:
    """缺门槛键 / 缺上市天数键 / 多余键各自以 ValueError 拒绝。

    原 3 条「is an error / is rejected」用例逐条成行；循环只收集，
    断言在表外一次完成，失败消息点名行 label（即原测试名）。
    """
    wrong = []
    for label, payload, expected in UNIVERSE_CONFIG_ERROR_CASES:
        try:
            UniverseConfig.model_validate(payload())
        except ValueError as exc:
            if expected is not None and re.search(expected, str(exc)) is None:
                wrong.append(
                    f"{label}: 错误消息中找不到 {expected!r}，实际 {str(exc)!r}"
                )
        else:
            wrong.append(f"{label}: 未抛出 ValueError")
    assert not wrong, "损坏的 universe 配置未被拒绝:\n" + "\n".join(wrong)


def test_digest_is_stable_and_content_sensitive() -> None:
    config = _load()

    assert config.digest() == _load().digest()
    assert (
        config.digest() != config.model_copy(update={"min_listing_days": 121}).digest()
    )
