from __future__ import annotations

from dataclasses import dataclass


ACTIVE_CATALOG_VERSION = "catalog-v1"


@dataclass(frozen=True)
class CatalogProduct:
    product_id: str
    name: str
    scope: str
    price_cents: int
    delivery_days: int
    revisions: int


@dataclass(frozen=True)
class CatalogSnapshot:
    version: str
    products: tuple[CatalogProduct, ...]

    def get(self, product_id: str) -> CatalogProduct | None:
        return next((item for item in self.products if item.product_id == product_id), None)


def default_catalog() -> CatalogSnapshot:
    """The approved pilot catalog; values are centralized and versioned."""
    return CatalogSnapshot(
        version=ACTIVE_CATALOG_VERSION,
        products=(
            CatalogProduct("site-essencial", "Site Essencial", "até 3 páginas", 99_700, 3, 2),
            CatalogProduct(
                "site-profissional", "Site Profissional", "até 5 páginas", 149_700, 4, 2
            ),
            CatalogProduct("site-avancado", "Site Avançado", "até 8 páginas", 199_700, 7, 2),
            CatalogProduct("site-premium", "Site Premium", "até 12 páginas", 249_700, 8, 2),
            CatalogProduct("landing-page", "Landing Page", "página única", 149_700, 2, 2),
        ),
    )
