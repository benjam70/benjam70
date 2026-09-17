---
name: thread-context
description: Read a full support ticket or email thread before drafting anything, and build a digest of what's already been established, so replies don't repeat facts, re-ask answered questions, or restate instructions already sent. Use whenever a ticket has more than one message from more than one party, before Mode A/B/C or any reply.
---

# Thread context

A ticket thread is not just the latest message. It's a record of what
multiple people have already said, asked, and answered. Read the whole
thread before drafting anything, not just the most recent entry.

## When to run this

Any time a ticket or email thread has more than one message, and at least
one prior message came from a different party than the one being drafted
for now. A single customer message with no reply yet doesn't need this.
A ticket with an AI bot triage note, an internal comment, and a merchant
reply already in it does.

## Guardrail

Only extract what a message actually says. Don't infer a fact and record
it as established because it seems implied. Don't mark a question as
answered because a later message seems related, it needs to actually
answer it. If a message is ambiguous about whether it settles an earlier
point, treat it as still open rather than guessing it closed. Treating an
inference as established fact is the same failure as inventing one, it
just hides inside a summary instead of a sentence.

## Step 1: build the digest

Walk the thread in chronological order and extract, for each distinct
fact, question, or commitment:

- What was stated, and by whom (customer, internal colleague, merchant,
  automated system note).
- When (the message's own timestamp, not "recently" or "earlier").
- Whether it was ever answered or acted on later in the same thread, and
  if so, by what message.

Keep this as a working list while drafting, not as output. Three columns
worth tracking mentally: Established (facts nobody disputes), Asked (a
question raised, answered or not), Promised (an action someone said would
happen, done or not).

## Step 2: check every draft against the digest

Before finalizing any output (Mode A, Mode B, Mode C, or a plain reply):

- Don't restate a fact a prior message in the same thread already gave,
  reference it in half a sentence if it's still relevant, don't repeat it
  in full.
- Don't ask a question the thread already answered. Check the digest
  first, even if the answer is a few messages back.
- Don't repeat an instruction or ask already sent to the same recipient.
  If Natalie already asked the customer for their membership number, a
  new note doesn't ask for it again, it either notes it's still pending
  or moves on.
- If two messages in the thread contradict each other, that's new
  information worth surfacing, not something to silently pick a side on.

## Step 3: name what's still actually open

After the digest, state in one line what genuinely hasn't been addressed
yet. That's the only part of the thread a new reply needs to focus on.
Everything else is context, not new content.

## Failure mode this prevents

Without this pass, a fresh draft tends to re-derive the whole case from
the ticket's original message, producing a reply that repeats what an
earlier colleague already said, asks a question already answered further
down the thread, or promises an action someone already promised two
messages ago. Reading the full thread once, up front, is cheaper than
each of those mistakes.

## Relationship to payment-forensics

This is a general-purpose thread-reading discipline, not specific to
payments. When payment-forensics is active, it works alongside that
skill's own Mode B/C THREAD DIGEST rule and the mechanical
`payment_forensics.thread_digest` gate: you can't know what's already
been said without having read the whole thread first, and HybridEngine
rejects Mode B/C drafts that restate already-told recipient facts when
thread history is supplied.
