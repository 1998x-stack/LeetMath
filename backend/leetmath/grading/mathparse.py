"""Safe math-input parser (docs/06 §3 security).

* Never calls eval/exec/sympify/parse_expr on user text.
* Whitelisted tokens, functions and symbols only; bounded length, depth and node count.
* Produces our own AST first, so we can record domain constraints (denominators, log/sqrt
  arguments, tan poles) *before* SymPy auto-simplifies e.g. x/x → 1.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction

import sympy as sp

MAX_LEN = 500
MAX_DEPTH = 40
MAX_NODES = 400
MAX_INT_EXPONENT = 400

FUNCTIONS = {
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "cot": sp.cot, "sec": sp.sec, "csc": sp.csc,
    "arcsin": sp.asin, "arccos": sp.acos, "arctan": sp.atan,
    "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
    "ln": sp.log, "log": sp.log, "lg": None, "exp": sp.exp, "sqrt": sp.sqrt, "abs": sp.Abs,
}
CONSTANTS = {"pi": sp.pi, "e": sp.E, "oo": sp.oo, "inf": sp.oo}


class MathInputError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ─────────────────────────── LaTeX / unicode normalisation ───────────────────────────
def _replace_braced_command(s: str, cmd: str, nargs: int, fmt) -> str:
    """Replace \\cmd{a}{b} (with nested braces) using fmt(*args)."""
    out = []
    i = 0
    needle = "\\" + cmd
    while True:
        j = s.find(needle, i)
        if j < 0:
            out.append(s[i:])
            break
        k = j + len(needle)
        if k < len(s) and s[k].isalpha():  # e.g. \frac vs \fracture — not ours
            out.append(s[i:k])
            i = k
            continue
        out.append(s[i:j])
        args = []
        opt = None
        while k < len(s) and s[k] == " ":
            k += 1
        if k < len(s) and s[k] == "[" and cmd == "sqrt":
            end = s.find("]", k)
            if end < 0:
                raise MathInputError("INVALID_MATH_INPUT", "unterminated [")
            opt = s[k + 1 : end]
            k = end + 1
        for _ in range(nargs):
            while k < len(s) and s[k] == " ":
                k += 1
            if k >= len(s):
                raise MathInputError("INVALID_MATH_INPUT", f"\\{cmd} missing argument")
            if s[k] != "{":  # \sqrt2 or \frac12 single-token shorthand
                args.append(s[k])
                k += 1
                continue
            depth = 0
            start = k
            while k < len(s):
                if s[k] == "{":
                    depth += 1
                elif s[k] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            if depth != 0:
                raise MathInputError("INVALID_MATH_INPUT", "unbalanced braces")
            args.append(s[start + 1 : k])
            k += 1
        out.append(fmt(*args) if opt is None else fmt(*args, opt=opt))
        i = k
    return "".join(out)


def normalize_input(text: str) -> str:
    s = text.strip()
    if not s:
        raise MathInputError("INVALID_MATH_INPUT", "empty input")
    if len(s) > MAX_LEN:
        raise MathInputError("INVALID_MATH_INPUT", "input too long")
    # A leading "f'(x)=" / "y=" label is accepted and ignored.
    s = re.sub(r"^\s*[A-Za-z](?:'|\\prime)*\s*(\(\s*[A-Za-z]\s*\))?\s*=\s*", "", s)
    s = s.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    for _ in range(10):
        if "\\frac" not in s:
            break
        s = _replace_braced_command(s, "frac", 2, lambda a, b: f"(({a})/({b}))")
    s = _replace_braced_command(
        s, "sqrt", 1, lambda a, opt=None: f"sqrt({a})" if opt is None else f"(({a})^(1/({opt})))"
    )
    s = re.sub(r"\\(mathrm|operatorname|text)\{([A-Za-z]+)\}", r"\2", s)
    replacements = [
        ("\\left", ""), ("\\right", ""), ("\\cdot", "*"), ("\\times", "*"), ("\\div", "/"),
        ("\\pi", " pi "), ("\\infty", " oo "), ("\\ln", " ln "), ("\\log", " log "),
        ("\\exp", " exp "), ("\\arcsin", " arcsin "), ("\\arccos", " arccos "), ("\\arctan", " arctan "),
        ("\\sin", " sin "), ("\\cos", " cos "), ("\\tan", " tan "), ("\\cot", " cot "),
        ("\\,", " "), ("\\;", " "), ("\\!", ""), ("\\ ", " "),
        ("×", "*"), ("·", "*"), ("÷", "/"), ("−", "-"), ("π", " pi "), ("∞", " oo "), ("√", "sqrt"),
        ("（", "("), ("）", ")"), ("，", ","), ("**", "^"),
    ]
    for a, b in replacements:
        s = s.replace(a, b)
    s = s.replace("{", "(").replace("}", ")")
    if "\\" in s:
        m = re.search(r"\\[A-Za-z]*", s)
        bad = m.group(0) if m else "backslash"
        raise MathInputError("INVALID_MATH_INPUT", "unsupported command " + bad)
    return s


# ─────────────────────────── tokenizer ───────────────────────────
_TOKEN_RE = re.compile(r"\s*(?:(\d+(?:\.\d+)?|\.\d+)|([A-Za-z]+)|(\^|\+|-|\*|/|\(|\)|,|\||!))")


@dataclass
class Tok:
    kind: str  # num / name / op / end
    value: str


def tokenize(s: str, variables: set[str]) -> list[Tok]:
    toks: list[Tok] = []
    pos = 0
    s = s.rstrip()
    while pos < len(s):
        m = _TOKEN_RE.match(s, pos)
        if not m or m.end() == pos:
            raise MathInputError("INVALID_MATH_INPUT", f"unexpected character {s[pos]!r}")
        num, name, op = m.groups()
        if num is not None:
            toks.append(Tok("num", num))
        elif name is not None:
            toks.extend(_split_name(name, variables))
        else:
            toks.append(Tok("op", op))
        pos = m.end()
    toks.append(Tok("end", ""))
    return toks


def _split_name(name: str, variables: set[str]) -> list[Tok]:
    """Split a letter run greedily into known functions/constants/variables (implicit products)."""
    known = sorted(set(FUNCTIONS) | set(CONSTANTS) | {v for v in variables if len(v) > 1}, key=len, reverse=True)
    out: list[Tok] = []
    i = 0
    while i < len(name):
        for k in known:
            if name.startswith(k, i):
                out.append(Tok("name", k))
                i += len(k)
                break
        else:
            out.append(Tok("name", name[i]))
            i += 1
    return out


# ─────────────────────────── AST + parser ───────────────────────────
# Node = tuple. ('num', Fraction) ('sym', str) ('const', str) ('neg', n) ('add'|'sub'|'mul'|'div'|'pow', a, b)
# ('call', fname, arg) ('fact', n)


@dataclass
class Parser:
    toks: list[Tok]
    variables: set[str]
    allow_unknown: bool = False
    i: int = 0
    nodes: int = 0
    used_symbols: set[str] = field(default_factory=set)

    def peek(self) -> Tok:
        return self.toks[self.i]

    def take(self) -> Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, value: str) -> None:
        t = self.take()
        if t.value != value:
            raise MathInputError("INVALID_MATH_INPUT", f"expected {value!r}")

    def node(self, *n):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise MathInputError("INVALID_MATH_INPUT", "expression too large")
        return n

    def parse(self):
        n = self.expr(0)
        if self.peek().kind != "end":
            raise MathInputError("INVALID_MATH_INPUT", f"unexpected {self.peek().value!r}")
        return n

    def expr(self, depth: int, stop_bar: bool = False):
        if depth > MAX_DEPTH:
            raise MathInputError("INVALID_MATH_INPUT", "expression nested too deeply")
        n = self.term(depth, stop_bar)
        while self.peek().value in ("+", "-"):
            op = self.take().value
            r = self.term(depth, stop_bar)
            n = self.node("add" if op == "+" else "sub", n, r)
        return n

    def _starts_primary(self, t: Tok, stop_bar: bool) -> bool:
        if t.kind in ("num", "name"):
            return True
        return t.value == "(" or (t.value == "|" and not stop_bar)

    def term(self, depth: int, stop_bar: bool):
        n = self.unary(depth, stop_bar)
        while True:
            t = self.peek()
            if t.value in ("*", "/"):
                self.take()
                r = self.unary(depth, stop_bar)
                n = self.node("mul" if t.value == "*" else "div", n, r)
            elif self._starts_primary(t, stop_bar):  # implicit multiplication: 2x, x(x+1), 2sin x
                r = self.power(depth, stop_bar)
                n = self.node("mul", n, r)
            else:
                return n

    def unary(self, depth: int, stop_bar: bool):
        t = self.peek()
        if t.value == "-":
            self.take()
            return self.node("neg", self.unary(depth + 1, stop_bar))
        if t.value == "+":
            self.take()
            return self.unary(depth + 1, stop_bar)
        return self.power(depth, stop_bar)

    def power(self, depth: int, stop_bar: bool):
        base = self.postfix(depth, stop_bar)
        if self.peek().value == "^":
            self.take()
            exp = self.unary(depth + 1, stop_bar)  # right-assoc, allows x^-1
            return self.node("pow", base, exp)
        return base

    def postfix(self, depth: int, stop_bar: bool):
        n = self.primary(depth, stop_bar)
        while self.peek().value == "!":
            self.take()
            n = self.node("fact", n)
        return n

    def primary(self, depth: int, stop_bar: bool):
        t = self.take()
        if t.kind == "num":
            return self.node("num", Fraction(t.value))
        if t.value == "(":
            n = self.expr(depth + 1)
            self.expect(")")
            return n
        if t.value == "|":
            n = self.expr(depth + 1, stop_bar=True)
            self.expect("|")
            return self.node("call", "abs", n)
        if t.kind == "name":
            name = t.value
            if name in FUNCTIONS:
                if FUNCTIONS[name] is None:
                    raise MathInputError("INVALID_MATH_INPUT", f"function {name} not supported; use log")
                # optional power on function: sin^2 x
                fpow = None
                if self.peek().value == "^":
                    self.take()
                    fpow = self.postfix(depth + 1, stop_bar)
                if self.peek().value == "(":
                    self.take()
                    arg = self.expr(depth + 1)
                    self.expect(")")
                else:  # sin x, ln x  — binds to the next power term
                    arg = self.power(depth + 1, stop_bar)
                n = self.node("call", name, arg)
                return self.node("pow", n, fpow) if fpow is not None else n
            if name in CONSTANTS and name not in self.variables:
                return self.node("const", name)
            if name in self.variables or self.allow_unknown:
                self.used_symbols.add(name)
                return self.node("sym", name)
            raise MathInputError("UNKNOWN_SYMBOL", f"unknown symbol {name!r}")
        raise MathInputError("INVALID_MATH_INPUT", f"unexpected {t.value or 'end of input'!r}")


def parse(text: str, variables: set[str], allow_unknown: bool = False):
    s = normalize_input(text)
    p = Parser(tokenize(s, variables), variables, allow_unknown)
    ast = p.parse()
    return ast, p.used_symbols


# ─────────────────────────── AST → SymPy, domain constraints ───────────────────────────
def make_symbols(assumptions: dict[str, str]) -> dict[str, sp.Symbol]:
    flags = {
        "real": {"real": True},
        "positive": {"positive": True},
        "negative": {"negative": True},
        "nonnegative": {"nonnegative": True},
        "nonzero": {"real": True, "nonzero": True},
        "integer": {"integer": True},
        "positive_integer": {"integer": True, "positive": True},
    }
    return {name: sp.Symbol(name, **flags.get(kind, {"real": True})) for name, kind in assumptions.items()}


@dataclass
class Converted:
    expr: sp.Expr
    constraints: list[tuple[str, sp.Expr]]  # ('nonzero'|'positive'|'nonneg', expr)


def to_sympy(ast, symbols: dict[str, sp.Symbol]) -> Converted:
    constraints: list[tuple[str, sp.Expr]] = []

    def conv(n) -> sp.Expr:
        kind = n[0]
        if kind == "num":
            return sp.Rational(n[1].numerator, n[1].denominator)
        if kind == "sym":
            return symbols.get(n[1]) or sp.Symbol(n[1], real=True)
        if kind == "const":
            return CONSTANTS[n[1]]
        if kind == "neg":
            return -conv(n[1])
        if kind in ("add", "sub", "mul"):
            a, b = conv(n[1]), conv(n[2])
            return a + b if kind == "add" else a - b if kind == "sub" else a * b
        if kind == "div":
            a, b = conv(n[1]), conv(n[2])
            if b == 0:
                raise MathInputError("INVALID_MATH_INPUT", "division by zero")
            constraints.append(("nonzero", b))
            return a / b
        if kind == "pow":
            a, b = conv(n[1]), conv(n[2])
            if a.is_number and b.is_number and b.is_Integer and abs(int(b)) > MAX_INT_EXPONENT:
                raise MathInputError("INVALID_MATH_INPUT", "exponent too large")
            if a.is_Integer and b.is_Integer and abs(int(a)) > 1 and abs(int(b)) * len(str(abs(int(a)))) > 2000:
                raise MathInputError("INVALID_MATH_INPUT", "number too large")
            if b.is_number and b.is_negative:
                constraints.append(("nonzero", a))
            if b.is_Rational and not b.is_Integer and b.q % 2 == 0:
                constraints.append(("nonneg", a))
            elif not b.is_number:
                constraints.append(("positive", a)) if not a.is_number else None
            return a**b
        if kind == "fact":
            a = conv(n[1])
            if a.is_Integer and int(a) > 200:
                raise MathInputError("INVALID_MATH_INPUT", "factorial too large")
            return sp.factorial(a)
        if kind == "call":
            fname, arg = n[1], conv(n[2])
            if fname in ("ln", "log"):
                constraints.append(("positive", arg))
            elif fname == "sqrt":
                constraints.append(("nonneg", arg))
            elif fname in ("tan", "sec"):
                constraints.append(("nonzero", sp.cos(arg)))
            elif fname in ("cot", "csc"):
                constraints.append(("nonzero", sp.sin(arg)))
            return FUNCTIONS[fname](arg)
        raise MathInputError("INVALID_MATH_INPUT", f"bad node {kind}")

    return Converted(conv(ast), constraints)
