"""Portable SVG/CSV and optional PNG visualization, no plotting dependency required."""
from __future__ import annotations

import csv
from pathlib import Path


def write_trajectory(directory: Path, history: list[dict], baseline: float):
    directory = Path(directory)
    with (directory/'trajectory.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f)
        writer.writerow(['attempt','candidate_val_f1','best_so_far_val_f1','accepted'])
        for a in history:
            writer.writerow([a['attempt'],a['validation']['f1'],a['best_so_far_f1'],int(a['kept'])])
    w,h=840,380
    left,right,top,bottom=76,40,36,64
    lo,hi=0.0,1.0
    N=max(1,len(history))
    def cx(k): return left + k*(w-left-right)/N
    def cy(v): return h-bottom - (v-lo)/(hi-lo)*(h-top-bottom)
    candidates=[(0,baseline)]+[(r['attempt'],r['validation']['f1']) for r in history]
    bests=[(0,baseline)]+[(r['attempt'],r['best_so_far_f1']) for r in history]
    def points(items): return ' '.join(f'{cx(x):.1f},{cy(y):.1f}' for x,y in items)
    elems=['<svg xmlns="http://www.w3.org/2000/svg" width="840" height="380" viewBox="0 0 840 380">',
           '<rect width="840" height="380" fill="#ffffff"/>',
           '<text x="76" y="22" font-family="Arial" font-size="17" fill="#0f172a">Validation F1: Candidate vs Best So Far</text>']
    for v in (0,.25,.5,.75,1.0):
        elems.append(f'<line x1="{left}" y1="{cy(v):.1f}" x2="{w-right}" y2="{cy(v):.1f}" stroke="#e2e8f0"/>')
        elems.append(f'<text x="38" y="{cy(v)+4:.1f}" font-family="Arial" font-size="12" fill="#64748b">{v:.2f}</text>')
    for i in range(N+1):
        elems.append(f'<text x="{cx(i):.1f}" y="{h-36}" text-anchor="middle" font-family="Arial" font-size="12" fill="#64748b">{i}</text>')
    elems.extend([
        f'<polyline points="{points(candidates)}" fill="none" stroke="#64748b" stroke-width="2"/>',
        f'<polyline points="{points(bests)}" fill="none" stroke="#0d9488" stroke-width="3"/>',
    ])
    for r in history:
        x,y=cx(r['attempt']),cy(r['validation']['f1'])
        color='#0d9488' if r['kept'] else '#dc2626'
        elems.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}"/>')
    elems.append('<text x="76" y="352" font-family="Arial" font-size="12" fill="#64748b">Gray: candidates</text>')
    elems.append('<text x="220" y="352" font-family="Arial" font-size="12" fill="#0d9488">Teal: best-so-far</text>')
    elems.append('<text x="385" y="352" font-family="Arial" font-size="12" fill="#dc2626">Red: rejected</text>')
    elems.append('</svg>')
    (directory/'trajectory.svg').write_text('\n'.join(elems),encoding='utf-8')
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig,ax=plt.subplots(figsize=(8.4,3.8))
        ax.plot([x for x,_ in candidates], [y for _,y in candidates],marker='o',label='Candidate val F1')
        ax.plot([x for x,_ in bests], [y for _,y in bests],marker='o',label='Best-so-far val F1')
        ax.set(xlabel='Experiment attempt',ylabel='Validation F1',ylim=(0,1),title='Bounded research search')
        ax.legend()
        fig.tight_layout()
        fig.savefig(directory/'trajectory.png',dpi=150)
        plt.close(fig)
    except ImportError:
        pass
