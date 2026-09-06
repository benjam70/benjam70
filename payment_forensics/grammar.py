"""Optional local grammar checking via the Harper language server.

Vale (vale_linter.py) enforces house style (banned words, gateway names) but
explicitly does not catch grammar. Harper (https://writewithharper.com) runs
fully offline, nothing leaves the machine, and its only interface is the
Language Server Protocol, so this module speaks a minimal subset of LSP over
stdio: initialize, open a virtual document, read back the diagnostics it
publishes, then shut down. This is deliberately opt-in, same pattern as
vale_linter.py and nli.py: a missing binary is a skip, not a failure.

Reading a subprocess pipe on Windows blocks with no way to time out
mid-read, so message framing is read on a daemon background thread and
handed to the caller through a queue; every wait uses queue.get(timeout=...)
instead of a raw stream.read().
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path


@dataclass(frozen=True)
class GrammarResult:
    available: bool
    allowed: bool
    skipped: bool = False
    messages: tuple[str, ...] = ()


def _write_message(stream, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    stream.write(body)
    stream.flush()


def _reader_loop(stream, out_queue: "queue.Queue[dict | None]") -> None:
    try:
        while True:
            headers = b""
            while b"\r\n\r\n" not in headers:
                chunk = stream.read(1)
                if not chunk:
                    out_queue.put(None)
                    return
                headers += chunk
            header_text = headers.decode("ascii", errors="replace")
            length = 0
            for line in header_text.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    length = int(line.split(":", 1)[1].strip())
            body = b""
            while len(body) < length:
                chunk = stream.read(length - len(body))
                if not chunk:
                    out_queue.put(None)
                    return
                body += chunk
            try:
                out_queue.put(json.loads(body.decode("utf-8")))
            except json.JSONDecodeError:
                continue
    except (OSError, ValueError):
        out_queue.put(None)


def run_grammar_check(text: str, *, executable: str = "harper-ls", timeout: float = 8.0) -> GrammarResult:
    """Run Harper locally when installed; never send text anywhere over the network."""
    project_root = Path(__file__).resolve().parents[1]
    binary = shutil.which(executable)
    if binary is None and executable == "harper-ls":
        bundled = project_root / ".tools" / "harper" / "harper-ls.exe"
        if bundled.is_file():
            binary = str(bundled)
    if not binary:
        return GrammarResult(available=False, allowed=True, skipped=True)

    uri = "file:///payment-forensics-grammar-check.md"
    deadline = time.monotonic() + timeout
    process = subprocess.Popen(
        [binary, "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    messages_queue: "queue.Queue[dict | None]" = queue.Queue()
    reader = threading.Thread(target=_reader_loop, args=(process.stdout, messages_queue), daemon=True)
    reader.start()

    def _next_message():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            return messages_queue.get(timeout=remaining)
        except queue.Empty:
            return None

    try:
        _write_message(process.stdin, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"processId": None, "rootUri": None, "capabilities": {}},
        })
        init_response = _next_message()
        if init_response is None or "result" not in init_response:
            return GrammarResult(True, True, skipped=True, messages=("Harper did not initialize in time",))

        _write_message(process.stdin, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
        _write_message(process.stdin, {
            "jsonrpc": "2.0", "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "markdown", "version": 1, "text": text}},
        })

        diagnostics: list[dict] = []
        found = False
        while True:
            message = _next_message()
            if message is None:
                break
            # harper-ls sends its own requests back to the client (e.g.
            # workspace/configuration) and blocks further processing,
            # including linting, until every one of them gets a reply.
            if "id" in message and "method" in message:
                if message["method"] == "workspace/configuration":
                    items = message.get("params", {}).get("items", [{}])
                    _write_message(process.stdin, {"jsonrpc": "2.0", "id": message["id"], "result": [None] * len(items)})
                else:
                    _write_message(process.stdin, {"jsonrpc": "2.0", "id": message["id"], "result": None})
                continue
            if message.get("method") == "textDocument/publishDiagnostics":
                params = message.get("params", {})
                if params.get("uri") == uri:
                    diagnostics = params.get("diagnostics", [])
                    found = True
                    break
        if not found:
            return GrammarResult(True, True, skipped=True, messages=("Harper did not respond in time",))

        # LSP DiagnosticSeverity: 1=Error, 2=Warning, 3=Information, 4=Hint.
        # Harper reports its suggestions at Hint level, so only a genuine
        # Error blocks; everything else is advisory and only surfaced.
        severity_names = {1: "error", 2: "warning", 3: "info", 4: "hint"}
        messages = tuple(
            f"{severity_names.get(item.get('severity'), 'hint')}: {item.get('message', 'grammar issue')}"
            for item in diagnostics
        )
        blocked = any(item.get("severity") == 1 for item in diagnostics)
        return GrammarResult(True, not blocked, messages=messages)
    finally:
        try:
            _write_message(process.stdin, {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None})
            _write_message(process.stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
            process.stdin.close()
        except Exception:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
