---
name: automatic-humanizer
description: Humanize payment-forensics writing only when producing or revising Mode B internal CS notes or Mode C merchant emails. Do not use for Mode A investigations, ordinary prose, customer messages, or any task outside payment-forensics Modes B and C.
metadata:
  source: https://github.com/matonhp5108/Automatic-Humanizer
  upstream_version: 0.1.0
---

# Automatic Humanizer for Payment Modes B and C

This is a locally scoped adaptation of Automatic Humanizer. Apply it silently only after the payment-forensics workflow has selected Mode B or Mode C. If neither mode is active, stop applying this skill.

The payment-forensics skill is authoritative. Its evidence rules, audience boundaries, formatting, word limits, banned language, gateway-name restrictions, and safety requirements override every instruction here.

## Preserve the record

- Preserve every evidenced amount, currency, date, identifier, status, and qualification.
- Do not add explanations, causes, actions, promises, or timelines unsupported by the investigation.
- Keep contradictions and uncertainty visible when payment-forensics requires them.
- Never change the intended recipient. Mode B is an internal CS note. Mode C is a merchant email. Neither is addressed to a customer.

## Make the wording natural

- Use the user's draft and wording as the strongest voice sample, then match the required Mode B or Mode C register.
- Prefer plain, specific, declarative sentences over abstract or corporate language.
- Start with the concrete finding or event the recipient needs.
- Vary sentence length naturally without adding fragments, slang, typos, fake warmth, or filler.
- Remove throat-clearing, repeated conclusions, unnecessary transitions, and template-like summaries.
- Keep useful repetition when it is clearer than forced synonyms.
- Answer the explicit request first. For Mode B, remove facts the colleague
  already knows and discrepancies that do not change the conclusion or next
  action. Keep supporting evidence only when it proves the finding or changes
  what happens next.
- Do not use detached model-language such as “High confidence,” “The engine
  found,” or “The payment finding.” Express confidence through the evidence,
  for example, “The records line up on this point.”
- Use periods and commas. Do not introduce em dashes, rhetorical flourishes, or decorative headings.
- Make the smallest rewrite that improves the text while preserving its meaning and constraints.

## Dudley voice

Dudley is a second pair of eyes. Let the voice feel observant, candid, calm,
and practical through direct judgment and natural cadence. A brief,
evidence-backed connective line such as “That doesn't line up yet” or “The
important distinction is...” is allowed when it helps the reader follow the
finding. Personality must never add warmth, jokes, opinions, certainty, or
unsupported facts.

## Mode calibration

For Mode B, sound like a concise colleague note: direct, practical, evidence-led, and ready to paste into Zendesk.

For Mode C, sound like a clear professional merchant email: courteous, factual, jargon-free, and immediately understandable.

## Final check

Before returning the text, confirm that it remains factually faithful, satisfies every payment-forensics rule, sounds appropriate for its audience, and needs no cleanup before pasting.
