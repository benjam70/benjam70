"""Log-template clustering for Coralogix search results.

Free-text keyword search over Coralogix has produced three documented
false positives in real investigations: Revolut+"chargeback" matched
unrelated Stripe records, tabby's capitalization mismatch hid real data,
and Amazon Pay+PSPNotificationHandler matched an internal code-review
bot's log that happened to mention the same class and method names as
example code. In each case the fix was a human noticing the match didn't
actually fit and verifying the underlying field, one case at a time.

This module automates that check. A genuine PSP webhook event recurs
across many orders in a recognizable structural shape (same wording,
different order ID/amount/status); a coincidental keyword hit is usually
a one-off with a completely different shape. Clustering a batch of raw
log message lines by structural template (via the Drain algorithm) turns
"does this look real" into "did this line land in a cluster with other
lines, or is it alone."

It also speeds onboarding a new, not-yet-investigated gateway: instead of
hand-testing field-name guesses one at a time, pull a broad sample of raw
log lines for the new route and mine templates from it directly, seeing
the actual recurring message shapes and their variable fields at once.

Requires the optional ``drain3`` package. Without it, callers should keep
verifying keyword hits against a specific field, the way every false
positive above was actually caught; a missing install is not a data gap.
"""

from __future__ import annotations

from dataclasses import dataclass

# Payment-forensics-specific variable fields, masked before clustering so
# runs differing only by order ID / amount / reference still collapse into
# one template instead of one cluster per order.
_MASKS: tuple[tuple[str, str], ...] = (
    (r"GE\d{8,}[A-Z]{2}", "ORDER_ID"),
    (r"pi_[A-Za-z0-9]+", "STRIPE_REF"),
    (r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "GUID"),
    (r"\b\d{1,3}(?:,\d{3})*\.\d{2}\b", "AMOUNT"),
    (r"\b\d+\b", "NUM"),
)


@dataclass(frozen=True)
class TemplateCluster:
    cluster_id: int
    size: int
    template: str
    example: str
    likely_noise: bool


def _build_miner():
    from drain3 import TemplateMiner
    from drain3.masking import MaskingInstruction
    from drain3.template_miner_config import TemplateMinerConfig

    config = TemplateMinerConfig()
    config.drain_sim_th = 0.4
    config.drain_depth = 4
    config.masking_instructions = [
        MaskingInstruction(pattern, name) for pattern, name in _MASKS
    ]
    return TemplateMiner(config=config)


def mine_templates(
    log_lines: list[str] | tuple[str, ...],
    *,
    noise_size_threshold: int = 1,
) -> tuple[TemplateCluster, ...]:
    """Cluster raw Coralogix log message lines into structural templates.

    log_lines: raw log message text already pulled from Coralogix (the
      free-text message field, not the full JSON row) — this does not
      query Coralogix itself, it only clusters lines you already have.
    noise_size_threshold: a cluster with this many members or fewer is
      flagged `likely_noise`. Default 1: a line with no structural match
      anywhere else in the batch is exactly the shape every documented
      false positive here took, verify it against the actual field
      before treating it as evidence, don't just trust the keyword hit.

    Returns clusters sorted largest first, each with its mined template
    (variable parts masked), one real example line, and a member count.
    """
    try:
        import drain3  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "Install the optional drain3 package to enable template mining"
        ) from exc
    miner = _build_miner()
    examples: dict[int, str] = {}
    for line in log_lines:
        if not line:
            continue
        result = miner.add_log_message(line)
        examples.setdefault(result["cluster_id"], line)
    clusters = tuple(
        TemplateCluster(
            cluster_id=cluster.cluster_id,
            size=cluster.size,
            template=cluster.get_template(),
            example=examples.get(cluster.cluster_id, ""),
            likely_noise=cluster.size <= noise_size_threshold,
        )
        for cluster in miner.drain.clusters
    )
    return tuple(sorted(clusters, key=lambda c: c.size, reverse=True))
