"""Dependency-free, self-contained, evidence-first reports from saved summaries.

Only safe, explicitly selected summary fields are displayed. This module does
not fetch URLs, execute run artifacts, access OpenRouter or read candidate code.
"""
from __future__ import annotations

from html import escape
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

MAX_SUMMARY_BYTES = 4_000_000


def _h(value: Any) -> str:
    return escape(str(value), quote=True)


def _float(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, bool):
        return default
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return v if math.isfinite(v) else default


def _f1(value: Any) -> str:
    n = _float(value)
    return f"{n:.4f}" if n is not None and 0 <= n <= 1 else "n/a"


def _f1_number(value: Any) -> float | None:
    number = _float(value)
    return number if number is not None and 0 <= number <= 1 else None


def _safe_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def load_summary(run_dir: Path) -> dict:
    path = Path(run_dir) / "summary.json"
    if not path.is_file() or not path.stat().st_size <= MAX_SUMMARY_BYTES:
        raise ValueError("Run summary is missing or exceeds the safe report size")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Run summary must be valid UTF-8 JSON") from exc
    if not isinstance(obj, dict) or obj.get("demo") not in ("rd", "se"):
        raise ValueError("Unsupported run summary schema or demo kind")
    if not isinstance(obj.get("history"), list) or not isinstance(obj.get("details"), dict):
        raise ValueError("Run summary is missing required history/details")
    if len(obj["history"]) > 1000:
        raise ValueError("Run contains too many attempts for static report")
    return obj


_CSS = """
:root{color-scheme:light;--ink:#162230;--paper:#f8f7f4;--muted:#556370;
--line:#d8dedb;--blue:#2859a1;--teal:#087a70;--red:#a33f35;--gray:#e9ece9}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;line-height:1.5}
main{max-width:1140px;margin:auto;padding:44px 48px 64px}
.header{border-top:6px solid var(--ink);padding-top:24px;margin-bottom:44px}
.eyebrow{font-size:12px;font-weight:700;letter-spacing:.18em;text-transform:uppercase;color:var(--blue)}
h1{font-size:clamp(32px,4vw,60px);letter-spacing:-.055em;line-height:1.08;margin:12px 0 17px;font-weight:760}
h2{font-size:clamp(22px,2.8vw,34px);letter-spacing:-.04em;margin:0 0 16px}
p{margin:0 0 12px}.lead{font-size:17px;color:var(--muted);max-width:840px}
.meta{display:flex;flex-wrap:wrap;gap:9px;margin-top:22px}
.chip{border:1px solid var(--line);padding:6px 11px;border-radius:2px;font:600 12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.chip.source{background:var(--ink);color:white;border-color:var(--ink)}
section{margin:32px 0 42px}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.metric{border-top:2px solid var(--ink);padding:14px 0}.metric-label{font-size:12px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase}
.metric-value{font-size:clamp(24px,3vw,43px);letter-spacing:-.055em;font-weight:750;margin-top:5px;overflow-wrap:anywhere}
.metric-sub{font-size:13px;color:var(--muted)}.evidence{border-left:4px solid var(--teal);padding:12px 16px;background:#edf4f1;margin-top:20px}
.evidence.warn{border-color:var(--red);background:#f9efed}.small{font-size:13px;color:var(--muted)}
.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:15px}
th{text-align:left;text-transform:uppercase;font-size:11px;letter-spacing:.11em;color:var(--muted);padding:12px 14px 12px 0;border-bottom:2px solid var(--ink);white-space:nowrap}
td{padding:14px 14px 14px 0;border-bottom:1px solid var(--line);white-space:nowrap}
tr:last-child td{border-bottom:1px solid var(--ink)}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}
.good{color:var(--teal);font-weight:700}.bad{color:var(--red);font-weight:700}.neutral{color:var(--muted)}
.chart{padding:14px 0 0}.chart svg{display:block;width:100%;height:auto;max-height:480px}
.legend{display:flex;gap:24px;flex-wrap:wrap;font-size:13px;color:var(--muted);margin:8px 0}
.swatch{display:inline-block;width:22px;border-top:3px solid;vertical-align:middle;margin-right:7px}
.footer{border-top:1px solid var(--line);padding-top:20px;font-size:13px;color:var(--muted)}
@media(max-width:760px){main{padding:28px 20px 44px}.metrics{grid-template-columns:1fr 1fr}.metric-value{font-size:30px}}
@media print{main{padding:16px 20px;max-width:none}section{break-inside:avoid}.chart svg{max-height:350px}}
"""


