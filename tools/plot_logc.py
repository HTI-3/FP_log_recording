#!/usr/bin/env python3
"""Plot the Log C tables against the stock curve: input vs output.

    Stretch (all of 0..255 over the usable input) against spec-exact (the form
    proven on the camera) and the stock curve #82 read out of the dump.

    python3 tools/plot_logc.py            # docs/logc_curves{,_dark}.png + .csv
    python3 tools/plot_logc.py --ei 400

Three panels, one axis each -- never a dual axis:

  a  the table as written      input index 0..2047  ->  output 0..8190
  b  read as a log curve       the same, with the input in STOPS below index
                               1918, where a log curve is a straight line
  c  where the hardware reads  index 0..160, with the 65-knot sampling every
                               32 entries, and what the stretch curve becomes if
                               the hardware interpolates linearly between knots

Every curve comes out of tools/logc.py -- the same definitions the cards are
built from -- and the stock curve is read out of the DRAM dump, not modelled.
The CSV beside the images is the table view: every entry of every curve.
"""
import argparse, math, pathlib, sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'tools'))
import logc

DUMP = REPO / 'results/dram_21_09_2026/dram_C0000000.bin'
W, N, VMAX, KNOT = logc.WHITE_INDEX, logc.TABLE_N, logc.TABLE_MAX, 32

# Chart chrome and categorical slots 1-2 from the dataviz reference palette,
# validated for both modes (CVD dE 24.7 light / 26.8 dark). The stock curve is a
# REFERENCE, so it wears muted ink rather than a categorical hue.
THEME = {
    'light': dict(surface='#fcfcfb', ink='#0b0b0b', ink2='#52514e', muted='#898781',
                  grid='#e1e0d9', axis='#c3c2b7', new='#2a78d6', spec='#eb6834'),
    'dark':  dict(surface='#1a1a19', ink='#ffffff', ink2='#c3c2b7', muted='#898781',
                  grid='#2c2c2a', axis='#383835', new='#3987e5', spec='#d95926'),
}


def stock_table():
    with DUMP.open('rb') as f:
        f.seek(0xC0971F34 - 0xC0000000 + 82 * 0x1000)
        return np.frombuffer(f.read(N * 2), dtype='<u2').astype(float)


def code_tick(v):
    """Table code with its 8-bit equivalent -- one axis, two readings."""
    return f'{int(v)}\n({round(v / VMAX * 255)})'


