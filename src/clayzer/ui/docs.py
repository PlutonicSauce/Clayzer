"""The project's docs, served by the web app at /docs/<path>, so How it works can link to the
plan and design section by section.

Only the project's own Markdown is served (README, the CLI reference, the glossary, the plan,
the design, the briefs, the ADRs); any other path is refused. Section anchors match GitHub's, so
links between the docs keep working. Links to other docs stay in the app; links to code point at GitHub. Mermaid
diagrams render with Mermaid from a CDN when it's reachable, and show as their source text when
it isn't.
"""

from __future__ import annotations

import posixpath
import re
from html import escape

from clayzer.config import REPO

GITHUB = "https://github.com/PlutonicSauce/Clayzer/blob/main/"
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"

# The docs index, in reading order: (path, title).
DOCS = [
    ("docs/caption-plan.md", "The plan"),
    ("docs/caption-design.md", "The design"),
    ("docs/ontology-data-driven.md", "Ontology: data-driven design"),
    ("docs/ontology-induction.md", "Ontology: induction plan"),
    ("GLOSSARY.md", "Glossary"),
    ("README.md", "README: getting started"),
    ("docs/cli.md", "CLI and configuration reference"),
    ("docs/regression-gate.md", "Regression gate: prompt experiments"),
    ("docs/regression-gate-audit.md", "Regression gate: tests and limitations"),
    ("labels/extraction/README.md", "Labelling Claims from free text"),
    ("docs/tech-hackathon.md", "Brief: technical"),
    ("docs/vision-hackathon.md", "Brief: vision"),
]


def allowed() -> dict[str, str]:
    """Every servable doc: path -> title. ADRs are found on disk."""
    docs = {p: t for p, t in DOCS if (REPO / p).exists()}
    for adr in sorted((REPO / "docs" / "adr").glob("*.md")):
        number = adr.name.split("-", 1)[0]
        title = adr.read_text().splitlines()[0].lstrip("# ").strip()
        docs[f"docs/adr/{adr.name}"] = f"ADR-{number}: {title}"
    return docs


def _rewrite_links(html: str, path: str, docs: dict[str, str]) -> str:
    base = posixpath.dirname(path)

    def fix(m: re.Match) -> str:
        href = m.group(1)
        if re.match(r"^[a-z]+:|^#|^/", href):
            return m.group(0)
        target, _, anchor = href.partition("#")
        resolved = posixpath.normpath(posixpath.join(base, target)) if target else path
        frag = f"#{anchor}" if anchor else ""
        if resolved in docs:
            return f'href="/docs/{resolved}{frag}"'
        if (REPO / resolved).exists():
            return f'href="{GITHUB}{resolved}{frag}" target="_blank" rel="noopener"'
        return m.group(0)

    return re.sub(r'href="([^"]+)"', fix, html)


def render(path: str) -> str | None:
    """The doc as a page, or None if it isn't a servable doc."""
    import markdown

    docs = allowed()
    if path not in docs:
        return None
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"])
    body = md.convert((REPO / path).read_text())
    # Mermaid blocks: render as diagrams in the browser.
    body = re.sub(
        r'<pre><code class="language-mermaid">(.*?)</code></pre>',
        lambda m: f'<pre class="mermaid">{m.group(1)}</pre>',
        body,
        flags=re.DOTALL,
    )
    body = _rewrite_links(body, path, docs)
    nav = "".join(
        f'<li><a href="/docs/{p}"{" aria-current=page" if p == path else ""}>{escape(t)}</a></li>'
        for p, t in docs.items()
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(docs[path])} · Clayzer</title>
<link rel="icon" href="/static/favicon.ico">
<link rel="stylesheet" href="/static/style.css"><link rel="stylesheet" href="/static/docs.css">
</head><body>
<header class="top"><div class="brand"><a href="/" class="home-link"><strong>Clayzer</strong></a></div>
<nav><a href="/#/how">← How it works</a><a href="/">Overview</a></nav>
<div class="store mono">{escape(path)}</div></header>
<div class="docs-layout"><aside class="docs-nav"><h3>Docs</h3><ul>{nav}</ul></aside>
<article class="doc">{body}</article></div>
<script src="{MERMAID}"></script>
<script>if (window.mermaid) {{ mermaid.initialize({{ startOnLoad: true, theme: "neutral" }}); }}
// Mermaid renders after load, which shifts the page: re-jump to the linked section.
if (location.hash) setTimeout(() => document.getElementById(location.hash.slice(1))?.scrollIntoView(), 600);</script>
</body></html>"""


def anchors(path: str) -> set[str]:
    """Every section anchor in a doc, for checking links into it."""
    html = render(path) or ""
    return set(re.findall(r'<h[1-6] id="([^"]+)"', html))
