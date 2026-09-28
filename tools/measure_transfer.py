#!/usr/bin/env python3
"""Recover the camera's transfer function from an exposure ramp. No chart needed.

    tools/measure_transfer.py <dir of clips> --out transfer.png
    tools/measure_transfer.py --self-test

METHOD
  Point at any flat, evenly lit surface -- a wall, paper, an overcast sky --
  defocused so texture does not matter. Fix ISO, aperture and focus. Then shoot
  one short clip per shutter speed, from far under-exposed to clipped.

  Shutter speed IS the reference. Doubling the exposure time doubles the scene
  light reaching the sensor, exactly, for free. So each clip gives one point:
  a known RELATIVE luminance against a measured output code value. Enough
  clips and that is the transfer function of the whole chain -- which is what a
  grey card would have given you, with more points and better spacing.

  It is better than a chart here for two reasons: a chart's patches are only as
  good as its printing and your lighting, and a chart cannot reach the 10+ stops
  this needs. Exposure time can.

SHUTTER SPEEDS
  Read automatically from the fp's own SIGM maker atom -- no renaming needed,
  just point it at the clips. Falls back to a number in the filename, and
  --shutters overrides both.

WHAT TO SHOOT
  Twice, ideally:
    - with IDENTITY knots  -> the pipeline's own curve, i.e. what precedes the
      look trim. This is the number docs/LOOK_CURVE.md calls the pre-gamma.
    - with your log knots  -> whether the composition came out as intended.

GOTCHAS
  Manual everything: no auto ISO, no auto shutter, no DR expansion or highlight
  priority. Daylight or a DC source -- mains flicker will wreck short exposures.
  Make the darkest clip clearly black and the brightest clearly clipped, so the
  ramp brackets the full range.
"""
import argparse, pathlib, re, struct, subprocess, sys
import numpy as np


def shutter_from_sigm(path):
    """Read ExposureTime out of the fp's own SIGM maker atom.

    The fp writes a little-endian TIFF/EXIF block into udta/SIGM in every MOV.
    Reading it beats parsing filenames: the camera names clips
    A001_010_20260921.MOV, whose last number is the DATE, so a filename parse
    silently returns 1/20260921 and the whole measurement is garbage.
    """
    TYP = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}
    d = pathlib.Path(path).read_bytes()[:0x20000]
    m = re.search(rb'SIGM', d)
    if not m:
        return None
    b = d[m.start() + 4:]
    j = b.find(b'II*\x00')
    if j < 0:
        return None
    b = b[j:]

    def ifd(off):
        out = {}
        try:
            n = struct.unpack_from('<H', b, off)[0]
        except struct.error:
            return out
        for i in range(n):
            e = off + 2 + i * 12
            try:
                tag, ty, cnt = struct.unpack_from('<HHI', b, e)
            except struct.error:
                break
            if ty not in TYP:
                continue
            tot = TYP[ty] * cnt
            vo = struct.unpack_from('<I', b, e + 8)[0] if tot > 4 else e + 8
            try:
                if ty == 5:
                    out[tag] = struct.unpack_from('<2I', b, vo)
                elif ty == 4:
                    out[tag] = struct.unpack_from('<I', b, vo)[0]
            except struct.error:
                pass
        return out

    try:
        t0 = ifd(struct.unpack_from('<I', b, 4)[0])
    except struct.error:
        return None
    tags = dict(t0)
    if 0x8769 in t0:
        tags.update(ifd(t0[0x8769]))
    v = tags.get(0x829A)
    return v[0] / v[1] if isinstance(v, tuple) and v[1] else None


def shutter_of(name):
    """Metadata first, filename only as a fallback."""
    s = shutter_from_sigm(name)
    if s:
        return s
    m = re.findall(r'(\d{1,5})', pathlib.Path(name).stem)
    return 1.0 / int(m[-1]) if m else None


