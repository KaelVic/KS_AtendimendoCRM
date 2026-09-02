from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PaymentLink:
    product_id: str
    amount_cents: int
    url: str


@dataclass(frozen=True)
class PaymentLinkAllowlist:
    version: str | None
    links: tuple[PaymentLink, ...]

    def resolve(self, product_id: str, amount_cents: int) -> PaymentLink | None:
        return next(
            (
                link
                for link in self.links
                if link.product_id == product_id and link.amount_cents == amount_cents
            ),
            None,
        )

    def contains(self, url: str) -> bool:
        return any(link.url == url for link in self.links)

    @classmethod
    def from_json(cls, version: str | None, raw: str) -> "PaymentLinkAllowlist":
        try:
            values: Any = json.loads(raw or "[]")
        except json.JSONDecodeError as exc:
            raise ValueError("PAYMENT_LINK_ALLOWLIST_JSON inválido") from exc
        if not isinstance(values, list):
            raise ValueError("PAYMENT_LINK_ALLOWLIST_JSON deve ser uma lista")
        if values and not version:
            raise ValueError("allowlist de pagamento exige versão")
        links: list[PaymentLink] = []
        keys: set[tuple[str, int]] = set()
        for value in values:
            if not isinstance(value, dict):
                raise ValueError("entrada de allowlist inválida")
            product_id = value.get("product_id")
            amount_cents = value.get("amount_cents")
            url = value.get("url")
            if (
                not isinstance(product_id, str)
                or not isinstance(amount_cents, int)
                or amount_cents <= 0
                or not isinstance(url, str)
                or not url.startswith("https://")
            ):
                raise ValueError("entrada de allowlist inválida")
            key = (product_id, amount_cents)
            if key in keys:
                raise ValueError("allowlist de pagamento ambígua")
            keys.add(key)
            links.append(PaymentLink(product_id, amount_cents, url))
        return cls(version or None, tuple(links))
