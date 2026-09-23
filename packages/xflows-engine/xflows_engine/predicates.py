from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(
    r"""\s*(?:
        (?P<op>==|!=|>=|<=|&&|\|\|)
      | (?P<punct>[()!,<>])
      | (?P<string>'[^']*'|"[^"]*")
      | (?P<number>-?\d+(?:\.\d+)?)
      | (?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)
    )""",
    re.VERBOSE,
)

_KEYWORDS: dict[str, Any] = {"true": True, "false": False, "null": None, "none": None}
_FUNCTIONS = ("contains", "startsWith", "endsWith")


class WhenSyntaxError(ValueError):
    pass


def resolve_path(payload: Any, path: str) -> Any:
    current = payload
    for part in str(path).split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _equals(left: Any, right: Any) -> bool:
    left_num = _as_number(left)
    right_num = _as_number(right)
    if left_num is not None and right_num is not None:
        return left_num == right_num
    if left is None or right is None:
        return left is None and right is None
    return str(left) == str(right)


def _compare(op: str, left: Any, right: Any) -> bool:
    if op == "==":
        return _equals(left, right)
    if op == "!=":
        return not _equals(left, right)
    left_num = _as_number(left)
    right_num = _as_number(right)
    if left_num is not None and right_num is not None:
        a, b = left_num, right_num
    else:
        a, b = str(left), str(right)
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    raise WhenSyntaxError(f"Unsupported comparison operator {op!r}")


def _call_function(name: str, args: list[Any]) -> Any:
    if name == "contains":
        _require_args(name, args)
        return str(args[1]) in str(args[0])
    if name == "startsWith":
        _require_args(name, args)
        return str(args[0]).startswith(str(args[1]))
    if name == "endsWith":
        _require_args(name, args)
        return str(args[0]).endswith(str(args[1]))
    raise WhenSyntaxError(f"Unknown function {name!r} in when expression")


def _require_args(name: str, args: list[Any]) -> None:
    if len(args) != 2:
        raise WhenSyntaxError(f"{name}() takes exactly 2 arguments")


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value)
    return bool(value)


def _tokenize(expr: str) -> list[tuple[str, Any]]:
    tokens: list[tuple[str, Any]] = []
    pos = 0
    while pos < len(expr):
        match = _TOKEN_RE.match(expr, pos)
        if match is None or match.end() == pos:
            if not expr[pos:].strip():
                break
            raise WhenSyntaxError(
                f"Invalid token in when expression at index {pos}: {expr[pos]!r}"
            )
        pos = match.end()
        kind = match.lastgroup
        if kind in ("op", "punct"):
            tokens.append(("op", match.group(kind)))
        elif kind == "string":
            tokens.append(("val", match.group(kind)[1:-1]))
        elif kind == "number":
            text = match.group(kind)
            tokens.append(("val", float(text) if "." in text else int(text)))
        else:
            name = match.group(kind)
            if name in _KEYWORDS:
                tokens.append(("val", _KEYWORDS[name]))
            else:
                tokens.append(("path", name))
    tokens.append(("end", None))
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, Any]], payload: Any) -> None:
        self._tokens = tokens
        self._payload = payload
        self._index = 0

    def _peek(self) -> tuple[str, Any]:
        return self._tokens[self._index]

    def _advance(self) -> tuple[str, Any]:
        token = self._tokens[self._index]
        self._index += 1
        return token

    def parse(self) -> Any:
        result = self._parse_or()
        kind, value = self._peek()
        if kind != "end":
            raise WhenSyntaxError(f"Unexpected token {value!r} in when expression")
        return result

    def _parse_or(self) -> Any:
        left = self._truthy(self._parse_and())
        while self._peek() == ("op", "||"):
            self._advance()
            right = self._truthy(self._parse_and())
            left = left or right
        return left

    def _parse_and(self) -> Any:
        left = self._truthy(self._parse_unary())
        while self._peek() == ("op", "&&"):
            self._advance()
            right = self._truthy(self._parse_unary())
            left = left and right
        return left

    def _parse_unary(self) -> Any:
        if self._peek() == ("op", "!"):
            self._advance()
            return not self._truthy(self._parse_unary())
        return self._parse_comparison()

    def _parse_comparison(self) -> Any:
        left = self._parse_primary()
        kind, value = self._peek()
        if kind == "op" and value in ("==", "!=", ">", "<", ">=", "<="):
            self._advance()
            right = self._parse_primary()
            return _compare(value, left, right)
        return left

    def _parse_primary(self) -> Any:
        kind, value = self._advance()
        if kind == "op" and value == "(":
            inner = self._parse_or()
            closing_kind, closing_value = self._advance()
            if closing_kind != "op" or closing_value != ")":
                raise WhenSyntaxError("Missing closing parenthesis in when expression")
            return inner
        if kind == "op" and value in (")", ","):
            raise WhenSyntaxError(f"Unexpected token {value!r} in when expression")
        if kind == "path":
            if self._peek() == ("op", "("):
                if value not in _FUNCTIONS:
                    raise WhenSyntaxError(f"Unknown function {value!r} in when expression")
                self._advance()
                args = self._parse_args()
                return _call_function(value, args)
            return resolve_path(self._payload, value)
        if kind == "end":
            raise WhenSyntaxError("Unexpected end of when expression")
        return value

    def _parse_args(self) -> list[Any]:
        args: list[Any] = []
        if self._peek() == ("op", ")"):
            self._advance()
            return args
        args.append(self._parse_primary())
        while self._peek() == ("op", ","):
            self._advance()
            args.append(self._parse_primary())
        closing_kind, closing_value = self._advance()
        if closing_kind != "op" or closing_value != ")":
            raise WhenSyntaxError("Missing closing parenthesis in when function call")
        return args

    def _truthy(self, value: Any) -> bool:
        return _truthy(value)


def evaluate_when(expr: Any, payload: Any) -> bool:
    if expr is None or str(expr).strip() == "":
        return True
    tokens = _tokenize(str(expr))
    parser = _Parser(tokens, payload)
    result = parser.parse()
    return _truthy(result)
