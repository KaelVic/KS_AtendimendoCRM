"""Low-cardinality metrics and safe request correlation helpers.

This intentionally avoids recording message bodies, addresses, tokens, IDs of
contacts or arbitrary user input. The registry is process-local; production
scraping can aggregate one endpoint per process without adding a new service.
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict, deque
from collections.abc import Mapping


LabelSet = tuple[tuple[str, str], ...]


def _labels(labels: Mapping[str, object] | None) -> LabelSet:
    if not labels:
        return ()
    # Callers must use bounded enums/numbers, never request data. Truncation is
    # a last-resort guard against accidentally creating unbounded cardinality.
    return tuple(sorted((str(key), str(value)[:64]) for key, value in labels.items()))


def _format_labels(labels: LabelSet) -> str:
    if not labels:
        return ""
    rendered = []
    for key, value in labels:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        rendered.append(f'{key}="{escaped}"')
    return "{" + ",".join(rendered) + "}"


class MetricsRegistry:
    def __init__(self, *, sample_limit: int = 1000) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, LabelSet], float] = defaultdict(float)
        self._gauges: dict[tuple[str, LabelSet], float] = {}
        self._samples: dict[tuple[str, LabelSet], deque[float]] = defaultdict(
            lambda: deque(maxlen=sample_limit)
        )

    def inc(
        self, name: str, value: float = 1, *, labels: Mapping[str, object] | None = None
    ) -> None:
        with self._lock:
            self._counters[(name, _labels(labels))] += value

    def set_gauge(
        self, name: str, value: float, *, labels: Mapping[str, object] | None = None
    ) -> None:
        with self._lock:
            self._gauges[(name, _labels(labels))] = value

    def get_gauge(
        self, name: str, *, labels: Mapping[str, object] | None = None
    ) -> float | None:
        with self._lock:
            return self._gauges.get((name, _labels(labels)))

    def observe_latency(
        self, operation: str, latency_ms: float, *, labels: Mapping[str, object] | None = None
    ) -> None:
        if not math.isfinite(latency_ms) or latency_ms < 0:
            return
        merged = {"operation": operation, **(labels or {})}
        with self._lock:
            self._samples[("ks_operation_latency_ms", _labels(merged))].append(latency_ms)

    @staticmethod
    def _quantile(values: list[float], quantile: float) -> float:
        if not values:
            return 0.0
        values.sort()
        index = max(0, min(len(values) - 1, math.ceil(quantile * len(values)) - 1))
        return values[index]

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            samples = {key: list(value) for key, value in self._samples.items()}

        for (name, labels), value in sorted(counters.items()):
            lines.append(f"{name}{_format_labels(labels)} {value:g}")
        for (name, labels), value in sorted(gauges.items()):
            lines.append(f"{name}{_format_labels(labels)} {value:g}")
        for (name, labels), values in sorted(samples.items()):
            for suffix, quantile in (("p50", 0.50), ("p95", 0.95)):
                lines.append(
                    f"{name}_{suffix}{_format_labels(labels)} "
                    f"{self._quantile(values, quantile):g}"
                )
        return "\n".join(lines) + ("\n" if lines else "")

    def reset(self) -> None:
        # Test-only utility; production code never calls this.
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._samples.clear()


metrics = MetricsRegistry()


def record_component(component: str, healthy: bool, latency_ms: float | None = None) -> None:
    metrics.set_gauge(
        "ks_component_status",
        1 if healthy else 0,
        labels={"component": component},
    )
    if latency_ms is not None:
        metrics.observe_latency(component, latency_ms)


def record_integration(component: str, outcome: str, latency_ms: float | None = None) -> None:
    metrics.inc("ks_integration_calls_total", labels={"component": component, "outcome": outcome})
    if latency_ms is not None:
        metrics.observe_latency(component, latency_ms)


def record_tool_result(tool: str, success: bool) -> None:
    # `tool` is a registry name, never a model-supplied free-form argument.
    metrics.inc("ks_tool_success_total", labels={"tool": tool, "success": str(success).lower()})
