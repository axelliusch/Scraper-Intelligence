from __future__ import annotations

import dataclasses
import os
import shutil
from typing import Mapping

# Status values ---------------------------------------------------------------
AVAILABLE = "AVAILABLE"
PARTIAL = "PARTIAL"
MISSING_CREDENTIALS = "MISSING_CREDENTIALS"
NOT_INSTALLED = "NOT_INSTALLED"
NOT_CONFIGURED = "NOT_CONFIGURED"
AUTH_FAILED = "AUTH_FAILED"
RATE_LIMITED = "RATE_LIMITED"
UNREACHABLE = "UNREACHABLE"
ERROR = "ERROR"
NO_RESULTS = "NO_RESULTS"

#: Full status vocabulary, ordered worst -> best for summary/table rendering.
STATUSES = (
    ERROR,
    UNREACHABLE,
    AUTH_FAILED,
    RATE_LIMITED,
    MISSING_CREDENTIALS,
    NOT_INSTALLED,
    NOT_CONFIGURED,
    NO_RESULTS,
    PARTIAL,
    AVAILABLE,
)

# Legacy aliases kept for readers of older coverage logs (see README).
UNCONFIGURED = NOT_CONFIGURED
UNAVAILABLE = ERROR

#: Engine outcome states (lib/health.py) -> ST Trinity root-cause status.
_ENGINE_STATUS_TO_STATUS: dict[str, str] = {
    "ok": AVAILABLE,
    "partial": PARTIAL,
    "no-results": NO_RESULTS,
    "auth-failed": AUTH_FAILED,
    "auth_failed": AUTH_FAILED,
    "rate-limited": RATE_LIMITED,
    "rate_limited": RATE_LIMITED,
    "timeout": UNREACHABLE,
    "unreachable": UNREACHABLE,
    "error": ERROR,
    "broken": ERROR,
    "schema-drift": ERROR,
    "missing": NOT_INSTALLED,
    "skipped-unconfigured": NOT_CONFIGURED,
}


@dataclasses.dataclass(frozen=True)
class PlatformSpec:
    """Static capability metadata for one schema platform."""

    key: str  # schema platform key, e.g. "reddit"
    name: str  # display name, e.g. "Reddit"
    engine_names: tuple[str, ...]  # engine --search source names -> this platform
    keyless: bool = False  # engine can run with no credential at all
    env: tuple[str, ...] = ()  # env vars that enable/upgrade the platform
    cli: str | None = None  # optional external CLI dependency (e.g. "yt-dlp")
    partial_default: bool = False  # degraded even when configured (anon caps)

    def engine_tokens(self) -> str:
        return ",".join(self.engine_names)


PLATFORM_SPECS: tuple[PlatformSpec, ...] = (
    PlatformSpec(
        key="reddit",
        name="Reddit",
        engine_names=("reddit",),
        keyless=True,
        partial_default=True,
    ),
    PlatformSpec(
        key="hackernews",
        name="Hacker News",
        engine_names=("hackernews",),
        keyless=True,
    ),
    PlatformSpec(
        key="github",
        name="GitHub",
        engine_names=("github",),
        keyless=True,
        env=("GITHUB_TOKEN", "GH_TOKEN"),
        partial_default=True,
    ),
    PlatformSpec(
        key="youtube",
        name="YouTube",
        engine_names=("youtube",),
        keyless=True,
        env=("YOUTUBE_API_KEY", "YOUTUBE_KEY"),
        cli="yt-dlp",
        partial_default=True,
    ),
    PlatformSpec(
        key="x",
        name="X (Twitter)",
        engine_names=("x",),
        env=(
            "SCRAPECREATORS_API_KEY",
            "X_BACKEND",
            "XAI_API_KEY",
            "BIRD_X_COOKIE",
            "XURL_AUTH",
        ),
    ),
    PlatformSpec(
        key="tiktok",
        name="TikTok",
        engine_names=("tiktok",),
        env=("SCRAPECREATORS_API_KEY",),
    ),
    PlatformSpec(
        key="instagram",
        name="Instagram",
        engine_names=("instagram",),
        env=("SCRAPECREATORS_API_KEY",),
    ),
    PlatformSpec(
        key="linkedin",
        name="LinkedIn",
        engine_names=("linkedin",),
        env=("SCRAPECREATORS_API_KEY",),
    ),
    PlatformSpec(
        key="threads",
        name="Threads",
        engine_names=("threads",),
        env=("SCRAPECREATORS_API_KEY",),
    ),
    PlatformSpec(
        key="pinterest",
        name="Pinterest",
        engine_names=("pinterest",),
        env=("SCRAPECREATORS_API_KEY",),
    ),
    # `web` is the schema's catch-all platform (data/social/SCHEMA.md §2/§5).
    # The engine reaches it through its `grounding` (general web) source.
    PlatformSpec(
        key="web",
        name="Web",
        engine_names=("grounding",),
        keyless=True,
    ),
    # Non-engine platform: collected by the dedicated TelegramAdapter (public
    # channel web preview, keyless, no credentials required).
    PlatformSpec(
        key="telegram",
        name="Telegram",
        engine_names=(),
        keyless=True,
    ),
)

