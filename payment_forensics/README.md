# Hybrid engine integration

`HybridEngine` is the orchestration entry point. It does not create credentials or bypass the existing MCP servers.

Provide two application-owned adapters:

```python
from payment_forensics import HybridEngine, JsonProposalModel, RegistrySearchExecutor

model = JsonProposalModel(llm_client.propose_json, llm_client.render)
tools = RegistrySearchExecutor({
    "Gateway": gateway_mcp_search,
    "Admin": admin_mcp_search,
    "Coralogix": coralogix_mcp_search,
})
result = HybridEngine(model, tools).investigate(case_text)
```

For a live OpenAI Responses API model, use `OpenAIResponsesModel`. It uses
strict JSON Schema output for proposals, `OPENAI_API_KEY` for authentication,
and `OPENAI_MODEL` for deployment selection. For existing stdio MCP servers,
use `MCPStdioSearchExecutor` with one `MCPServerSpec` per source and an
explicit normalizer for that source's existing response shape.

The CLI fails closed unless an adapter module is supplied:

```text
python dudley_engine.py case.txt --adapter-module my_dudley_adapters
```

`my_dudley_adapters.build_search_executor()` must return a
`MCPStdioSearchExecutor` or `RegistrySearchExecutor`. This keeps the MCP
server process, credentials, and provider-specific parsing in the host
application rather than guessing them in the forensic controller.

Each search handler must return a `ToolResult` with correctly scoped facts. The existing MCP client owns transport, authentication, provider-specific request shape, and source priority. Handler failures are converted into `FAILED` results and cannot satisfy the completion gate.

## Optional semantic retrieval

The repository includes an optional Hugging Face retrieval layer. Install
`retrieval-requirements.txt` only in an environment intended to host local ML
models. `BGEEmbedder.from_pretrained()` loads `BAAI/bge-m3` for hybrid lexical
and dense candidate retrieval, while `BGEReranker.from_pretrained()` loads
`BAAI/bge-reranker-v2-m3` to rerank candidates. Both load from the local
Hugging Face cache by default and do not contact the network. Pass
`offline=False` only when explicitly provisioning a new model version.

Use semantic retrieval only for candidate discovery or ordering. Wrap an
existing executor with `RerankingSearchExecutor` if its normalizer already
returns multiple case-scoped facts. The wrapper does not filter, alter source
coverage, or admit facts that have not passed the existing controller gates.

The CLI exposes this safely as an opt-in flag:

```text
python dudley_engine.py case.txt --adapter-module my_dudley_adapters --bge-rerank
```

The LLM proposal is a JSON object with `searches`, `relevant_sources`, `identity_established`, `lifecycle_checked`, `terminal_state`, `fact_ids`, and `complete` fields. The controller ignores completion claims when its gate rejects them.

## Deterministic investigation controls

Payment movement can also be represented with `PaymentEvent` objects and checked
with `reconcile_events`. The ledger performs authorization, capture, settlement,
and refund arithmetic outside the model. In particular, an authorized amount
that exceeds a fully refunded capture is classified as
`UNCAPTURED_AUTHORIZATION`, not as a missing refund.

Each controller snapshot records the current investigation phase, phase history,
and ordered event log. Completed and blocked audit records include a
`replay_hash` over the case state, gate, proposal outcome, and rendered output.
These fields make repeated runs easier to compare and expose drift without
changing the existing model adapter contract.

External case content is screened by `security.py` for instruction-like text.
The text is preserved, but findings are surfaced as untrusted content so the
model can treat it as evidence rather than executable direction. Run telemetry
is available as structured dictionaries and can be exported as NDJSON; query
contents are represented by hashes.

`request_understanding.py` separately extracts multi-intent ticket requests,
requested artifacts, conversation acts, known identifiers, and open questions.
Mode B/C drafts are rejected when they omit an explicitly requested ARN,
refund-proof reference, refund status, or explanation.
The understanding record also keeps separate `already_known`,
`explicitly_requested`, and `still_unanswered` lists, plus amount, date,
refund-ID, ARN, and order-ID slots. Optional thread history preserves the
original intent while allowing the current turn to be reclassified.

## Drift and humanization controls

`validate_trajectory()` provides a deterministic pre-completion check that every
required source was queried and returned a complete result. Use it on recorded
agent steps before accepting a model's `complete` claim.

`HybridEngine` also derives a mandatory source plan before the first model call.
By default, Coralogix is mandatory and the model cannot omit it by returning a
smaller `relevant_sources` list. Pass `required_sources=()` only for a host that
has deliberately chosen a different source policy. Provider-specific no-path
cases remain explicit in the engine and are not silently treated as checked.

`validate_humanized_draft()` is a final-pass safety check. It rejects a rewrite
when protected payment spans such as order IDs, dates, amounts, URLs, or
references are changed or removed. Humanization must run after the investigation
and before the existing `validate_output()` check.

Authorization and capture are reconciled separately from refunds. If the
authorised amount exceeds the captured amount, the captured amount is fully
refunded, and the difference matches the documented adjustment, the controller
classifies that difference as `UNCAPTURED_AUTHORIZATION`. It is not a missing
refund or a missing refund ARN. The controller still records that the bank's
release of the unused authorisation was not independently verified.

From the repository root, run the instruction-copy check with:

```text
.venv\\Scripts\\python.exe tools/check_instruction_drift.py
```

The golden-case manifest is at `tests/golden_cases.json`. Add an anonymized case
there when a drift or wording regression is found.
