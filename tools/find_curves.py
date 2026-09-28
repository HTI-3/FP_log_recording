#!/usr/bin/env python3
"""Find tone-curve / gamma lookup tables in a memory image.

    tools/find_curves.py firmware_C0000000.bin --base 0xC0000000
    tools/find_curves.py a.bin b.bin --diff        # what changed between two states
    tools/find_curves.py --self-test

This answers PLAN.md §8 question 3 -- "is there a programmable tone curve in the
video path?" -- without needing to know where to look.

A tone curve has a shape almost nothing else in memory has: a long run of
**monotonically non-decreasing** values, at a regular element width, spanning a
sensible output range, with a smooth second derivative. Code is not monotonic.
Pointers are not monotonic. Image data is not monotonic. A gamma LUT is.

The --diff mode is the sharp instrument: dump the same region twice with the
camera in two different colour modes and compare. A table that CHANGES with
colour mode is a live, writable tone curve -- which is exactly the thing the
project needs, and finding it this way needs no disassembly at all.
"""
import argparse, pathlib, sys
import numpy as np

WIDTHS = {1: np.uint8, 2: np.uint16, 4: np.uint32}
# lengths worth calling out -- the usual LUT sizes, with and without an endpoint
NOTABLE = {17, 33, 64, 65, 128, 129, 256, 257, 512, 513, 1024, 1025, 4096, 4097}


def runs_of_monotonic(v, min_len):
    """Start/stop indices of maximal non-decreasing runs of length >= min_len."""
    if v.size < min_len:
        return []
    ok = np.diff(v.astype(np.int64)) >= 0
    # boundaries where monotonicity breaks
    brk = np.flatnonzero(~ok)
    # A run ENDS at the element before the break: v[brk] > v[brk+1], so the run
    # is [start .. brk] inclusive. Using brk+1 here absorbed the element that
    # broke monotonicity, which lengthened every run by one and wrecked the
    # normalisation -- the self-test caught it as a bad gamma fit.
    starts = np.concatenate(([0], brk + 1))
    stops = np.concatenate((brk, [v.size - 1]))
    lens = stops - starts + 1
    keep = lens >= min_len
    return list(zip(starts[keep], stops[keep]))


def trim_tail(v, min_len, factor=8.0):
    """Drop trailing elements whose step dwarfs the table's own step size.

    A run detector absorbs whatever follows the table if it happens to be
    larger -- after a 0..4095 ramp, 94% of random u16 values continue the run.
    A real LUT's steps vary smoothly, so a final step many times the median is
    the neighbour, not the table. Only the tail is trimmed: a gamma curve's
    FIRST steps are legitimately large.
    """
    while v.size > min_len:
        d = np.diff(v.astype(np.int64))
        med = float(np.median(d))
        if med <= 0 or d[-1] <= factor * med:
            break
        v = v[:-1]
    return v


def score(v):
    """Crude shape report: rise, how much of it strictly increases, best-fit gamma."""
    v = v.astype(np.float64)
    lo, hi = v[0], v[-1]
    if hi <= lo:
        return None
    strict = float(np.mean(np.diff(v) > 0))
    x = np.linspace(0, 1, v.size)
    y = (v - lo) / (hi - lo)
    m = (x > 0.02) & (x < 0.98) & (y > 0)
    gamma = float(np.median(np.log(y[m]) / np.log(x[m]))) if m.sum() > 8 else float('nan')
    # smoothness: a LUT is smooth; a coincidental sorted region is not
    d2 = np.abs(np.diff(y, 2))
    smooth = float(np.mean(d2 < (3.0 / v.size)))
    # How well does that gamma ACTUALLY fit? A clipped linear ramp fits a power
    # law at about 0.5 while being nothing of the kind -- 0xC07851EC in the real
    # dump is linear with slope 50 and then flat at 32767, and the bare gamma
    # column called it 0.50. Report the residual and the flat fraction so the
    # number cannot be read on its own.
    resid = float(np.max(np.abs(y - x ** gamma))) if gamma == gamma else float('nan')
    flat = float(np.mean(np.diff(v) == 0))
    shape = ('clipped' if flat > 0.15 else
             'linear' if float(np.max(np.abs(y - x))) < 0.03 else
             'CURVE' if resid < 0.02 else '?')
    return dict(lo=lo, hi=hi, strict=strict, gamma=gamma, smooth=smooth,
                resid=resid, flat=flat, shape=shape)