def _base(title: str, summary: dict, interior: str) -> str:
    details = summary["details"]
    kind = str(details.get("demo_kind", "UNSPECIFIED"))
    source = ("LIVE MODEL PROPOSALS" if kind == "LIVE_MODEL_PROPOSALS" else
              "PREAUTHORED OFFLINE CANDIDATES" if kind.startswith("PREAUTHORED") else
              "UNSPECIFIED PROPOSAL SOURCE")
    status = str(summary.get("status", "UNKNOWN"))
    run = str(summary.get("run_id", "unknown"))
    mode = str(summary.get("mode", "unknown"))
    notice = ("Live model proposals are evaluated as they arrive; performance varies by model and run."
              if kind == "LIVE_MODEL_PROPOSALS" else
              "Prepared proposals: results illustrate the verification policy; they are not evidence of autonomous model discovery."
              if kind.startswith("PREAUTHORED") else
              "Proposal provenance is unspecified in this summary; do not infer it is a live model result.")
    meta = (f'<div class="meta"><span class="chip source">{_h(source)}</span>'
            f'<span class="chip">MODE: {_h(mode)}</span><span class="chip">STATUS: {_h(status)}</span>'
            f'<span class="chip">RUN: {_h(run)}</span></div>')
    cost = _float(details.get("reported_api_cost_usd"))
    cost_text = f' · Provider-reported cost: USD {cost:.5f}' if cost is not None else ''
    footer = (f'<div class="footer">Generated from local <code>summary.json</code>, without network requests. '
              f'This view is not a hidden benchmark or a proof of correctness.{_h(cost_text)}'
              f' <br>Run context: <span class="mono">{_h(run)}</span></div>')
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;; img-src data:; base-uri &#39;none&#39;; form-action &#39;none&#39;">'
            f'<title>{_h(title)} | Loop Engineering</title><style>{_CSS}</style></head>'
            f'<body><main><header class="header"><div class="eyebrow">LOOP ENGINEERING / EVIDENCE REPORT</div>'
            f'<h1>{_h(title)}</h1><p class="lead">{_h(notice)}</p>{meta}</header>{interior}{footer}</main></body></html>')


def _metric(label: str, value: str, sub: str = "") -> str:
    return (f'<div class="metric"><div class="metric-label">{_h(label)}</div>'
            f'<div class="metric-value">{_h(value)}</div><div class="metric-sub">{_h(sub)}</div></div>')


def _status(value: Any) -> str:
    if value is None:
        return '<span class="neutral">NOT RUN</span>'
    if value is True:
        return '<span class="good">PASS</span>'
    if value is False:
        return '<span class="bad">FAIL</span>'
    return '<span class="neutral">UNKNOWN</span>'


