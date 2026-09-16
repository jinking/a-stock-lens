"""Record WeStock CLI fixtures for the offline test suite.

The recorded file is the command's stdout, verbatim, so the provider's tests
replay exactly what the source produced. That is the same rule the AkShare
recorder follows, and it is why the tests never need Node.js, network access,
or a WeStock binary.

Usage:

    ASTOCK_WESTOCK_BIN=/path/to/westock uv run python scripts/record_westock_fixture.py

The binary is never bundled or installed by this repository: the design keeps
A-Stock Lens free of another project's Python code, and the CLI stays an
operator-provided external command (design spec §24).
"""

import os
import subprocess
import sys
from pathlib import Path

from astock_lens.data.providers.westock import (
    BINARY_ENV,
    FINANCIAL_DATASETS,
    to_westock_code,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "westock"

# One batch covering a general manufacturer, a bank and a growth name: the
# three statement shapes differ enough that a parser bug on any one of them
# shows up in the fixture set.
SYMBOLS = ("600519.SH", "000001.SZ", "300750.SZ")
PERIODS = 8


def main() -> int:
    binary = os.getenv(BINARY_ENV, "").strip()
    if not binary:
        print(f"{BINARY_ENV} must point at the WeStock CLI binary", file=sys.stderr)
        return 1

    codes = ",".join(to_westock_code(symbol) for symbol in SYMBOLS)
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)

    for dataset, statement in sorted(FINANCIAL_DATASETS.items()):
        argv = [
            binary,
            "finance",
            codes,
            "--type",
            statement,
            "--limit",
            str(PERIODS),
            "--fields",
            "all",
        ]
        completed = subprocess.run(argv, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "(no stderr)"
            print(
                f"{dataset}: failed with {completed.returncode}: {detail}",
                file=sys.stderr,
            )
            return 1

        path = FIXTURE_ROOT / f"{dataset}.md"
        path.write_text(completed.stdout, encoding="utf-8")
        rows = sum(
            1 for line in completed.stdout.splitlines() if line.startswith("| s")
        )
        print(f"{dataset}: {rows} rows -> {path.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
