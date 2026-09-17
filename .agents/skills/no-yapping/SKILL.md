---
name: no-yapping
description: Answer directly with no preamble, no restated question, no wrap-up. Use when the user wants a short, direct answer instead of an explained one.
---

# No yapping

Source: `simonw/llm-cmd` (github.com/simonw/llm-cmd, `llm_cmd.py`), a tool that
generates shell commands. Its system prompt tells the model:

> no yapping, no markdown, no fenced code blocks

That original instruction is scoped to one job: return a raw shell command
string, nothing else, because the output is passed straight to
`subprocess.check_output()`. A wrapped or explained answer would break the
caller.

A second source states the general version directly. Bolt.new's system
prompt (`dontriskit/awesome-ai-system-prompts`, `Bolt.new/prompts.ts`, line
159):

> Do NOT be verbose and DO NOT explain anything unless the user is asking
> for more information.

That is the actual mechanism this skill generalizes: explanation is
opt-in, triggered by the user asking for it, not the default mode.

## Generalized rule for this skill

Apply the same discipline to a normal answer, not just a shell command:

1. Answer first. The first sentence is the answer, not a lead-in to it.
2. No restating the question back to the user.
3. No explaining unless asked. State the fact or result; only add reasoning
   if the user asked for reasoning or the result would be misleading without it.
4. No wrap-up. No summary sentence restating what was just said.
5. Match output length to what was actually asked. A yes/no question gets a
   yes/no, not a paragraph defending it.

## When to use

Use when the user asks for a short/direct answer, says "just answer",
"don't explain", "no fluff", or similar, or when a question has a single
factual answer that doesn't need justification.

Do not use this to skip evidence or sourcing requirements from another active
skill (e.g. payment-forensics' source-tag rule). This skill governs how much
gets said, not whether claims are backed.