def _se(summary: dict) -> str:
    history = _safe_list(summary["history"])
    status = str(summary.get("status", "?"))
    details = summary["details"]
    headline = 'Accepted under active policy' if status == 'ACCEPTED' else f'Ended: {status}'
    audit = details.get('posthoc_protected_audit_passed')
    msg = ('Public-only policy accepted a candidate that did not pass the independent acceptance checks.'
           if details.get('accepted_using_public_only') is True and audit is False else
           'A passing acceptance suite covers the implemented checks, not every possible input or property.'
           if status == 'ACCEPTED' and audit is True else
           'No universal correctness claim can be inferred from this run.')
    is_warning = details.get('accepted_using_public_only') is True and audit is False
    rows = []
    for index, item in enumerate(history):
        row = _safe_dict(item)
        attempt = row.get('attempt', index + 1)
        public = row.get('public_passed')
        protected = row.get('protected_passed')
        fingerprint = str(row.get('candidate_sha256', ''))[:12]
        rows.append(f'<tr><td class="mono">{_h(attempt)}</td><td>{_status(public)}</td>'
                    f'<td>{_status(protected)}</td><td class="mono">{_h(fingerprint)}</td></tr>')
    if not rows:
        rows = ['<tr><td colspan="4">No verified candidate has been recorded.</td></tr>']
    total = str(len(history))
    return (
        f'<section class="metrics">{_metric("Terminal decision", status, "Policy outcome")}'
        f'{_metric("Verified attempts", total, "Public checks first")}'
        f'{_metric("Acceptance checks", "10", "Finite reference vectors")}</section>'
        f'<section><h2>Candidate → public checks → acceptance checks</h2>'
        '<p class="small">Acceptance checks run only after public checks pass. NOT RUN is not equivalent to FAIL.</p>'
        '<div class="tablewrap"><table><thead><tr><th>Attempt</th><th>Public</th><th>Acceptance</th><th>Candidate SHA-256</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
        f'<div class="evidence{" warn" if is_warning else ""}"><strong>{_h(headline)}</strong><br>{_h(msg)}</div></section>'
        '<section><h2>What this establishes</h2>'
        '<p>This run reports finite, host-side test outcomes and the resulting policy decision. '
        'The proposer does not determine the acceptance verdict. Protected criteria are not passed to the proposer; '
        'they are not a secrecy guarantee in an open-source repository.</p></section>'
    )


def _chart(history: list, baseline: float | None) -> str:
    if baseline is None:
        return '<p>Baseline F1 was not available for plotting.</p>'
    samples: list[tuple[int, float, float, bool | None]] = [(0, baseline, baseline, None)]
    for index, entry in enumerate(history, 1):
        row = _safe_dict(entry)
        val = _f1_number(_safe_dict(row.get('validation')).get('f1'))
        best = _f1_number(row.get('best_so_far_f1'))
        if val is None or best is None:
            return '<p>Chart unavailable: one or more validation metrics are invalid.</p>'
        samples.append((index, val, best, row.get('kept')))
    width, height = 1040, 410
    left, right, top, bottom = 74, 32, 26, 60
    plot_w, plot_h = width - left - right, height - top - bottom
    n = max(1, len(samples) - 1)
    x = lambda i: left + i * plot_w / n
    y = lambda v: top + (1 - v) * plot_h
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Validation F1 by attempt: gray candidate versus teal best-so-far; starts at baseline, zero to one scale">']
    for f1 in (0, 0.25, 0.5, 0.75, 1):
        y0 = y(f1)
        parts.append(f'<line x1="{left}" y1="{y0:.1f}" x2="{width-right}" y2="{y0:.1f}" stroke="#d8dedb"/>')
        parts.append(f'<text x="{left-14}" y="{y0+5:.1f}" text-anchor="end" font-size="15" fill="#556370">{f1:.2f}</text>')
    for i in range(len(samples)):
        parts.append(f'<text x="{x(i):.1f}" y="{height-22}" text-anchor="middle" font-size="15" fill="#556370">{i}</text>')
    def poly(index):
        return ' '.join(f'{x(i):.1f},{y(row[index]):.1f}' for i,row in enumerate(samples))
    parts.append(f'<polyline points="{poly(1)}" fill="none" stroke="#64748b" stroke-width="3" stroke-dasharray="7 6"/>')
    parts.append(f'<polyline points="{poly(2)}" fill="none" stroke="#087a70" stroke-width="4"/>')
    for i, (_, candidate, best, kept) in enumerate(samples):
        cx, cy = x(i), y(candidate)
        fill = '#087a70' if kept is True else '#a33f35' if kept is False else '#162230'
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="{fill}"/>')
        parts.append(f'<circle cx="{cx:.1f}" cy="{y(best):.1f}" r="3" fill="#087a70"/>')
    parts.append('</svg>')
    return ''.join(parts)


