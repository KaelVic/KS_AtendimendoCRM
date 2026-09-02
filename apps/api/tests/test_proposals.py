from datetime import date

import pytest
from pydantic import ValidationError

from src.proposals.catalog import default_catalog
from src.proposals.contracts import ProposalDraft, ProposalLineDraft
from src.proposals.renderer import ProposalPdfRenderer, ProposalRenderData
from src.proposals.validation import HUMAN_APPROVAL_REQUIRED, validate_draft


def valid_draft() -> ProposalDraft:
    return ProposalDraft(
        customer="Clínica Exemplo",
        need="Apresentar serviços com clareza e captar pedidos de orçamento.",
        product_id="site-essencial",
        items=[ProposalLineDraft(product_id="site-essencial", quantity=1)],
        price_cents=99700,
        delivery_days=3,
        revisions=2,
        scope="até 3 páginas",
        observations=["Duas rodadas de revisão."],
    )


def test_valid_draft_uses_only_the_active_catalog_values():
    result = validate_draft(valid_draft(), default_catalog())

    assert result.status == "READY"
    assert result.total_cents == 99700
    assert result.catalog_version == "catalog-v1"


@pytest.mark.parametrize(
    "field,value",
    [("price_cents", 1), ("delivery_days", 99), ("revisions", 8), ("scope", "escopo inventado")],
)
def test_adultered_catalog_value_requires_human_approval(field, value):
    draft = valid_draft().model_copy(update={field: value})

    result = validate_draft(draft, default_catalog())

    assert result.status == HUMAN_APPROVAL_REQUIRED
    assert result.approval_reasons


def test_unknown_product_and_discount_never_become_a_renderable_proposal():
    draft = valid_draft().model_copy(
        update={
            "product_id": "made-up-product",
            "items": [ProposalLineDraft(product_id="made-up-product", quantity=1)],
        }
    )

    result = validate_draft(draft, default_catalog())

    assert result.status == HUMAN_APPROVAL_REQUIRED
    assert result.renderable is False


def test_missing_required_field_is_rejected_before_rendering():
    with pytest.raises(ValidationError):
        ProposalDraft.model_validate(valid_draft().model_dump(exclude={"price_cents"}))


def test_pdf_renderer_is_deterministic_and_has_a_golden_hash():
    data = ProposalRenderData(
        customer="Clínica Exemplo",
        need="Apresentar serviços com clareza e captar pedidos de orçamento.",
        product_name="Site Essencial",
        scope="até 3 páginas",
        total_cents=99700,
        delivery_days=3,
        revisions=2,
        observations=("Duas rodadas de revisão.",),
        catalog_version="catalog-v1",
        generated_on=date(2026, 8, 31),
    )
    renderer = ProposalPdfRenderer()

    first = renderer.render(data)
    second = renderer.render(data)

    assert first == second
    assert first.startswith(b"%PDF-1.4")
    assert renderer.sha256(first) == "52a489147dfcc57593f5041178316d39cbe23a53d380fc7d0c2f6f1a14a82b06"
