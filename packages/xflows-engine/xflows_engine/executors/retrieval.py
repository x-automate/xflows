"""Executors for retrieval-flavored nodes: WebSearch and VectorStore.

The engine stays stdlib-only. WebSearch performs a real DuckDuckGo Lite
search through the ``context.http_request`` seam ((method, url) -> response
text) and parses the HTML with ``re``/``html.unescape``/``urllib.parse``.
VectorStore is a pass-through that echoes its configuration in metadata.
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlsplit

from ..base import BaseNodeExecutor
from ..context import NodeExecutionContext
from ..result import NodeExecutionResult

_DUCKDUCKGO_LITE_URL = "https://lite.duckduckgo.com/lite/?q="

_LINK_RE = re.compile(r"<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", re.DOTALL | re.IGNORECASE)
_SNIPPET_RE = re.compile(
    r"<td[^>]+class=\"result-snippet\"[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_tags(fragment: str) -> str:
    """Remove HTML tags, unescape entities, and collapse whitespace."""
    text = html.unescape(_TAG_RE.sub("", fragment))
    return _WHITESPACE_RE.sub(" ", text).strip()


def _resolve_result_url(href: str) -> str | None:
    """Resolve a DuckDuckGo Lite result href to the target URL.

    Lite wraps results in redirects of the form
    ``//duckduckgo.com/l/?uddg=<urlencoded target>&rut=...``. Direct
    duckduckgo.com links (pagination, home page, ...) are skipped.
    """
    cleaned = href.strip()
    if not cleaned:
        return None
    split = urlsplit(cleaned)
    host = (split.netloc or "").lower()
    if "duckduckgo.com" in host or cleaned.startswith("//duckduckgo.com"):
        query = parse_qs(split.query)
        target = query.get("uddg", [""])[0]
        return target or None
    # Plain http(s) links pass through; scheme-relative links get https.
    if not split.scheme and cleaned.startswith("//"):
        return "https:" + cleaned
    if split.scheme in ("http", "https"):
        return cleaned
    return None


def _coerce_top_k(raw: Any, default: int = 3) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _resolve_query(node: dict[str, Any], input_payload: dict[str, Any], context: NodeExecutionContext) -> str:
    """Resolve the search query from node params, upstream input, or user input."""
    params = node.get("params", {}) or {}
    raw = params.get("query")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    value = input_payload.get("value", "")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("query", "search", "text", "input"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return context.user_input.strip() if context.user_input else ""


def _parse_results(response_text: str, top_k: int) -> list[dict[str, str]]:
    """Extract result links and snippets from DuckDuckGo Lite HTML."""
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href, label in _LINK_RE.findall(response_text):
        title = _strip_tags(label)
        url = _resolve_result_url(href)
        if not url or not title or url in seen:
            continue
        seen.add(url)
        links.append((title, url))
        if len(links) >= top_k:
            break
    snippets = [_strip_tags(snippet) for snippet in _SNIPPET_RE.findall(response_text)]
    results: list[dict[str, str]] = []
    for index, (title, url) in enumerate(links):
        entry = {"title": title, "url": url}
        if index < len(snippets) and snippets[index]:
            entry["snippet"] = snippets[index]
        results.append(entry)
    return results


def _format_results(results: list[dict[str, str]]) -> str:
    """Render results as a numbered list for downstream nodes."""
    lines: list[str] = []
    for index, result in enumerate(results, start=1):
        lines.append(f"{index}. {result['title']}")
        lines.append(f"   {result['url']}")
        snippet = result.get("snippet", "")
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)


class WebSearchExecutor(BaseNodeExecutor):
    component_ids = ("WebSearch",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        top_k = _coerce_top_k(params.get("top_k"))
        query = _resolve_query(node, input_payload, context)
        passthrough = input_payload.get("value", "")

        if not query:
            return NodeExecutionResult(
                value=passthrough,
                metadata={"note": "No query resolved; input passed through.", "top_k": top_k},
            )

        url = _DUCKDUCKGO_LITE_URL + quote_plus(query)
        try:
            response_text = await context.http_request("GET", url)
        except Exception as exc:  # noqa: BLE001 - degrade to passthrough, never fail the run
            return NodeExecutionResult(
                value=passthrough,
                metadata={
                    "note": f"WebSearch request failed; input passed through. ({exc})",
                    "query": query,
                    "top_k": top_k,
                },
            )

        results = _parse_results(response_text, top_k)
        if not results:
            return NodeExecutionResult(
                value=passthrough,
                metadata={
                    "note": "No results parsed from search; input passed through.",
                    "query": query,
                    "top_k": top_k,
                },
            )

        return NodeExecutionResult(
            value=_format_results(results),
            metadata={"query": query, "top_k": top_k, "results": results},
        )


class VectorStoreExecutor(BaseNodeExecutor):
    component_ids = ("VectorStore",)

    async def execute(
        self,
        node: dict[str, Any],
        input_payload: dict[str, Any],
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        params = node.get("params", {}) or {}
        return NodeExecutionResult(
            value=input_payload.get("value", ""),
            metadata={
                "vectorStore": {
                    "collection": str(params.get("collection", "docs") or "docs"),
                    "top_k": _coerce_top_k(params.get("top_k")),
                    "query": params.get("query", ""),
                },
            },
        )