def style(ax, t, title, xlabel):
    ax.set_facecolor(t['surface'])
    ax.grid(True, color=t['grid'], linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'):
        ax.spines[s].set_color(t['axis'])
    ax.tick_params(colors=t['muted'], labelsize=7.5, length=0)
    ax.set_title(title, color=t['ink'], fontsize=10, loc='left', pad=8,
                 fontweight='semibold')
    ax.set_xlabel(xlabel, color=t['ink2'], fontsize=8)
    ax.set_ylabel('output: table code  (8-bit)', color=t['ink2'], fontsize=8)
    yt = [0, 2048, 4096, 6144, VMAX]
    ax.set_yticks(yt)
    ax.set_yticklabels([code_tick(v) for v in yt])


def end_label(ax, t, x, y, text, dy=0):
    """Direct label in TEXT ink -- identity is carried by the line and legend."""
    ax.annotate(text, (x, y), xytext=(6, dy), textcoords='offset points',
                color=t['ink2'], fontsize=7.5, va='center')


def plot(mode, ei, out):
    t = THEME[mode]
    st = stock_table()
    sp = np.array(logc.camera_table(ei), float)
    ft = np.array(logc.camera_table(ei, stretch=True), float)
    idx = np.arange(N)
    lw = 1.6

    plt.rcParams['font.family'] = ['Helvetica Neue', 'Arial', 'DejaVu Sans']
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.2), facecolor=t['surface'])
    fig.subplots_adjust(left=0.06, right=0.965, top=0.76, bottom=0.14, wspace=0.34)

    lo, hi = logc.stretch_span(ei)
    c8 = lambda v: round(v / VMAX * 255)
    cps = lambda tb: c8(tb[690]) - c8(tb[345])
    fig.text(0.06, 0.95, f'fpLog: stretch vs spec-exact ARRI Log C V3, EI {ei}',
             color=t['ink'], fontsize=13, fontweight='semibold')
    fig.text(0.06, 0.905,
             f'Both use the same input mapping (index {W} = diffuse white). Stretch '
             f'only moves the output: Log C {lo:.4f}..{hi:.4f} fills 0..255 '
             f'(x{1 / (hi - lo):.2f}), {cps(ft)} codes per stop around grey '
             f'instead of {cps(sp)}.',
             color=t['ink2'], fontsize=8.5)

    # ---- a: as written -----------------------------------------------------
    ax = axes[0]
    style(ax, t, 'a  The table as written', 'input: table index')
    ax.plot(idx, st, color=t['muted'], lw=1.2, ls=(0, (4, 3)))
    ax.plot(idx, sp, color=t['spec'], lw=lw)
    ax.plot(idx, ft, color=t['new'], lw=lw)
    ax.axvline(W, color=t['axis'], lw=0.8)
    ax.annotate(f'index {W}: diffuse white\n#82 and stretch reach full scale', (W, 900), xytext=(-6, 0),
                textcoords='offset points', ha='right', color=t['muted'], fontsize=7)
    ax.set_xlim(0, N - 1)
    ax.set_ylim(0, VMAX * 1.03)
    ax.set_xticks([0, 512, 1024, 1536, W])
    end_label(ax, t, N - 1, sp[-1], 'spec-exact')

    # ---- b: in stops -------------------------------------------------------
    ax = axes[1]
    style(ax, t, 'b  Read as a log curve', f'input: stops below index {W}')
    m = idx >= 1
    s = np.log2(idx[m] / W)
    ax.plot(s, st[m], color=t['muted'], lw=1.2, ls=(0, (4, 3)))
    ax.plot(s, sp[m], color=t['spec'], lw=lw)
    ax.plot(s, ft[m], color=t['new'], lw=lw)
    ax.axvline(0, color=t['axis'], lw=0.8)
    ax.set_xlim(s[0], math.log2((N - 1) / W) + 0.05)
    ax.set_ylim(0, VMAX * 1.03)
    ax.set_xticks([-10, -8, -6, -4, -2, 0])
    end_label(ax, t, s[-1], ft[-1], 'stretch', dy=-4)
    end_label(ax, t, s[-1], sp[-1], 'spec-exact')
    ax.annotate('log C is straight here only above ~-4 stops;\n'
                'the bend below is ARRI\'s own toe, by design', (-10.4, 7000),
                color=t['muted'], fontsize=7)

    # ---- c: where the hardware samples -------------------------------------
    ax = axes[2]
    style(ax, t, 'c  Where the hardware reads it', 'input: table index (zoom)')
    z = idx <= 160
    knots = np.arange(0, 161, KNOT)
    ax.plot(idx[z], st[z], color=t['muted'], lw=1.2, ls=(0, (4, 3)))
    ax.plot(idx[z], sp[z], color=t['spec'], lw=lw)
    ax.plot(idx[z], ft[z], color=t['new'], lw=lw)
    # what the stretch curve becomes if only every 32nd entry is read and the
    # hardware interpolates linearly between them -- the open risk, drawn
    ax.plot(knots, ft[knots], color=t['new'], lw=1.0, ls=(0, (1, 2)))
    ax.scatter(knots, ft[knots], s=22, color=t['new'], zorder=3,
               edgecolors=t['surface'], linewidths=1.5)
    for k in knots:
        ax.axvline(k, color=t['grid'], lw=0.8, zorder=0)
    seg = round(ft[KNOT] / VMAX * 255) - round(ft[0] / VMAX * 255)
    ax.annotate(f'first knot segment: {seg} of 255 codes\n'
                f'(stock: {round(st[KNOT] / VMAX * 255)})',
                (KNOT, ft[KNOT]), xytext=(8, -26), textcoords='offset points',
                color=t['ink2'], fontsize=7.5)
    cut = logc.EXPOSURE[ei][0] * W          # Log C's toe ends here
    ax.axvline(cut, color=t['axis'], lw=0.8, ls=(0, (2, 2)))
    ax.annotate(f'Log C toe ends\nat index {cut:.0f}', (cut, 7300), xytext=(4, 0),
                textcoords='offset points', color=t['ink2'], fontsize=7)
    ax.set_xlim(0, 160)
    ax.set_ylim(0, VMAX * 1.03)
    ax.set_xticks(knots)

    # ---- legend: always present for >= 2 series ----------------------------
    handles = [Line2D([], [], color=t['new'], lw=lw),
               Line2D([], [], color=t['spec'], lw=lw),
               Line2D([], [], color=t['muted'], lw=1.2, ls=(0, (4, 3))),
               Line2D([], [], color=t['new'], lw=1.0, ls=(0, (1, 2)),
                      marker='o', markersize=4.5, markeredgecolor=t['surface'])]
    labels = ['stretch (black..white onto 0..255)',
              'spec-exact (bit-exact ARRI, ships)',
              'stock curve #82 (sRGB, from the dump)',
              'stretch, if read only at every 32nd entry']
    leg = fig.legend(handles, labels, loc='upper left', bbox_to_anchor=(0.055, 0.885),
                     ncol=4, frameon=False, fontsize=8, handlelength=2.6,
                     columnspacing=2.2)
    for tx in leg.get_texts():
        tx.set_color(t['ink2'])

    fig.savefig(out, dpi=200, facecolor=t['surface'])
    plt.close(fig)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ei', type=int, default=800, choices=sorted(logc.EXPOSURE))
    ap.add_argument('--out', type=pathlib.Path, default=REPO / 'docs')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    suffix = '' if a.ei == 800 else f'_ei{a.ei}'
    for mode in ('light', 'dark'):
        p = a.out / f'logc_curves{suffix}{"_dark" if mode == "dark" else ""}.png'
        print('wrote', plot(mode, a.ei, p))

    # the table view: every entry of every curve plotted
    st = stock_table()
    sp = logc.camera_table(a.ei)
    ft = logc.camera_table(a.ei, stretch=True)
    csv = a.out / f'logc_curves{suffix}.csv'
    with csv.open('w') as fh:
        fh.write('index,stops_below_1918,stock_82,spec_exact,stretch,'
                 'stock_82_8bit,spec_exact_8bit,stretch_8bit\n')
        for i in range(N):
            sb = f'{math.log2(i / W):.4f}' if i else ''
            fh.write(f'{i},{sb},{int(st[i])},{sp[i]},{ft[i]},'
                     f'{round(st[i] / VMAX * 255)},{round(sp[i] / VMAX * 255)},'
                     f'{round(ft[i] / VMAX * 255)}\n')
    print('wrote', csv)
    return 0


if __name__ == '__main__':
    sys.exit(main())
