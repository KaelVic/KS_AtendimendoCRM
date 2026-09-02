"""Versioned catalog and deterministic proposal generation."""

from .catalog import CatalogSnapshot, default_catalog
from .contracts import ProposalDraft, ProposalLineDraft
from .validation import HUMAN_APPROVAL_REQUIRED, validate_draft

__all__ = [
    "CatalogSnapshot",
    "HUMAN_APPROVAL_REQUIRED",
    "ProposalDraft",
    "ProposalLineDraft",
    "default_catalog",
    "validate_draft",
]
