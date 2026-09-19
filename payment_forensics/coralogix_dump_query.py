"""Query large saved Coralogix result dumps with real SQL, not regex.

When a `coralogix_query_dataprime` result is too large to return inline, the
harness saves it to a file and hands back the path. Reading that file by
hand so far has meant grepping for an escaped-JSON pattern like
``message\\":\\"[^\\]*`` and iterating on the regex until it stops
truncating or missing rows, real, repeated friction from this session's
investigations, not a hypothetical.

DuckDB reads the exact structure Coralogix returns (``results`` is a list
of ``{metadata, labels, userData}``, with ``userData`` itself a JSON
string) directly via ``read_json_auto``, no manual escaping, and lets you
group, count, and filter across the *entire* file with one query instead
of re-running grep with a wider capture group each time.

Requires the optional ``duckdb`` package. Without it, callers should keep
using targeted Coralogix queries and grep on the saved file, the way every
case so far was actually investigated; a missing install is not a data gap.
"""

from __future__ import annotations

import re

_SAFE_FIELD_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _connect(dump_path: str):
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "Install the optional duckdb package to query saved Coralogix dumps"
        ) from exc
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE _raw AS SELECT unnest(results) AS r FROM read_json_auto(?)",
        [dump_path],
    )
    con.execute("CREATE VIEW events AS SELECT r.userData AS user_data FROM _raw")
    return con


def field_value_counts(
    dump_path: str,
    fields: list[str],
    *,
    limit: int = 50,
) -> tuple[tuple, ...]:
    """Group every row in a saved dump by one or more userData fields.

    dump_path: path to a saved coralogix_query_dataprime result file.
    fields: top-level userData field names to group by, e.g. ["action",
      "message"]. Each becomes its own column in the result, plus a
      trailing count column, most frequent combination first.
    limit: max distinct combinations to return (default 50).

    This is the direct replacement for grepping the saved file for a
    pattern and eyeballing which messages repeat: one query answers "what
    are the real recurring event shapes in this file" completely,
    including full untruncated message text.
    """
    for field in fields:
        if not _SAFE_FIELD_RE.fullmatch(field):
            raise ValueError(f"unsafe field name: {field!r}")
    con = _connect(dump_path)
    selects = ", ".join(f"json_extract_string(user_data, '$.{f}') AS {f}" for f in fields)
    group_by = ", ".join(str(i + 1) for i in range(len(fields)))
    sql = (
        f"SELECT {selects}, COUNT(*) AS n FROM events "
        f"GROUP BY {group_by} ORDER BY n DESC LIMIT ?"
    )
    return tuple(con.execute(sql, [limit]).fetchall())


def run_sql(dump_path: str, sql: str, *, params: list | None = None) -> tuple[tuple, ...]:
    """Run arbitrary SQL against a saved dump's `events` view.

    `events` has one column, `user_data` (the raw JSON string for each log
    row). Use `json_extract_string(user_data, '$.<field>')` to pull a
    field, same as `field_value_counts` does internally. Prefer
    `field_value_counts` for the common "group and count" case, this is
    for anything that needs a real WHERE clause or a join, that
    grep can't express at all.
    """
    con = _connect(dump_path)
    return tuple(con.execute(sql, params or []).fetchall())
