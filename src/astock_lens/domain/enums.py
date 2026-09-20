"""Approved domain vocabularies.

Every enumeration here is copied from the design spec or `docs/ARCHITECTURE.md`.
Values that the design does not enumerate are deliberately absent rather than
guessed.
"""

from enum import StrEnum


class DataStatus(StrEnum):
    """Explicit missing-data states.

    A missing value is never represented as zero.
    """

    VALUE = "VALUE"
    NULL = "NULL"
    STALE = "STALE"
    INVALID = "INVALID"
    SOURCE_ERROR = "SOURCE_ERROR"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ErrorSeverity(StrEnum):
    """Error severities; P0 blocks the current scan."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class WatchlistState(StrEnum):
    """Watchlist lifecycle states.

    `DISCOVERED → WATCH → DEEP_RESEARCH → TRACK_SIGNAL` is the only active V1
    path. The remaining states are reserved for future phases and must not be
    reachable in V1.
    """

    DISCOVERED = "DISCOVERED"
    WATCH = "WATCH"
    DEEP_RESEARCH = "DEEP_RESEARCH"
    TRACK_SIGNAL = "TRACK_SIGNAL"
    READY = "READY"
    HOLDING = "HOLDING"
    EXITED = "EXITED"
    ARCHIVED = "ARCHIVED"


ACTIVE_WATCHLIST_STATES: frozenset[WatchlistState] = frozenset(
    {
        WatchlistState.DISCOVERED,
        WatchlistState.WATCH,
        WatchlistState.DEEP_RESEARCH,
        WatchlistState.TRACK_SIGNAL,
    }
)

RESERVED_WATCHLIST_STATES: frozenset[WatchlistState] = frozenset(
    {
        WatchlistState.READY,
        WatchlistState.HOLDING,
        WatchlistState.EXITED,
        WatchlistState.ARCHIVED,
    }
)


class MarketRegime(StrEnum):
    """Market regime states. The router adjusts priority, never raw scores."""

    BULL = "BULL"
    RANGE_UP = "RANGE_UP"
    RANGE = "RANGE"
    RANGE_DOWN = "RANGE_DOWN"
    BEAR = "BEAR"


class MarketValidation(StrEnum):
    """Market validation outcomes for a candidate."""

    CONFIRMED = "CONFIRMED"
    NEUTRAL = "NEUTRAL"
    CONTRADICTED = "CONTRADICTED"


class Signal(StrEnum):
    """V1 signal vocabulary.

    A signal describes a market state; it is never an investment
    recommendation.
    """

    BREAKOUT = "BREAKOUT"
    PULLBACK = "PULLBACK"
    TREND_CONTINUE = "TREND_CONTINUE"
    TREND_WEAKEN = "TREND_WEAKEN"
    BREAKDOWN = "BREAKDOWN"
    VALUE_CONTRARIAN = "VALUE_CONTRARIAN"
    DIVIDEND_SUPPORT = "DIVIDEND_SUPPORT"
    NO_SIGNAL = "NO_SIGNAL"
    WATCH = "WATCH"


class NextAction(StrEnum):
    """Allowed next actions for a candidate."""

    IGNORE = "IGNORE"
    WATCH = "WATCH"
    DEEP_RESEARCH = "DEEP_RESEARCH"
    TRACK_SIGNAL = "TRACK_SIGNAL"


class FactorDomain(StrEnum):
    """Factor domains targeted by V1."""

    FUNDAMENTAL = "FUNDAMENTAL"
    GROWTH = "GROWTH"
    QUALITY = "QUALITY"
    VALUATION = "VALUATION"
    MARKET_MOMENTUM = "MARKET_MOMENTUM"
    TECHNICAL = "TECHNICAL"


class JobStage(StrEnum):
    """Daily pipeline stages; each one is independently restartable."""

    SYNC_DATA = "SYNC_DATA"
    NORMALIZE = "NORMALIZE"
    BUILD_UNIVERSE = "BUILD_UNIVERSE"
    COMPUTE_FACTORS = "COMPUTE_FACTORS"
    RUN_STRATEGIES = "RUN_STRATEGIES"
    DETECT_REGIME = "DETECT_REGIME"
    MARKET_VALIDATE = "MARKET_VALIDATE"
    RUN_SIGNALS = "RUN_SIGNALS"
    BUILD_CANDIDATES = "BUILD_CANDIDATES"
    UPDATE_WATCHLIST = "UPDATE_WATCHLIST"
    GENERATE_DAILY_SNAPSHOT = "GENERATE_DAILY_SNAPSHOT"


class SnapshotKind(StrEnum):
    """Snapshots persisted after a daily scan."""

    UNIVERSE = "UNIVERSE"
    FACTOR = "FACTOR"
    STRATEGY = "STRATEGY"
    MARKET_REGIME = "MARKET_REGIME"
    CANDIDATE = "CANDIDATE"