def scan(data, base, min_len=32, min_strict=0.5, min_smooth=0.8):
    """Candidate tables, naturally aligned only, de-duplicated across widths.

    Alignment is enforced because a real table is aligned, and because reading a
    u16 table at offset+1 yields a sequence that is still monotonic -- the
    self-test found fifty such phantoms before this was fixed.

    Widths are then de-duplicated: an increasing u16 table read as u32 is also
    increasing, so the same bytes appear at 2 and 4 bytes wide. Where byte
    ranges overlap, the candidate with the MOST entries wins -- the finer
    element size is the one that actually explains the data.
    """
    cand = []
    for w, dt in WIDTHS.items():
        v = np.frombuffer(data, dtype=dt, count=len(data) // w)
        for s, e in runs_of_monotonic(v, min_len):
            seg = trim_tail(v[s:e + 1], min_len)
            sc = score(seg)
            if not sc or sc['strict'] < min_strict or sc['smooth'] < min_smooth:
                continue
            n = int(seg.size)
            e = s + n - 1
            cand.append(dict(addr=base + s * w, width=w, n=n,
                             _lo=s * w, _hi=(e + 1) * w, **sc))

    cand.sort(key=lambda r: (-r['n'], r['width']))
    out, taken = [], []
    for r in cand:
        if any(r['_lo'] < hi and lo < r['_hi'] for lo, hi in taken):
            continue
        taken.append((r['_lo'], r['_hi']))
        out.append({k: v for k, v in r.items() if not k.startswith('_')})
    out.sort(key=lambda r: (r['shape'] != 'CURVE', -(r['n'] in NOTABLE), -r['n']))
    return out


def show(rows, limit=40):
    if not rows:
        print('  no candidate tables')
        return
    print(f'  {"address":>10}  {"w":>1} {"entries":>7}  {"first":>7} {"last":>10} '
          f'{"~gamma":>7} {"resid":>6} {"flat":>5}  shape')
    for r in rows[:limit]:
        star = ' *' if r['n'] in NOTABLE else '  '
        g = f"{r['gamma']:.3f}" if r['gamma'] == r['gamma'] else '    -'
        print(f"  0x{r['addr']:08X} {r['width']} {r['n']:7d}{star} {int(r['lo']):7d} "
              f"{int(r['hi']):10d} {g:>7} {r['resid']:6.3f} {r['flat']:5.2f}  {r['shape']}")
    if len(rows) > limit:
        print(f'  ... {len(rows) - limit} more')
    print('  * = a conventional LUT length.  shape: CURVE = a real power law')
    print('  (trust ~gamma); clipped = saturates, so the gamma column is')
    print('  meaningless there; linear = a straight ramp.')


def self_test():
    print('SELF-TEST\n')
    rng = np.random.default_rng(7)
    buf = bytearray(rng.integers(0, 256, 200_000, dtype=np.uint8).tobytes())

    x = np.linspace(0, 1, 257)
    gamma_lut = (np.power(x, 1 / 2.2) * 65535).astype('<u2')
    buf[0x4000:0x4000 + gamma_lut.nbytes] = gamma_lut.tobytes()

    ident = (np.linspace(0, 4095, 1025)).astype('<u2')
    buf[0x9000:0x9000 + ident.nbytes] = ident.tobytes()

    rows = scan(bytes(buf), 0xC0000000)
    show(rows, 12)

    got = {r['addr']: r for r in rows}
    ok = True
    planted = ((0xC0004000, gamma_lut.nbytes, 'gamma 1/2.2 LUT, 257 x u16', 257, 0.4545),
               (0xC0009000, ident.nbytes, 'identity ramp, 1025 x u16', 1025, 1.0))
    for want, nbytes, label, wantn, wantgamma in planted:
        hit = got.get(want)
        print(f"\n  planted {label} at 0x{want:08X}: "
              f"{'FOUND' if hit else 'MISSED'}")
        ok &= hit is not None
        if hit:
            print(f"    reported {hit['n']} entries (expected {wantn}), width "
                  f"{hit['width']} (expected 2), ~gamma {hit['gamma']:.3f} "
                  f"(expected {wantgamma:.3f})")
            ok &= hit['n'] == wantn and hit['width'] == 2
            ok &= abs(hit['gamma'] - wantgamma) < 0.06
    spans = [(a - 0xC0000000, a - 0xC0000000 + nb) for a, nb, *_ in planted]
    noise = [r for r in rows
             if not any(lo <= r['addr'] - 0xC0000000 < hi for lo, hi in spans)]
    print(f"\n  false positives in 200 KB of uniform random noise: {len(noise)}")
    ok &= len(noise) == 0
    print(f'\nSELF-TEST {"PASSED" if ok else "FAILED"}')
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('images', nargs='*', type=pathlib.Path)
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0xC0000000)
    ap.add_argument('--min-len', type=int, default=32)
    ap.add_argument('--diff', action='store_true',
                    help='two images of the same region: report tables that differ')
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.images:
        ap.error('give an image, or --self-test')

    if a.diff:
        if len(a.images) != 2:
            ap.error('--diff takes exactly two images')
        d1, d2 = (p.read_bytes() for p in a.images)
        if len(d1) != len(d2):
            ap.error('the two images must cover the same region')
        r1 = {(r['addr'], r['width'], r['n']): r for r in scan(d1, a.base, a.min_len)}
        r2 = scan(d2, a.base, a.min_len)
        changed = []
        for r in r2:
            k = (r['addr'], r['width'], r['n'])
            o = r1.get(k)
            off = r['addr'] - a.base
            if d1[off:off + r['n'] * r['width']] != d2[off:off + r['n'] * r['width']]:
                changed.append(r)
        print(f'candidate tables in image 2: {len(r2)}; '
              f'CHANGED between the two states: {len(changed)}\n')
        show(changed)
        print('\nA table that changes with the camera state is a LIVE one. If the two '
              'states were two colour modes, this is the tone curve.')
        return 0

    d = a.images[0].read_bytes()
    print(f'{a.images[0]}  {len(d):,} bytes at 0x{a.base:08X}\n')
    show(scan(d, a.base, a.min_len))
    return 0


if __name__ == '__main__':
    sys.exit(main())
