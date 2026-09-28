#!/usr/bin/env python3
"""Plot the 89 tone curves extracted from the DRAM dump: input vs output.

    python3 tools/plot_curves.py
"""
import pathlib
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import colormaps, colors as mcolors
from matplotlib.cm import ScalarMappable

HERE = pathlib.Path(__file__).resolve().parent.parent
CURVES = HERE / 'results/dram_21_09_2026/curves/all_curves.npy'
LIVE = 82                      # the curve three live pointers select
BANK, STRIDE = 0xC0971F34, 0x1000

# Sequential ramp, single hue, light->dark: the curves are an ORDERED family,
# not 89 categorical identities. Truncated at 0.55 so the lightest step still
# has usable contrast on a light surface.
RAMP = colormaps['Blues']
LO, HI = 0.55, 1.0
ACCENT_L, ACCENT_D = '#d94801', '#fd8d3c'


def draw(M, dark, out):
    surf, ink, muted, grid = (('#14161a', '#f2f4f7', '#9aa3ad', '#2a2f37') if dark
                              else ('#fcfcfb', '#1b1f24', '#5c6670', '#e3e6ea'))
    accent = ACCENT_D if dark else ACCENT_L
    n, N = M.shape
    x = np.arange(N)

    fig, ax = plt.subplots(figsize=(9, 6.2), dpi=170)
    fig.patch.set_facecolor(surf)
    ax.set_facecolor(surf)

    for i in range(n):
        if i == LIVE:
            continue
        ax.plot(x, M[i], lw=0.7, color=RAMP(LO + (HI - LO) * i / (n - 1)),
                alpha=0.85, solid_capstyle='round')
    ax.plot(x, M[LIVE], lw=2.4, color=accent, solid_capstyle='round', zorder=5)
    ax.annotate(f'curve #{LIVE}  (live — 0x{BANK + LIVE * STRIDE:08X})',
                xy=(N * 0.62, M[LIVE][int(N * 0.62)]),
                xytext=(N * 0.34, M[LIVE][int(N * 0.62)] - 1900),
                color=accent, fontsize=9.5, fontweight='medium',
                arrowprops=dict(arrowstyle='-', color=accent, lw=1.2))

    ax.set_xlim(0, N - 1)
    ax.set_ylim(0, 8400)
    ax.set_xlabel('input  (11-bit index, 0–2047)', color=muted, fontsize=10)
    ax.set_ylabel('output  (13-bit, 0–8190)', color=muted, fontsize=10)
    ax.set_title('SIGMA fp Ver.5.02 — 89 ISP tone curves',
                 color=ink, fontsize=13, fontweight='semibold', loc='left', pad=14)
    ax.text(0, 1.015, f'0x{BANK:08X} + n×0x{STRIDE:X}, 2048 × u16 each',
            transform=ax.transAxes, color=muted, fontsize=9)
    ax.grid(True, color=grid, lw=0.7, alpha=0.9)
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'):
        ax.spines[s].set_color(grid)
    ax.tick_params(colors=muted, labelsize=9)

    sm = ScalarMappable(cmap=mcolors.LinearSegmentedColormap.from_list(
        'r', [RAMP(LO + (HI - LO) * t / 255) for t in range(256)]),
        norm=mcolors.Normalize(0, n - 1))
    cb = fig.colorbar(sm, ax=ax, pad=0.015, fraction=0.035)
    cb.set_label('curve index n', color=muted, fontsize=9.5)
    cb.ax.tick_params(colors=muted, labelsize=8.5)
    cb.outline.set_edgecolor(grid)

    fig.tight_layout()
    fig.savefig(out, facecolor=surf)
    plt.close(fig)
    print(f'wrote {out}')


if __name__ == '__main__':
    M = np.load(CURVES).astype(float)
    print(f'{M.shape[0]} curves × {M.shape[1]} entries')
    d = HERE / 'results/dram_21_09_2026'
    draw(M, False, d / 'tone_curves.png')
    draw(M, True, d / 'tone_curves_dark.png')
