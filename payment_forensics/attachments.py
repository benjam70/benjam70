"""Deterministic intake and evidence extraction for case attachments."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import zlib
from typing import Any, Mapping

from .controller import EvidenceItem


@dataclass(frozen=True)
class AttachmentInput:
    name: str
    path: str | None = None
    text: str | None = None
    media_type: str | None = None


@dataclass(frozen=True)
class AttachmentRecord:
    name: str
    media_type: str | None
    sha256: str | None
    status: str
    text: str = ""
    error: str | None = None
    facts: tuple[EvidenceItem, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "media_type": self.media_type, "sha256": self.sha256,
                "status": self.status, "text": self.text, "error": self.error,
                "facts": [fact.__dict__ for fact in self.facts]}


def normalize_attachment(value: AttachmentInput | Mapping[str, Any] | str) -> AttachmentInput:
    if isinstance(value, AttachmentInput):
        return value
    if isinstance(value, str):
        return AttachmentInput(name=Path(value).name, path=value)
    if isinstance(value, Mapping):
        path = value.get("path")
        return AttachmentInput(name=str(value.get("name") or (Path(str(path)).name if path else "attachment")),
                               path=str(path) if path else None,
                               text=str(value["text"]) if value.get("text") is not None else None,
                               media_type=str(value["media_type"]) if value.get("media_type") else None)
    raise TypeError("attachment must be a path, mapping, or AttachmentInput")


def inspect_attachment(value: AttachmentInput | Mapping[str, Any] | str, *, case_input: str = "") -> AttachmentRecord:
    attachment = normalize_attachment(value)
    try:
        if attachment.text is not None:
            raw, text = attachment.text.encode("utf-8"), attachment.text
        elif attachment.path:
            path = Path(attachment.path)
            raw = path.read_bytes()
            text = _extract_text(path, raw)
        else:
            raise ValueError("attachment has neither text nor path")
        if not text.strip():
            raise ValueError("no text could be extracted; OCR or visual review is required")
        facts = extract_attachment_facts(attachment.name, text, case_input=case_input)
        return AttachmentRecord(attachment.name, attachment.media_type, sha256(raw).hexdigest(), "INSPECTED", text, facts=facts)
    except Exception as exc:
        return AttachmentRecord(attachment.name, attachment.media_type, None, "FAILED", error=f"{type(exc).__name__}: {exc}")


def _extract_text(path: Path, raw: bytes) -> str:
    if path.suffix.casefold() in {".txt", ".md", ".csv", ".json", ".log"}:
        return raw.decode("utf-8", errors="replace")
    if path.suffix.casefold() != ".pdf":
        raise ValueError(f"unsupported attachment type: {path.suffix or 'unknown'}")
    try:
        from pypdf import PdfReader  # type: ignore
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    except ImportError:
        return _extract_pdf_literal_strings(raw)


def _extract_pdf_literal_strings(raw: bytes) -> str:
    streams = [raw]
    for match in re.finditer(rb"stream\r?\n", raw):
        end = raw.find(b"endstream", match.end())
        if end >= 0:
            try:
                streams.append(zlib.decompress(raw[match.end():end]))
            except zlib.error:
                pass
    strings = []
    for stream in streams:
        for match in re.finditer(rb"\(([^()]*(?:\\.[^()]*)*)\)\s*(?:Tj|')", stream):
            value = re.sub(rb"\\([()\\])", rb"\1", match.group(1))
            value = value.replace(rb"\\n", b"\n").replace(rb"\\r", b"\r")
            strings.append(value.decode("utf-8", errors="replace"))
    if not strings:
        raise ValueError("PDF text extraction unavailable or document is image-only")
    return " ".join(strings)


def extract_attachment_facts(name: str, text: str, *, case_input: str = "") -> tuple[EvidenceItem, ...]:
    combined = f"{case_input}\n{text}"
    arn = re.search(r"\b(?:refund\s+arn|arn)\s*[:#-]?\s*(\d{20,})", text, re.I)
    amount = re.search(r"(?:refund amount|total refund|refund)\s*[:#-]?\s*(?:EUR|€)\s*([0-9]+(?:[.,][0-9]{2}))", text, re.I)
    date = re.search(r"(?:refund date|date)\s*[:#-]?\s*(\d{4}-\d{2}-\d{2})", text, re.I)
    refund = re.search(r"refund (?:adyen )?reference\s*[:#-]?\s*([A-Z0-9]{8,})", text, re.I)
    original = re.search(r"adyen reference\s*[:#-]?\s*([A-Z0-9]{8,})", text, re.I)
    order = re.search(r"\bGE\d{8,}[A-Z]{2}\b", combined, re.I)
    return (EvidenceItem(source=f"Attachment: {name}", source_type="document", event_type="REFUND",
        status="COMPLETED", amount=amount.group(1).replace(",", ".") if amount else None,
        currency="EUR" if amount else None, timestamp=date.group(1) if date else None,
        order_id=order.group(0) if order else None, refund_id=refund.group(1) if refund else None,
        psp_reference=original.group(1) if original else None, arn=arn.group(1) if arn else None,
        raw_fact=text[:4000], evidence_role="document"),)


_ADMIN_AMOUNT = re.compile(r"(?:(?:EUR|USD|GBP|ILS|SAR|AED|€|\$|£|₪)\s*)?([0-9]+(?:[.,][0-9]{2}))")
_ADMIN_ID = re.compile(r"(?i)\b(refund|transaction|payment|psp)\s*(?:id|reference)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9_-]{5,})")


def extract_admin_capture_facts(text: str) -> tuple[EvidenceItem, ...]:
    """Extract auditable lifecycle facts from pasted Global-e Admin text.

    The original capture is never changed.  Only lines containing payment
    lifecycle language and a monetary amount become facts; ambiguous lines
    remain available to the model as raw case input for review.
    """
    order_match = re.search(r"\bGE\d{8,}[A-Z]{2}\b", text, re.I)
    order_id = order_match.group(0) if order_match else None
    facts: list[EvidenceItem] = []
    for line in text.splitlines():
        cleaned = " ".join(line.split())
        lowered = cleaned.casefold()
        if not cleaned or not re.search(r"refund|capture|authori[sz]|settle|payment", lowered):
            continue
        amount_match = _ADMIN_AMOUNT.search(cleaned)
        ids = {kind.casefold(): value for kind, value in _ADMIN_ID.findall(cleaned)}
        if not amount_match and not ids:
            continue
        if re.search(r"refund", lowered):
            event_type = "REFUND"
        elif re.search(r"capture", lowered):
            event_type = "CAPTURE"
        elif re.search(r"authori[sz]", lowered):
            event_type = "AUTHORISATION"
        elif re.search(r"settle", lowered):
            event_type = "SETTLEMENT"
        else:
            event_type = "PAYMENT"
        if re.search(r"failed|rejected|refused|error|declined", lowered):
            status = "FAILED"
        elif re.search(r"refund(?:ed)?|completed|captured|settled|authori[sz]ed|success", lowered):
            status = "COMPLETED"
        else:
            status = "UNKNOWN"
        currency_match = re.search(r"(?i)\b(EUR|USD|GBP|ILS|SAR|AED)\b|[€$£₪]", cleaned)
        symbol = currency_match.group(0) if currency_match else ""
        currency = {"€": "EUR", "$": "USD", "£": "GBP", "₪": "ILS"}.get(symbol, symbol.upper() or None)
        component = "gift_card" if re.search(r"gift[ -]?card", lowered) else ("card" if re.search(r"\bcard\b", lowered) else None)
        date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2}(?:[T ][0-9:.+-]+)?|\d{2}[/-]\d{2}[/-]20\d{2})\b", cleaned)
        facts.append(EvidenceItem(
            source="Admin capture", source_type="admin_capture", event_type=event_type,
            status=status, amount=amount_match.group(1).replace(",", ".") if amount_match else None, currency=currency,
            timestamp=date_match.group(1) if date_match else None, order_id=order_id,
            refund_id=ids.get("refund"), payment_id=ids.get("payment"),
            psp_reference=ids.get("psp") or ids.get("transaction"), raw_fact=cleaned,
            evidence_role="admin_capture", component=component,
        ))
    return tuple(facts)