def _rd(summary: dict) -> str:
    details = summary['details']
    history = _safe_list(summary['history'])
    baseline_f1 = _f1(_safe_dict(details.get('baseline_validation')).get('f1'))
    best_f1 = _f1(_safe_dict(details.get('best_validation')).get('f1'))
    rows = []
    for i, item in enumerate(history, 1):
        row = _safe_dict(item)
        cfg = _safe_dict(row.get('config'))
        decision = '<span class="good">KEEP</span>' if row.get('kept') is True else '<span class="bad">REJECT</span>'
        rows.append(f'<tr><td class="mono">{_h(row.get("attempt",i))}</td><td>{_h(cfg.get("feature_map", "?"))}</td>'
                    f'<td class="mono">{_f1(_safe_dict(row.get("validation")).get("f1"))}</td>'
                    f'<td>{decision}</td><td class="mono">{_f1(row.get("best_so_far_f1"))}</td></tr>')
    if not rows:
        rows = ['<tr><td colspan="5">No evaluated hypothesis has been recorded.</td></tr>']
    heldout = _safe_dict(details.get('heldout_report'))
    baseline_h = _f1(_safe_dict(heldout.get('baseline')).get('f1'))
    selected_h = _f1(_safe_dict(heldout.get('selected')).get('f1'))
    heldout_html = (
        f'<section><h2>Held-out evaluation</h2><p class="small">Consulted only after configuration selection. Not used in the search objective.</p>'
        f'<div class="metrics">{_metric("Baseline held-out F1", baseline_h)}'
        f'{_metric("Selected held-out F1", selected_h)}'
        f'{_metric("Held-out access count", str(details.get("heldout_access_count", "?")), "As recorded by this run")}'
        '</div><div class="evidence">A single synthetic seed is illustrative, not a statistical generalization claim.</div></section>'
        if heldout else '<section><h2>Held-out evaluation</h2><p>Not recorded. No held-out conclusion is available.</p></section>'
    )
    stop = str(details.get('stop_reason', 'not supplied'))
    return (
        f'<section class="metrics">{_metric("Baseline validation F1", baseline_f1)}'
        f'{_metric("Best-so-far validation F1", best_f1)}'
        f'{_metric("Attempts", str(len(history)), "Termination: " + str(summary.get("status", "?")))}</section>'
        f'<section><h2>Two distinct quantities</h2>'
        '<p class="small">Candidate validation F1 may decrease; stored best-so-far follows a strict-improvement selection rule. '
        'Monotonic best-so-far is not a proof of convergence.</p>'
        f'<div class="chart">{_chart(history, _f1_number(_safe_dict(details.get("baseline_validation")).get("f1")))}</div>'
        '<div class="legend"><span><span class="swatch" style="border-color:#64748b"></span>Candidate validation F1</span>'
        '<span><span class="swatch" style="border-color:#087a70"></span>Best-so-far validation F1</span>'
        '<span><span class="swatch" style="border-color:#a33f35"></span>Rejected candidate</span></div>'
        '<div class="tablewrap"><table><thead><tr><th>Attempt</th><th>Feature map</th><th>Candidate F1</th><th>Decision</th><th>Best-so-far F1</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
        f'<div class="evidence"><strong>Stop reason: {_h(stop)}.</strong> A bounded search may stop without reaching an optimum.</div></section>'
        f'{heldout_html}'
    )


def build_html(summary: dict) -> str:
    if summary.get('demo') == 'se':
        return _base('What constitutes correctness?', summary, _se(summary))
    if summary.get('demo') == 'rd':
        return _base('What constitutes improvement?', summary, _rd(summary))
    raise ValueError('Unknown demo in summary')


def write_html(run_dir: Path) -> Path:
    """Write report.html atomically inside the run folder. Never execute the run."""
    path = Path(run_dir).resolve()
    summary = load_summary(path)
    target = path / 'report.html'
    if target.is_symlink():
        raise ValueError('Refusing to overwrite symlinked HTML report')
    html = build_html(summary)
    # Avoid partial HTML when interrupted; do not use a shell or external renderer.
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path, prefix='.report-', suffix='.tmp', delete=False) as f:
            tmp = Path(f.name)
            f.write(html)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()
    return target