#: Schema key -> spec, for lookups by the coverage report.
BY_KEY: dict[str, PlatformSpec] = {s.key: s for s in PLATFORM_SPECS}

#: Engine source name -> schema key (superset of the adapter's own mapping).
ENGINE_TO_PLATFORM: dict[str, str] = {}
for _spec in PLATFORM_SPECS:
    for _engine_name in _spec.engine_names:
        ENGINE_TO_PLATFORM[_engine_name] = _spec.key


def spec_for(platform: str) -> PlatformSpec | None:
    return BY_KEY.get(platform)


def _cli_available(cli: str) -> bool:
    try:
        return shutil.which(cli) is not None
    except Exception:
        return False


def classify_static(
    spec: PlatformSpec,
    env: Mapping[str, str] | None = None,
    which: object = None,
) -> str:
    """Classify a platform from the local environment alone (no engine run).

    `env` is os.environ by default; `which` is a shutil.which-like callable
    (injectable for tests). Returns AVAILABLE for a usable configuration and
    the specific root-cause status otherwise (MISSING_CREDENTIALS,
    NOT_INSTALLED, NOT_CONFIGURED, PARTIAL).
    """
    env = os.environ if env is None else env
    which = _cli_available if which is None else which

    creds_present = any(bool(env.get(var)) for var in spec.env)
    if creds_present:
        return AVAILABLE  # a credential path is configured
    if spec.cli and not which(spec.cli):
        if not spec.keyless:
            return NOT_INSTALLED  # required engine CLI is missing
        return PARTIAL  # keyless path exists but external CLI is missing
    if spec.keyless:
        return PARTIAL if spec.partial_default else AVAILABLE
    if spec.env:
        return MISSING_CREDENTIALS  # a credential is declared but not set
    return NOT_CONFIGURED  # no env route and not keyless


def classify_observed(
    spec: PlatformSpec,
    engine_status: str | None,
    env: Mapping[str, str] | None = None,
    which: object = None,
) -> str:
    """Combine an engine-run observation with static capability knowledge.

    engine_status is the raw engine health state (see lib/health.py: "ok",
    "no-results", "partial", "rate-limited", "auth-failed", ...) or None when
    the platform was not attempted this run. Observed outcomes win over static
    guesses; unattempted platforms fall back to classify_static.
    """
    if engine_status is None:
        return classify_static(spec, env=env, which=which)
    status = _ENGINE_STATUS_TO_STATUS.get(engine_status)
    if status is not None:
        return status
    # Unknown/novel engine state -> best static guess.
    return classify_static(spec, env=env, which=which)


def status_rank(status: str) -> int:
    """Order statuses worst->best for table sorting (ERROR first)."""
    return {value: index for index, value in enumerate(STATUSES)}.get(status, len(STATUSES))