from __future__ import annotations

from typing import Callable, Iterator

from social_base import SOURCES, CollectorError, SocialCollector

CollectorFactory = Callable[..., SocialCollector]


class RegistryError(CollectorError):
    """A collector could not be registered or created."""


class UnknownSourceError(RegistryError):
    """No collector is registered for the requested source."""


class CollectorRegistry:
    """Maps schema `source` -> collector factory."""

    def __init__(self) -> None:
        self._factories: dict[str, CollectorFactory] = {}

    def register(self, source: str, factory: CollectorFactory) -> None:
        if not source or not isinstance(source, str):
            raise RegistryError(f"invalid source name: {source!r}")
        if source not in SOURCES:
            raise RegistryError(f"source {source!r} is not a known schema source")
        if not callable(factory):
            raise RegistryError(f"factory for {source!r} is not callable")
        self._factories[source] = factory

    def unregister(self, source: str) -> None:
        if source in self._factories:
            del self._factories[source]

    def sources(self) -> list[str]:
        return sorted(self._factories)

    def create(self, source: str, **kwargs: object) -> SocialCollector:
        """Instantiate a collector for `source`, passing kwargs to its factory."""
        factory = self._factories.get(source)
        if factory is None:
            raise UnknownSourceError(f"no collector registered for source {source!r}")
        try:
            collector = factory(**kwargs)
        except TypeError as exc:
            raise RegistryError(
                f"factory for {source!r} rejected kwargs {tuple(kwargs)}: {exc}"
            ) from exc
        if not isinstance(collector, SocialCollector):
            raise RegistryError(
                f"factory for {source!r} returned {type(collector).__name__}, "
                "not a SocialCollector"
            )
        if collector.source != source:
            raise RegistryError(
                f"factory for {source!r} returned a collector with "
                f"source {collector.source!r}"
            )
        return collector

    def __contains__(self, source: str) -> bool:
        return source in self._factories

    def __len__(self) -> int:
        return len(self._factories)

    def __iter__(self) -> Iterator[str]:
        return iter(self.sources())


_DEFAULT = CollectorRegistry()


def default_registry() -> CollectorRegistry:
    """Return the process-wide registry."""
    return _DEFAULT


def register_default_collectors(
    registry: CollectorRegistry | None = None,
) -> CollectorRegistry:
    """Register all in-tree collectors. Import is deferred to avoid cycles.

    Returns the registry that was populated.
    """
    reg = registry or _DEFAULT
    try:
        from .last30days_adapter import Last30daysAdapter
    except ImportError:
        from last30days_adapter import Last30daysAdapter
    reg.register(Last30daysAdapter.source, Last30daysAdapter)
    try:
        from .rss_adapter import RssAdapter
        from .telegram_adapter import TelegramAdapter
    except ImportError:
        from rss_adapter import RssAdapter
        from telegram_adapter import TelegramAdapter
    reg.register(RssAdapter.source, RssAdapter)
    reg.register(TelegramAdapter.source, TelegramAdapter)
    return reg
