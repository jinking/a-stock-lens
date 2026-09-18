"""把 WeStock `sector` 的两个响应规范化成行业记录。

目录响应是一张 `code,name,…` 的行情榜；成员响应是一张 `code,name` 表，标题里带着
行业名与层级（实测：`申万二级行业成分股-股份制银行Ⅱ [申万二级行业] (9 只)`）。

两条判定用力的地方：

- **标题必须与调用方要的行业一致**。目录说这是一个板块、标题说是另一个，说明这次
  调用拿回的是别人的答案；此时记录下来的成员关系会错误地挂到该板块名下。
- **无法解析的代码必须报错**，不能跳过。跳过会让某只标的从行业分布里消失，而报告
  的行业覆盖率却看不出少了谁。
"""

from datetime import datetime

from astock_lens.data.industry import IndustryCatalogEntry, IndustryMembership
from astock_lens.data.markdown import parse_tables
from astock_lens.data.providers.westock import from_westock_code

CANONICAL_SYMBOL_COLUMN = "code"
CODE_COLUMN = "code"
NAME_COLUMN = "name"


class IndustryConstituentError(ValueError):
    """源站响应不是本模块能如实解释的形状。"""


def parse_sector_catalog(text: str) -> tuple[IndustryCatalogEntry, ...]:
    """读出目录里的板块代码与名称，保持源站给出的顺序。"""
    tables = parse_tables(text)
    if not tables:
        raise IndustryConstituentError("sector catalog carried no table")
    table = tables[0]
    index = _columns(table.columns, (CODE_COLUMN, NAME_COLUMN), "catalog")

    entries: list[IndustryCatalogEntry] = []
    for row in table.rows:
        code = row[index[CODE_COLUMN]].strip()
        name = row[index[NAME_COLUMN]].strip()
        if not code or not name:
            raise IndustryConstituentError(
                f"sector catalog row has an empty code or name: {row!r}"
            )
        entries.append(IndustryCatalogEntry(industry_id=code, industry_name=name))
    return tuple(entries)


def normalize_constituents(
    text: str,
    *,
    industry_id: str,
    industry_name: str,
    as_of: datetime,
    provider: str,
    source_ref: str | None = None,
) -> tuple[IndustryMembership, ...]:
    """把一次成员响应折成规范记录，按 symbol 排序并去重。"""
    _require_matching_title(text, industry_name)

    tables = parse_tables(text)
    if not tables:
        raise IndustryConstituentError(
            f"constituent response for {industry_id} carried no table"
        )
    table = tables[0]
    index = _columns(table.columns, (CODE_COLUMN, NAME_COLUMN), "constituent")

    by_symbol: dict[str, IndustryMembership] = {}
    for row in table.rows:
        raw_code = row[index[CODE_COLUMN]].strip()
        raw_name = row[index[NAME_COLUMN]].strip()
        if not raw_code or not raw_name:
            raise IndustryConstituentError(
                f"constituent row in {industry_id} has an empty code or name: {row!r}"
            )
        try:
            symbol = from_westock_code(raw_code)
        except ValueError as error:
            raise IndustryConstituentError(
                f"constituent row {raw_code!r} ({raw_name}) in {industry_id} "
                f"cannot be parsed into a canonical symbol: {error}"
            ) from error
        by_symbol[symbol] = IndustryMembership(
            symbol=symbol,
            industry_id=industry_id,
            industry_name=industry_name,
            as_of=as_of,
            provider=provider,
            source_ref=source_ref or raw_name,
        )

    return tuple(by_symbol[symbol] for symbol in sorted(by_symbol))


def _columns(
    columns: tuple[str, ...], needed: tuple[str, ...], what: str
) -> dict[str, int]:
    missing = [column for column in needed if column not in columns]
    if missing:
        raise IndustryConstituentError(
            f"{what} table lacks the columns {missing}; it carried {list(columns)}"
        )
    return {column: columns.index(column) for column in needed}


def _require_matching_title(text: str, industry_name: str) -> None:
    """标题里的行业名必须就是调用方要的那个。"""
    for line in text.splitlines():
        if "成分股" not in line:
            continue
        if industry_name in line:
            return
        raise IndustryConstituentError(
            f"the response is for another industry: asked for {industry_name!r}, "
            f"the title says {line.strip()!r}"
        )
    raise IndustryConstituentError(
        f"the response carries no title naming the industry ({industry_name!r})"
    )