def build_se_comparison(left: dict, right: dict) -> str:
    """Contrast *the same prepared candidate prefix* under different policies.

    Refuse stochastic or nonmatching proposals so the page cannot mistakenly
    attribute model variability to the verifier policy.
    """
    if left.get('demo') != 'se' or right.get('demo') != 'se':
        raise ValueError('SE policy comparison requires two software-engineering runs')
    a, b = left['details'], right['details']
    if (a.get('demo_kind') != 'PREAUTHORED_FIXTURES' or
            b.get('demo_kind') != 'PREAUTHORED_FIXTURES'):
        raise ValueError('SE policy comparison supports only preauthored offline fixtures')
    lh, rh = left['history'], right['history']
    if not lh or not rh:
        raise ValueError('SE comparison requires at least one verified candidate per run')
    common = min(len(lh), len(rh))
    for i in range(common):
        l, r = _safe_dict(lh[i]), _safe_dict(rh[i])
        if (l.get('candidate_sha256') != r.get('candidate_sha256') or
                l.get('public_passed') != r.get('public_passed') or
                l.get('protected_passed') != r.get('protected_passed')):
            raise ValueError('SE comparison requires the same candidate and verifier results in the shared prefix')
    def card(title: str, run: dict) -> str:
        d = run['details']
        status = str(run.get('status', '?'))
        unsafe = d.get('accepted_using_public_only') is True and d.get('posthoc_protected_audit_passed') is False
        rows = []
        for h in run['history']:
            item = _safe_dict(h)
            rows.append(f'<tr><td class="mono">{_h(item.get("attempt", "?"))}</td>'
                        f'<td>{_status(item.get("public_passed"))}</td><td>{_status(item.get("protected_passed"))}</td></tr>')
        note = ('Accepted using public tests even though acceptance checks failed.' if unsafe else
                'The policy accepted only after its active criteria were satisfied.' if status == 'ACCEPTED' else
                'This policy did not reach acceptance in the recorded attempts.')
        return (f'<article class="comparison"><div class="eyebrow">{_h(title)}</div>'
                f'<h2>{_h(str(run.get("mode", "?")))}</h2><p class="lead">'
                f'{_h(status)} · {_h(len(run["history"]))} verified attempt(s)</p>'
                f'<table><thead><tr><th>Attempt</th><th>Public</th><th>Acceptance</th></tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table>'
                f'<div class="evidence{" warn" if unsafe else ""}">{_h(note)}</div>'
                f'<p class="small">Run {_h(run.get("run_id", "?"))}</p></article>')
    content = (
        '<section><h2>Same candidate sequence. Different acceptance authority.</h2>'
        '<p class="lead">This comparison uses the matching prefix of prepared candidates and verifier results. '
        'Only the acceptance policy varies. It is an illustrative counterexample, not an LLM performance study.</p>'
        '<div class="comparison-grid">' + card('RUN A', left) + card('RUN B', right) + '</div></section>'
        '<section><h2>Interpretation</h2>'
        '<p>Passing visible/public checks does not imply satisfying acceptance checks. '
        'A governed decision depends on evidence and policy, not on how confident the proposer sounds. '
        'The checks remain finite; neither mode establishes universal correctness.</p></section>'
    )
    # The one-pager uses the same isolated visual system, with no external assets.
    comparison_label = {
        'run_id': 'two offline runs', 'mode': 'policy comparison',
        'status': 'COMPARISON', 'details': {'demo_kind': 'PREAUTHORED_FIXTURES'},
    }
    base = _base('One task. Two policies.', comparison_label, content)
    return base.replace('</style>',
        '.comparison-grid{display:grid;grid-template-columns:1fr 1fr;gap:32px;margin-top:32px}'
        '.comparison{border-top:3px solid var(--ink);padding-top:18px;min-width:0}'
        '@media(max-width:760px){.comparison-grid{grid-template-columns:1fr}}'
        '</style>')


def write_se_comparison(left_dir: Path, right_dir: Path) -> Path:
    left = load_summary(left_dir)
    right = load_summary(right_dir)
    html = build_se_comparison(left, right)
    # Persist with the first run; both paths remain unchanged except for the new report.
    base = Path(left_dir).resolve()
    target = base / 'comparison.html'
    if target.is_symlink():
        raise ValueError('Refusing to overwrite symlinked comparison report')
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=base,
                                         prefix='.compare-', suffix='.tmp', delete=False) as handle:
            tmp = Path(handle.name)
            handle.write(html)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()
    return target
