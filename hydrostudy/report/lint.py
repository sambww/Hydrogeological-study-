"""Anti-fabrication lint: every number in generated narrative must come from the computed context.

Templates carry no numeric literals; equation constants and citation years are whitelisted explicitly."""

from __future__ import annotations

import re

NUM_RE = re.compile(r"(?<![A-Za-z.\-/])\d[\d,]*(?:\.\d+)?")
EQUATION_CONSTANTS = {"4", "2", "2.25", "0.5772", "192.5", "1440", "24", "1", "3", "100", "0.01", "10"}


def numbers_in(text: str) -> set[str]:
    return {m.group(0).rstrip(",") for m in NUM_RE.finditer(text or "")}


def collect_allowed(obj, acc: set | None = None) -> set:
    acc = set() if acc is None else acc
    if isinstance(obj, str):
        acc |= numbers_in(obj)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        acc.add(f"{obj}")
        acc |= numbers_in(f"{obj:,}") | numbers_in(f"{obj:,.1f}") | numbers_in(f"{obj:,.0f}") | numbers_in(f"{obj:g}")
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_allowed(v, acc)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            collect_allowed(v, acc)
    return acc


#: Context keys holding prose a person typed rather than anything the pipeline computed. Their numbers must never
#: enter the allowed set, or they whitelist themselves: a reviewer's opinion is precisely where a hand-typed figure
#: would otherwise reach a sealed report unchecked, which is the case this lint exists to prevent.
UNTRUSTED_CONTEXT_KEYS = ("opinions", "reviewer")


def allowed_number_set(context: dict, extra_allowed: set | None = None) -> set:
    """Every number the narrative may legitimately contain, from the computed context only."""
    computed = {k: v for k, v in context.items() if k not in UNTRUSTED_CONTEXT_KEYS}
    return collect_allowed(computed) | EQUATION_CONSTANTS | (extra_allowed or set())


def lint_sections(sections: dict[str, str], context: dict, extra_allowed: set | None = None) -> dict:
    allowed = allowed_number_set(context, extra_allowed)
    problems = []
    for name, text in sections.items():
        for tok in sorted(numbers_in(text)):
            if tok not in allowed and tok.replace(",", "") not in allowed:
                problems.append({"section": name, "number": tok})
    return {"ok": not problems, "problems": problems, "n_allowed": len(allowed)}
