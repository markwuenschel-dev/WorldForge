#!/usr/bin/env python3
"""operator_view.py — v2.1 OperatorForge shared static-HTML rendering helpers.

The dashboard is LOCAL and STATIC (handoff §3): self-contained HTML files with
inlined CSS, no server, no external assets. Every builder (build_dashboard,
build_failure_index, build_asset_ownership, build_route_view) renders through
these helpers so the pages read as one system and the broken-link validator has a
single link convention to check.

No third-party deps; stdlib only. Links are relative paths between generated
pages under procedural/reports/operator/dashboard/**.
"""

import html
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "dashboard"

# One inlined stylesheet, theme-aware, terminal/editorial. No external fonts.
_CSS = """
:root { color-scheme: light dark; --bg:#0e1116; --fg:#d7dde3; --muted:#8b97a5;
  --card:#171c23; --line:#252c36; --accent:#5aa9ff; --pass:#3fb950; --fail:#f85149;
  --blocked:#d29922; --absent:#6e7681; }
@media (prefers-color-scheme: light) { :root { --bg:#f6f8fa; --fg:#1f2328;
  --muted:#57606a; --card:#ffffff; --line:#d0d7de; --accent:#0969da; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:14px/1.5 ui-monospace,"SF Mono",Menlo,Consolas,monospace; }
.wrap { max-width:1100px; margin:0 auto; padding:24px; }
h1,h2,h3 { font-weight:600; line-height:1.25; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:16px; margin:28px 0 10px;
  border-bottom:1px solid var(--line); padding-bottom:6px; }
a { color:var(--accent); text-decoration:none; } a:hover { text-decoration:underline; }
.muted { color:var(--muted); } .sub { color:var(--muted); margin:0 0 18px; font-size:13px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:12px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px;
  padding:14px 16px; }
.card h3 { margin:0 0 8px; font-size:14px; }
.kv { display:flex; justify-content:space-between; gap:12px; padding:2px 0;
  border-bottom:1px dashed var(--line); }
.kv:last-child { border-bottom:0; } .kv .k { color:var(--muted); }
.badge { display:inline-block; padding:1px 8px; border-radius:999px; font-size:12px;
  font-weight:600; }
.b-pass{ background:rgba(63,185,80,.15); color:var(--pass); }
.b-fail{ background:rgba(248,81,73,.15); color:var(--fail); }
.b-blocked{ background:rgba(210,153,34,.15); color:var(--blocked); }
.b-absent,.b-not_run{ background:rgba(110,118,129,.15); color:var(--absent); }
table { width:100%; border-collapse:collapse; }
.scroll { overflow-x:auto; }
th,td { text-align:left; padding:6px 10px; border-bottom:1px solid var(--line);
  white-space:nowrap; }
th { color:var(--muted); font-weight:600; }
code { background:var(--card); border:1px solid var(--line); border-radius:4px;
  padding:1px 5px; font-size:12px; }
.foot { margin-top:32px; color:var(--muted); font-size:12px;
  border-top:1px solid var(--line); padding-top:12px; }
""".strip()


def esc(s):
    return html.escape(str(s), quote=True)


def badge(status):
    s = str(status)
    return '<span class="badge b-{}">{}</span>'.format(esc(s), esc(s))


def link(href, text):
    return '<a href="{}">{}</a>'.format(esc(href), esc(text))


def kv(k, v):
    return '<div class="kv"><span class="k">{}</span><span class="v">{}</span></div>'.format(
        esc(k), v if isinstance(v, str) and v.startswith("<") else esc(v))


def page(title, body, subtitle="", git_sha="", back=None):
    crumb = (link(back[0], back[1]) + " &nbsp;/&nbsp; " if back else "")
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{css}</style></head><body><div class="wrap">
<p class="muted">{crumb}OperatorForge</p>
<h1>{title}</h1><p class="sub">{sub}</p>
{body}
<div class="foot">WorldForge v2.1 OperatorForge — static operator dashboard.
git_sha <code>{sha}</code>. Local/static; indexes existing evidence, does not
make stale evidence true.</div>
</div></body></html>""".format(
        title=esc(title), css=_CSS, crumb=crumb, sub=esc(subtitle),
        body=body, sha=esc(git_sha[:12] if git_sha else "unknown"))


def write_page(relpath, htmltext):
    out = DASHBOARD_DIR / relpath
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(htmltext, encoding="utf-8")
    return out
