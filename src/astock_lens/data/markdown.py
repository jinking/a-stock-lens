"""Markdown 表格与键值块的解析。

两个数据源都用 Markdown 作答：腾讯 WeStock CLI 直接打印表格，neodata 把表格放在
JSON 的 `content` 字段里。解析规则只写一份，避免两边对"什么算一行"给出不同答案。

两条规矩：

- 单元格逐字保留（不做数值转换、不补零），缺失标记原样留下；
- 表头与实际行宽不一致时**抛错**而不是猜——一张读不完整的表不能被当成读完了。
"""

from collections.abc import Mapping
from dataclasses import dataclass

DASH = "-"


class MalformedTable(ValueError):
    """文本里有表格，但读不成一张可信的表。"""


@dataclass(frozen=True)
class Table:
    """一张 Markdown 表，单元格逐字。"""

    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


def parse_tables(text: str) -> tuple[Table, ...]:
    """读出文本里的每一张 Markdown 表。

    表格前后的散文（例如 CLI 的批次状态行）被忽略：那是关于请求的说明，不是数据。
    """
    lines = text.splitlines()
    tables: list[Table] = []
    index = 0

    while index < len(lines):
        if not _is_row(lines[index]):
            index += 1
            continue
        header = _cells(lines[index])
        if index + 1 >= len(lines) or not _is_separator(lines[index + 1]):
            index += 1
            continue

        rows: list[tuple[str, ...]] = []
        cursor = index + 2
        while cursor < len(lines) and _is_row(lines[cursor]):
            row = _cells(lines[cursor])
            if len(row) != len(header):
                raise MalformedTable(
                    f"第 {cursor + 1} 行有 {len(row)} 个单元格，表头声明了 "
                    f"{len(header)} 个"
                )
            rows.append(row)
            cursor += 1
        tables.append(Table(columns=header, rows=tuple(rows)))
        index = cursor

    return tuple(tables)


def parse_key_values(text: str) -> dict[str, str]:
    """读出 `**字段**: 值` 形式的键值行。

    neodata 的估值块就是这个形状：字段名会被加粗，值跟在冒号后。只认加粗的字段名，
    因为普通行里的冒号（例如单位说明）不是键值。
    """
    found: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("**") or "**" not in stripped[2:]:
            continue
        label, _, rest = stripped[2:].partition("**")
        _, separator, value = rest.partition(":")
        if not separator:
            continue
        label = label.strip()
        if label:
            found[label] = value.strip()
    return found


def table_row_as_mapping(table: Table, row: tuple[str, ...]) -> Mapping[str, str]:
    """把一行按表头映射成字典，便于按列名取值。"""
    return {
        column: row[index]
        for index, column in enumerate(table.columns)
        if index < len(row)
    }


def _is_row(line: str) -> bool:
    return line.strip().startswith("|")


def _is_separator(line: str) -> bool:
    cells = _cells(line)
    return bool(cells) and all(
        set(cell) <= {DASH, ":"} and DASH in cell for cell in cells
    )


def _cells(line: str) -> tuple[str, ...]:
    """把一行 Markdown 拆成逐字单元格。"""
    stripped = line.strip()
    stripped = stripped.removeprefix("|")
    stripped = stripped.removesuffix("|")
    return tuple(cell.strip() for cell in stripped.split("|"))
