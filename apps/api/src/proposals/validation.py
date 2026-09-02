from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .catalog import CatalogProduct, CatalogSnapshot
from .contracts import ProposalDraft

HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"


@dataclass(frozen=True)
class ValidatedProposal:
    status: str
    approval_reasons: tuple[str, ...]
    catalog_version: str
    total_cents: int
    delivery_days: int | None
    revisions: int | None
    primary_product: CatalogProduct | None
    lines: tuple[dict[str, Any], ...]
    canonical_data: dict[str, Any]

    @property
    def renderable(self) -> bool:
        return self.status == "READY" and self.primary_product is not None


def validate_draft(draft: ProposalDraft, catalog: CatalogSnapshot) -> ValidatedProposal:
    reasons: list[str] = []
    primary = catalog.get(draft.product_id)
    if primary is None:
        reasons.append("PRODUCT_NOT_IN_ACTIVE_CATALOG")

    lines: list[dict[str, Any]] = []
    total = 0
    line_by_product: dict[str, dict[str, Any]] = {}
    for line in draft.items:
        product = catalog.get(line.product_id)
        if product is None:
            reasons.append(f"ITEM_NOT_IN_ACTIVE_CATALOG:{line.product_id}")
            continue
        current = line_by_product.get(product.product_id)
        if current is None:
            current = {
                "product_id": product.product_id,
                "product_name": product.name,
                "scope": product.scope,
                "quantity": 0,
                "unit_price_cents": product.price_cents,
                "line_total_cents": 0,
            }
            line_by_product[product.product_id] = current
            lines.append(current)
        current["quantity"] += line.quantity
        current["line_total_cents"] += product.price_cents * line.quantity
        total += product.price_cents * line.quantity

    if primary is not None:
        if draft.price_cents != total:
            reasons.append("PRICE_MISMATCH")
        if draft.delivery_days != primary.delivery_days:
            reasons.append("DELIVERY_DAYS_MISMATCH")
        if draft.revisions != primary.revisions:
            reasons.append("REVISIONS_MISMATCH")
        if draft.scope != primary.scope:
            reasons.append("SCOPE_MISMATCH")
        if draft.discount_cents:
            reasons.append("DISCOUNT_REQUIRES_APPROVAL")
        if draft.additional_scope:
            reasons.append("ADDITIONAL_SCOPE_REQUIRES_APPROVAL")
        if any(line.product_id != primary.product_id for line in draft.items):
            reasons.append("MULTIPLE_PRODUCTS_REQUIRE_APPROVAL")
        if len(draft.items) != len(line_by_product):
            reasons.append("DUPLICATE_PRODUCT_LINES_REQUIRE_APPROVAL")

    canonical = {
        "customer": draft.customer,
        "need": draft.need,
        "product_id": primary.product_id if primary else draft.product_id,
        "items": lines,
        "price_cents": total,
        "delivery_days": primary.delivery_days if primary else None,
        "revisions": primary.revisions if primary else None,
        "scope": primary.scope if primary else draft.scope,
        "observations": list(draft.observations),
        "discount_cents": draft.discount_cents,
        "additional_scope": draft.additional_scope,
        "catalog_version": catalog.version,
    }
    return ValidatedProposal(
        status="READY" if not reasons else HUMAN_APPROVAL_REQUIRED,
        approval_reasons=tuple(dict.fromkeys(reasons)),
        catalog_version=catalog.version,
        total_cents=total,
        delivery_days=primary.delivery_days if primary else None,
        revisions=primary.revisions if primary else None,
        primary_product=primary,
        lines=tuple(lines),
        canonical_data=canonical,
    )
