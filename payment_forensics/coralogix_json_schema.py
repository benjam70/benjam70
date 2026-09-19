"""JSON schema inference across a batch of raw Coralogix PSP payloads.

Several gateways here (Stripe, Checkout.com, PayJustNow) log the full raw
webhook JSON body, and the documented method for understanding a new or
not-yet-investigated gateway has so far been reading a handful of pasted
examples by hand: which fields exist, which only show up on certain event
types (a refund confirmation carrying `refundAmount` that an auth
confirmation never does), which fields are always present.

This module automates that read. Given a batch of raw JSON payloads
already pulled from Coralogix (the parsed log body, not the message
text, see `coralogix_templates.py` for that), it merges them into one
JSON Schema via GenSON and separates fields that are present in every
sample from fields that only show up on some of them, the same
"always-present vs event-specific" distinction that's been worked out by
hand for gateways like PayJustNow (`checkoutPaymentStatus`,
`paymentReference` always present; `refundAmount`/`refundReason` only on
a refund event).

Requires the optional ``genson`` package. Without it, callers should keep
reading sample payloads by hand, the way every gateway documented so far
was actually investigated; a missing install is not a data gap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSummary:
    name: str
    types: tuple[str, ...]
    always_present: bool
    example: object


def _coerce_to_dict(payload: dict | str) -> dict | None:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return obj if isinstance(obj, dict) else None
    return None


def infer_schema(
    payloads: list[dict | str] | tuple[dict | str, ...],
    *,
    sample_limit: int = 50,
) -> dict:
    """Merge a batch of raw JSON payloads into one JSON Schema.

    payloads: raw payloads already pulled from Coralogix, as parsed dicts
      or JSON text. Non-dict / unparseable entries are skipped, not
      errored on, real Coralogix rows often include noise alongside real
      hits.
    sample_limit: max payloads to feed in (default 50), GenSON's merge
      cost grows with sample count and this is meant for a quick shape
      check, not exhaustively schema-fitting every row in a case.

    Returns {"schema": <JSON Schema dict>, "sample_count": N}, or
    {"schema": None, "sample_count": 0} if nothing parsed as an object.
    """
    try:
        from genson import SchemaBuilder
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "Install the optional genson package to enable JSON schema inference"
        ) from exc
    builder = SchemaBuilder()
    parsed = 0
    for payload in list(payloads)[:sample_limit]:
        obj = _coerce_to_dict(payload)
        if obj is None:
            continue
        builder.add_object(obj)
        parsed += 1
    if parsed == 0:
        return {"schema": None, "sample_count": 0}
    return {"schema": builder.to_schema(), "sample_count": parsed}


def summarize_fields(
    payloads: list[dict | str] | tuple[dict | str, ...],
    *,
    sample_limit: int = 50,
) -> tuple[FieldSummary, ...]:
    """Summarize top-level fields as always-present vs event-specific.

    This is the direct answer to "what does this gateway's payload
    actually look like": one field list, each marked whether it showed
    up in every sample or only some, with a real example value, instead
    of reading the merged schema's `required` array by hand.
    """
    objects = [obj for obj in (_coerce_to_dict(p) for p in list(payloads)[:sample_limit]) if obj is not None]
    if not objects:
        return ()
    result = infer_schema(objects, sample_limit=sample_limit)
    schema = result["schema"]
    if not schema:
        return ()
    properties = schema.get("properties", {})
    required = set(schema.get("required", ()))
    summaries = []
    for name, prop_schema in properties.items():
        prop_type = prop_schema.get("type", "unknown")
        types = tuple(prop_type) if isinstance(prop_type, list) else (prop_type,)
        example = next((obj[name] for obj in objects if name in obj), None)
        summaries.append(
            FieldSummary(
                name=name,
                types=types,
                always_present=name in required,
                example=example,
            )
        )
    return tuple(sorted(summaries, key=lambda f: (not f.always_present, f.name)))
