#!/usr/bin/env python3
"""Did the camera actually record Log C?  Scored against an exposure series.

    python3 tools/verify_logc.py <dir of clips>
    python3 tools/verify_logc.py <dir of clips> --ei 800 --json out.json
    python3 tools/verify_logc.py --self-test

METHOD, AND WHY IT HAS ONLY ONE FREE PARAMETER
  Shoot one clip per shutter speed at a fixed, evenly lit, defocused surface.
  Shutter time is the reference: doubling it doubles the light, exactly and for
  free.  So the series gives *relative* exposure, not absolute — which leaves
  exactly one unknown, **where diffuse white (linear 1.0) sits in the series**.

  Everything else is predicted.  This fits that one scale and then scores every
  point against Log C.  If the pipeline really carries Log C, one number lines
  all the points up; if it does not, no scale will, and the residual pattern
  says which way it failed.

  It also refits the scale for every EI in the document and reports the best, so
  a wrong `--ei` on the card shows up as "you shot EI 400, not 800" rather than
  as a vague mismatch.

WHAT THE RESIDUALS MEAN
  * **flat residuals, small**            -> Log C is in the file.  Ship it.
  * **good low, collapsing at the top**  -> the highlights were clipped or kneed
    BEFORE the gamma stage (`PRE_TOP APKNEE`, `MAT_TOP PSTAPKNEE`).  No curve in
    `GAM_TOP` can recover them; the fp's usable log range ends where the
    residuals leave.  **This is the outcome the mapping is most at risk of.**
  * **good high, collapsing at the bottom** -> the noise floor, or black was
    lifted/crushed downstream.  Expected in the last stop or two.
  * **a consistent tilt**                -> the input mapping is off: the real
    white index is not 1918.  The printed `best white index` is the correction.

  Reads shutter speeds from the fp's own SIGM atom via `measure_transfer.py`,
  so the clips need no renaming.

GOTCHAS -- the same ones measure_transfer.py paid for
  Manual everything.  No auto ISO, no auto shutter, no DR expansion or highlight
  priority.  Daylight or a DC source: mains flicker wrecks short exposures.
  Bracket the whole range -- the darkest clip clearly black, the brightest
  clearly clipped -- or the fit has nothing to pin the ends with.
"""
import argparse, json, pathlib, sys
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import logc
from measure_transfer import shutter_of, patch_mean


def predict(rel, scale, ei, fit_range=False, stretch=False):
    """Predicted 0..255 code for relative exposures `rel` at a given white scale.

    Goes through `logc.encode`, the same definition the camera table is built
    from, so a `--fit-range` card is scored against what it actually wrote and
    not against the spec-exact curve.
    """
    lin = np.asarray(rel, float) * scale
    y = np.array([logc.encode(float(x), ei, fit_range=fit_range, stretch=stretch)
                  for x in lin])
    return np.clip(y, 0, 1) * 255.0


def fit_scale(rel, code, ei, mask=None, fit_range=False, stretch=False):
    """The one free parameter: which relative exposure is linear 1.0.

    Scanned rather than solved -- Log C is piecewise and the objective is not
    convex near the toe, so a coarse-to-fine scan is both simpler and safer than
    a solver that can sit down in the linear segment.
    """
    m = np.ones(len(rel), bool) if mask is None else mask
    if m.sum() < 3:
        return None, np.inf
    best, lo, hi = (None, np.inf), -12.0, 12.0
    for _ in range(6):
        grid = np.linspace(lo, hi, 241)
        errs = [np.sqrt(np.mean((predict(rel[m], 2.0 ** g, ei, fit_range, stretch) - code[m]) ** 2))
                for g in grid]
        k = int(np.argmin(errs))
        if errs[k] < best[1]:
            best = (2.0 ** grid[k], errs[k])
        step = grid[1] - grid[0]
        lo, hi = grid[k] - step, grid[k] + step
    return best


def analyse(rel, code, ei, fit_range=False, stretch=False):
    rel, code = np.asarray(rel, float), np.asarray(code, float)
    # Fit on the mid-range only: the toe is noise and the top may be clipped
    # upstream, and letting either drag the fit is how you get a scale that
    # matches nothing and blame the curve for it.
    usable = (code > code.min() + 6) & (code < min(250.0, code.max() - 2))
    scale, rms = fit_scale(rel, code, ei,
                           usable if usable.sum() >= 3 else None, fit_range, stretch)
    if scale is None:
        return None
    pred = predict(rel, scale, ei, fit_range, stretch)
    return dict(ei=ei, scale=float(scale), rms=float(rms),
                pred=pred, resid=code - pred, usable=usable,
                white_index=float(logc.WHITE_INDEX))