def patch_mean(path, frames=8, crop=8):
    """Mean luma of a centred 1/crop-sized patch, averaged over `frames`."""
    cmd = ['ffmpeg', '-v', 'error', '-i', str(path),
           '-vf', f'crop=iw/{crop}:ih/{crop},format=gray',
           '-frames:v', str(frames), '-f', 'rawvideo', '-']
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode or not r.stdout:
        return None
    return float(np.frombuffer(r.stdout, dtype=np.uint8).mean())


def analyse(pairs):
    """pairs: [(relative exposure, code value)] -> normalised curve."""
    pairs = sorted(pairs)
    e = np.array([p[0] for p in pairs], float)
    v = np.array([p[1] for p in pairs], float)
    e = e / e.max()
    return e, v


def report(e, v):
    print(f"\n{'rel. exposure':>14} {'stops':>7} {'code':>7}")
    for x, y in zip(e, v):
        print(f"{x:14.5f} {np.log2(x):7.2f} {y:7.1f}")
    lo, hi = v.min(), v.max()
    print(f"\ncode range {lo:.1f}..{hi:.1f}")
    if hi < 250:
        print("  WARNING: never reached clipping -- add brighter exposures.")
    if lo > 24:
        print("  WARNING: never reached black -- add darker exposures.")
    m = (v > lo + 8) & (v < hi - 8)
    if m.sum() >= 4:
        g = np.polyfit(np.log(e[m]), np.log(np.maximum(v[m], 1)), 1)[0]
        print(f"  effective gamma over the usable range: {g:.3f}"
              f"   (1/{1/g:.2f})" if g > 0 else "")
        print(f"  -> feed this to build_logcurve_card.py as --pre-gamma {1/g:.2f}")
    return 0


def self_test():
    print("SELF-TEST: synthetic camera with a known gamma of 1/2.2\n")
    e = 2.0 ** np.arange(-10, 1)
    v = np.clip(np.power(e, 1 / 2.2) * 255, 0, 255)
    e2, v2 = analyse(list(zip(e, v)))
    m = (v2 > v2.min() + 8) & (v2 < v2.max() - 8)
    g = np.polyfit(np.log(e2[m]), np.log(v2[m]), 1)[0]
    ok = abs(g - 1 / 2.2) < 0.02
    print(f"  recovered gamma {g:.4f}, expected {1/2.2:.4f} -> "
          f"{'PASSED' if ok else 'FAILED'}")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('clips', nargs='?', type=pathlib.Path)
    ap.add_argument('--shutters', help='comma-separated denominators, in file order')
    ap.add_argument('--out', type=pathlib.Path)
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.clips:
        ap.error('give a directory of clips, or --self-test')

    files = sorted(p for p in a.clips.iterdir()
                   if p.suffix.lower() in ('.mov', '.mp4'))
    if not files:
        raise SystemExit(f'no clips in {a.clips}')
    sh = ([1.0 / int(x) for x in a.shutters.split(',')] if a.shutters
          else [shutter_of(p) for p in files])
    pairs = []
    for p, s in zip(files, sh):
        if s is None:
            print(f'  {p.name}: no shutter in the name, skipped'); continue
        m = patch_mean(p)
        if m is None:
            print(f'  {p.name}: could not read'); continue
        print(f'  {p.name}: 1/{1/s:.0f} s -> {m:.1f}')
        pairs.append((s, m))
    if len(pairs) < 4:
        raise SystemExit('need at least four usable clips')
    e, v = analyse(pairs)
    r = report(e, v)
    if a.out:
        import matplotlib; matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7, 4.6), dpi=170)
        ax.plot(np.log2(e), v, 'o-', lw=2, color='#2979b9')
        ax.set_xlabel('relative exposure (stops)'); ax.set_ylabel('code value 0-255')
        ax.set_title('Measured transfer function', loc='left', fontweight='bold')
        ax.grid(True, color='#e3e6ea'); ax.set_axisbelow(True)
        for s in ('top', 'right'): ax.spines[s].set_visible(False)
        fig.tight_layout(); fig.savefig(a.out); print(f'\nwrote {a.out}')
    return r


if __name__ == '__main__':
    sys.exit(main())
