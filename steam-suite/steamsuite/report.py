"""Step-by-step calculation reports.

Every calculation in the suite records what it did as a list of steps:
a plain-language explanation, the equation in symbols, the equation with
numbers substituted, and the result. The report can be shown in the app or
exported as Markdown or a standalone HTML page.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date

from .units import fmt


def num(value: float, sig: int = 4) -> str:
    """Number formatted for LaTeX (no thousands separators)."""
    return fmt(value, sig, sep=False)


def tex_text(text: str) -> str:
    """Plain text inside a LaTeX equation (handles ° and · safely)."""
    body = text.replace("·", r"}\cdot\text{").replace("°", r"}{}^{\circ}\text{")
    body = re.sub(r"\^(\d+)", r"}^{\1}\\text{", body)
    return r"\text{" + body + "}"


def unit(text: str) -> str:
    """Unit for LaTeX, e.g. unit('mm^2') -> '\\ \\text{mm}^{2}\\text{}'."""
    return r"\ " + tex_text(text)


@dataclass
class Step:
    title: str
    text: str = ""
    equation: str | None = None  # LaTeX, in symbols
    substitution: str | None = None  # LaTeX, with numbers
    result: str | None = None  # LaTeX
    reference: str | None = None
    table: list[list[str]] | None = None  # first row is the header


@dataclass
class CalcReport:
    title: str
    subtitle: str = ""
    inputs: list[tuple[str, str]] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    results: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    disclaimer: str | None = None

    def add_input(self, label: str, value: str) -> None:
        self.inputs.append((label, value))

    def add_step(self, title: str, **kwargs) -> Step:
        step = Step(title=title, **kwargs)
        self.steps.append(step)
        return step

    def add_result(self, label: str, value: str) -> None:
        self.results.append((label, value))

    # --- export -------------------------------------------------------------

    def to_markdown(self) -> str:
        out: list[str] = [f"# {self.title}", ""]
        if self.subtitle:
            out += [self.subtitle, ""]
        out += [f"*Prepared {date.today().isoformat()} with Steam Suite.*", ""]
        if self.disclaimer:
            out += [f"> **Important:** {self.disclaimer}", ""]
        if self.results:
            out += ["## Summary", "", "| Result | Value |", "|---|---|"]
            out += [f"| {k} | {v} |" for k, v in self.results]
            out.append("")
        if self.warnings:
            out += ["## Warnings", ""] + [f"- ⚠️ {w}" for w in self.warnings] + [""]
        if self.inputs:
            out += ["## Inputs", "", "| Input | Value |", "|---|---|"]
            out += [f"| {k} | {v} |" for k, v in self.inputs]
            out.append("")
        if self.steps:
            out += ["## Calculation", ""]
            for i, s in enumerate(self.steps, 1):
                out += [f"### Step {i}: {s.title}", ""]
                if s.text:
                    out += [s.text, ""]
                for eq in (s.equation, s.substitution, s.result):
                    if eq:
                        out += [f"$$ {eq} $$", ""]
                if s.table:
                    out += _md_table(s.table) + [""]
                if s.reference:
                    out += [f"*Reference: {s.reference}*", ""]
        if self.assumptions:
            out += ["## Assumptions and limitations", ""] + [f"- {a}" for a in self.assumptions] + [""]
        if self.references:
            out += ["## References", ""] + [f"{i}. {r}" for i, r in enumerate(self.references, 1)] + [""]
        return "\n".join(out)

    def to_html(self) -> str:
        e = html.escape
        parts: list[str] = []
        parts.append(f"<h1>{e(self.title)}</h1>")
        if self.subtitle:
            parts.append(f"<p class='subtitle'>{e(self.subtitle)}</p>")
        parts.append(f"<p class='meta'>Prepared {date.today().isoformat()} with Steam Suite.</p>")
        if self.disclaimer:
            parts.append(f"<div class='note'><strong>Important:</strong> {e(self.disclaimer)}</div>")
        if self.results:
            parts.append("<h2>Summary</h2>" + _html_kv(self.results, "Result"))
        if self.warnings:
            items = "".join(f"<li>{e(w)}</li>" for w in self.warnings)
            parts.append(f"<h2>Warnings</h2><ul class='warn'>{items}</ul>")
        if self.inputs:
            parts.append("<h2>Inputs</h2>" + _html_kv(self.inputs, "Input"))
        if self.steps:
            parts.append("<h2>Calculation</h2>")
            for i, s in enumerate(self.steps, 1):
                block = [f"<section class='step'><h3>Step {i}: {e(s.title)}</h3>"]
                if s.text:
                    block.append(f"<p>{e(s.text)}</p>")
                for eq in (s.equation, s.substitution, s.result):
                    if eq:
                        block.append(f"<div class='eq'>$$ {e(eq)} $$</div>")
                if s.table:
                    block.append(_html_table(s.table))
                if s.reference:
                    block.append(f"<p class='ref'>Reference: {e(s.reference)}</p>")
                block.append("</section>")
                parts.append("".join(block))
        if self.assumptions:
            items = "".join(f"<li>{e(a)}</li>" for a in self.assumptions)
            parts.append(f"<h2>Assumptions and limitations</h2><ul>{items}</ul>")
        if self.references:
            items = "".join(f"<li>{e(r)}</li>" for r in self.references)
            parts.append(f"<h2>References</h2><ol>{items}</ol>")
        body = "\n".join(parts)
        return _HTML_TEMPLATE.replace("{{TITLE}}", e(self.title)).replace("{{BODY}}", body)


def _md_table(rows: list[list[str]]) -> list[str]:
    head, *rest = rows
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(r) + " |" for r in rest]
    return lines


def _html_kv(rows: list[tuple[str, str]], first: str) -> str:
    e = html.escape
    body = "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in rows)
    return f"<table><thead><tr><th>{first}</th><th>Value</th></tr></thead><tbody>{body}</tbody></table>"


def _html_table(rows: list[list[str]]) -> str:
    e = html.escape
    head, *rest = rows
    th = "".join(f"<th>{e(c)}</th>" for c in head)
    trs = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in rest)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body,{delimiters:[{left:'$$',right:'$$',display:true}]});"></script>
<style>
  body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; max-width: 900px;
         margin: 2rem auto; padding: 0 1rem; color: #1d2733; line-height: 1.5; background: #fff; }
  h1 { margin-bottom: .2rem; } h2 { border-bottom: 2px solid #e3e8ee; padding-bottom: .2rem; margin-top: 2rem; }
  h3 { margin-bottom: .3rem; }
  .subtitle { color: #4a5868; margin-top: 0; } .meta { color: #6b7785; font-size: .9rem; }
  table { border-collapse: collapse; margin: .6rem 0; width: 100%; }
  th, td { border: 1px solid #d5dce4; padding: .35rem .6rem; text-align: left; }
  th { background: #f2f5f8; }
  .step { border-left: 4px solid #2f6db5; padding: .2rem 0 .2rem 1rem; margin: 1.2rem 0; }
  .eq { overflow-x: auto; }
  .ref { color: #6b7785; font-size: .9rem; font-style: italic; }
  .note { background: #fff6e0; border: 1px solid #f0d48a; padding: .7rem 1rem; border-radius: 6px; }
  ul.warn li { color: #8a4b00; }
  @media print { body { margin: 0; } .step { break-inside: avoid; } }
</style>
</head>
<body>
{{BODY}}
</body>
</html>
"""