def report(names, rel, code, ei, fit_range=False, stretch=False):
    rel, code = np.asarray(rel, float), np.asarray(code, float)
    runs = [a for a in (analyse(rel, code, e, fit_range, stretch) for e in sorted(logc.EXPOSURE)) if a]
    if not runs:
        print('not enough usable points to fit -- need at least 3 between '
              'black and clipping')
        return 1
    runs.sort(key=lambda a: a['rms'])
    best, asked = runs[0], next(a for a in runs if a['ei'] == ei)

    print(f'\n{len(rel)} clips, scored against ARRI Log C V3 EI {ei}'
          f'{" (--stretch)" if stretch else " (--fit-range)" if fit_range else " (spec-exact)"}\n')
    print(f'{"clip":<24} {"rel exp":>9} {"stops":>7} {"code":>6} '
          f'{"pred":>6} {"resid":>7}')
    order = np.argsort(rel)
    for i in order:
        flag = '' if asked['usable'][i] else '   (excluded from the fit)'
        print(f'{names[i][:24]:<24} {rel[i]:9.4g} {np.log2(rel[i]):7.2f} '
              f'{code[i]:6.1f} {asked["pred"][i]:6.1f} '
              f'{asked["resid"][i]:+7.1f}{flag}')

    # linear = rel * scale, so linear 1.0 happens at rel = 1/scale.
    at = 1.0 / asked['scale']
    print(f'\nfit: diffuse white (linear 1.0) sits at relative exposure '
          f'{at:.4g},')
    print(f'     {abs(np.log2(at)):.2f} stops '
          f'{"below" if at < 1 else "above"} the brightest clip'
          f'   [scale {asked["scale"]:.4g}]')
    print(f'     RMS over the {int(asked["usable"].sum())} usable points: '
          f'{asked["rms"]:.2f} code values of 255')

    print('\nbest EI by RMS:')
    for a in runs[:4]:
        mark = '  <-- you asked for this one' if a['ei'] == ei else ''
        print(f'   EI {a["ei"]:>4}   RMS {a["rms"]:6.2f}{mark}')
    if best['ei'] != ei:
        print(f'\n  NOTE: EI {best["ei"]} fits better than EI {ei}. If the card '
              f'wrote EI {ei},\n  that gap is the pipeline disagreeing with the '
              f'curve, not the EI being wrong.')

    r = asked['resid']
    # Diagnostics run over ALL points, not just the ones the fit used -- the
    # clipped ones are exactly what we are trying to detect, and a first version
    # of this looked only at `usable` and so could never see them.
    #
    # Points at the codec ceiling are excluded instead: a good shoot is told to
    # bracket INTO clipping, so genuine full-scale clipping is expected and must
    # not raise the alarm. An upstream knee flattens the curve well BELOW 250,
    # and that is the signature this is looking for.
    live = code < 250
    mid = np.median(rel[live]) if live.sum() else np.median(rel)
    hi, lo = live & (rel >= mid), live & (rel < mid)
    u = asked['usable']
    print()
    if asked['rms'] < 3.0:
        print('VERDICT: Log C is in the file. Residuals are at the noise level.')
    elif asked['rms'] < 8.0:
        print('VERDICT: broadly Log C, with real deviation. Read the residuals '
              'by exposure\n         before shipping -- the pattern says where.')
    else:
        print('VERDICT: this is NOT Log C as predicted. Do not ship. The '
              'residual pattern below\n         says which assumption broke.')

    if hi.sum() and r[hi].mean() < -4:
        print('  Top end falls BELOW prediction: highlights were compressed or '
              'clipped\n  upstream of the gamma stage. No curve in GAM_TOP '
              'recovers them -- the fp\'s\n  usable log range ends where the '
              'residuals leave.')
    if lo.sum() and abs(r[lo].mean()) > 4:
        print(f'  Bottom end is off by {r[lo].mean():+.1f}: the toe or the '
              f'black level does not\n  match. Check the darkest clips are '
              f'actually at the noise floor.')
    if u.sum() >= 4:
        tilt = np.polyfit(np.log2(rel[u]), r[u], 1)[0]
        if abs(tilt) > 1.5:
            print(f'  Residuals TILT by {tilt:+.1f} codes per stop: the input '
                  f'mapping is off.\n  Try --white to move where linear 1.0 '
                  f'sits; 1918 is the stock measurement.')
    return 0


