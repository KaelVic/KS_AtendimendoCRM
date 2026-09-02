from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import date


TEMPLATE_VERSION = "proposal-template-v1"


@dataclass(frozen=True)
class ProposalRenderData:
    customer: str
    need: str
    product_name: str
    scope: str
    total_cents: int
    delivery_days: int
    revisions: int
    observations: tuple[str, ...]
    catalog_version: str
    generated_on: date


def _ascii(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def _pdf_escape(value: str) -> str:
    return _ascii(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class ProposalPdfRenderer:
    """Minimal deterministic PDF renderer; only server-derived values enter it."""

    def render(self, data: ProposalRenderData) -> bytes:
        price = (
            f"R$ {data.total_cents / 100:,.2f}".replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )
        lines = [
            "KaelSolutions",
            "PROPOSTA COMERCIAL",
            f"Cliente: {data.customer}",
            f"Necessidade: {data.need}",
            f"Produto: {data.product_name}",
            f"Escopo: {data.scope}",
            f"Investimento: {price}",
            f"Prazo: {data.delivery_days} dias uteis",
            f"Revisoes: {data.revisions}",
            f"Catalogo: {data.catalog_version}",
            f"Data: {data.generated_on.isoformat()}",
        ] + [f"Observacao: {item}" for item in data.observations]
        stream_lines = ["BT", "/F1 12 Tf", "50 790 Td"]
        for index, line in enumerate(lines):
            if index:
                stream_lines.append("0 -24 Td")
            stream_lines.append(f"({_pdf_escape(line)}) Tj")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("ascii")

        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        ]
        output = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for number, obj in enumerate(objects, start=1):
            offsets.append(len(output))
            output.extend(f"{number} 0 obj\n".encode("ascii"))
            output.extend(obj)
            output.extend(b"\nendobj\n")
        xref = len(output)
        output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        output.extend(
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
                "ascii"
            )
        )
        return bytes(output)

    @staticmethod
    def sha256(pdf: bytes) -> str:
        return hashlib.sha256(pdf).hexdigest()