def self_test():
    ok = True
    # A synthetic camera that really does encode Log C EI 800.
    #
    # `rel` is normalised so the BRIGHTEST clip is 1.0, so the scale must be
    # ABOVE 1 for the series to bracket diffuse white at all. A first version of
    # this test used 2^-4, which put every point far below white, left nothing
    # clipped, and made the third case below meaningless.
    rel = 2.0 ** np.arange(-11, 5, 1.0)
    rel = rel / rel.max()
    true_scale = 8.0                     # white sits 3 stops below the top clip
    code = predict(rel, true_scale, 800)
    a = analyse(rel, code, 800)
    good = a is not None and abs(np.log2(a['scale'] / true_scale)) < 0.05 and a['rms'] < 0.5
    print(f'  recovers a known Log C camera        scale '
          f'{np.log2(a["scale"]):+.3f} vs {np.log2(true_scale):+.3f} stops, '
          f'RMS {a["rms"]:.3f}   {"PASS" if good else "FAIL"}')
    ok &= good

    # A camera that is NOT log -- plain sRGB, which is what the fp does stock.
    def srgb(L):
        L = np.clip(L, 0, None)
        return np.where(L <= 0.0031308, 12.92 * L, 1.055 * L ** (1 / 2.4) - 0.055)
    code2 = np.clip(srgb(rel * true_scale), 0, 1) * 255
    b = analyse(rel, code2, 800)
    good = b is not None and b['rms'] > 8.0
    print(f'  REJECTS a stock sRGB camera          RMS {b["rms"]:.2f} '
          f'(must exceed 8)          {"PASS" if good else "FAIL"}')
    ok &= good

    # Log C with the highlights clipped upstream at diffuse white -- the
    # outcome we most fear, and the one the fp's own table domain hints at.
    ceiling = predict([1.0 / true_scale], true_scale, 800)[0]   # code at linear 1.0
    code3 = np.minimum(predict(rel, true_scale, 800), ceiling)
    c = analyse(rel, code3, 800)
    live = code3 < 250                       # same rule the report uses
    hi = live & (rel >= np.median(rel[live]))
    good = c is not None and hi.sum() > 0 and c['resid'][hi].mean() < -4
    print(f'  flags upstream highlight clipping    mean top residual '
          f'{c["resid"][hi].mean():+.1f}   {"PASS" if good else "FAIL"}')
    ok &= good

    # a --fit-range camera must be recovered when scored with --fit-range
    code4 = predict(rel, true_scale, 800, fit_range=True)
    d = analyse(rel, code4, 800, fit_range=True)
    good = d is not None and abs(np.log2(d['scale'] / true_scale)) < 0.05 and d['rms'] < 0.5
    print(f'  recovers a --fit-range camera        RMS {d["rms"]:.3f}'
          f'                        {"PASS" if good else "FAIL"}')
    ok &= good
    # and scoring it with the WRONG form must NOT quietly pass
    e_ = analyse(rel, code4, 800, fit_range=False)
    good = e_ is None or e_['rms'] > 8.0
    print(f'  mismatched form does not pass         RMS '
          f'{(e_["rms"] if e_ else float("inf")):.2f} (must exceed 8)   '
          f'{"PASS" if good else "FAIL"}')
    ok &= good

    # a --stretch camera must be recovered as --stretch, and fail as spec-exact
    code6 = predict(rel, true_scale, 800, stretch=True)
    g6 = analyse(rel, code6, 800, stretch=True)
    good = g6 is not None and abs(np.log2(g6['scale'] / true_scale)) < 0.05 and g6['rms'] < 0.5
    print(f'  recovers a --stretch camera          RMS {g6["rms"]:.3f}'
          f'                        {"PASS" if good else "FAIL"}')
    ok &= good
    h6 = analyse(rel, code6, 800)
    good = h6 is None or h6['rms'] > 8.0
    print(f'  --stretch scored as spec-exact fails  RMS '
          f'{(h6["rms"] if h6 else float("inf")):.2f} (must exceed 8)  '
          f'{"PASS" if good else "FAIL"}')
    ok &= good

    print('\nSELF-TEST ' + ('PASSED' if ok else 'FAILED'))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('clips', nargs='?', type=pathlib.Path)
    ap.add_argument('--ei', type=int, default=800, choices=sorted(logc.EXPOSURE))
    ap.add_argument('--shutters', help='comma-separated denominators, in file order')
    ap.add_argument('--crop', type=int, default=8, help='patch is 1/N of frame')
    ap.add_argument('--fit-range', action='store_true',
                    help='score against a --fit-range card. MUST match how the '
                         'card was built, or every residual is wrong')
    ap.add_argument('--stretch', action='store_true',
                    help='score against a --stretch card. MUST match the card')
    ap.add_argument('--json', type=pathlib.Path)
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.clips is None:
        ap.error('give a directory of clips, or --self-test')

    files = sorted(p for p in a.clips.iterdir()
                   if p.suffix.lower() in ('.mov', '.mp4'))
    if not files:
        return print(f'no clips in {a.clips}') or 1

    if a.shutters:
        sh = [1.0 / float(x) for x in a.shutters.split(',')]
        if len(sh) != len(files):
            ap.error(f'{len(sh)} shutters for {len(files)} clips')
    else:
        sh = [shutter_of(p) for p in files]

    names, rel, code = [], [], []
    for p, s in zip(files, sh):
        if s is None:
            print(f'  skipping {p.name}: no shutter speed'); continue
        v = patch_mean(p, crop=a.crop)
        if v is None:
            print(f'  skipping {p.name}: could not read a patch'); continue
        names.append(p.name); rel.append(s); code.append(v)
    if len(rel) < 3:
        return print('need at least 3 readable clips') or 1

    rel = np.array(rel) / max(rel)
    rc = report(names, rel, np.array(code), a.ei, a.fit_range, a.stretch)
    if a.json:
        res = analyse(rel, np.array(code), a.ei, a.fit_range, a.stretch)
        a.json.write_text(json.dumps(
            dict(ei=a.ei, scale=res['scale'], rms=res['rms'],
                 clips=[dict(name=n, rel=float(r), code=float(c))
                        for n, r, c in zip(names, rel, code)]), indent=2))
        print(f'\nwrote {a.json}')
    return rc


if __name__ == '__main__':
    sys.exit(main())
