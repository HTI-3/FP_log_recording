#!/usr/bin/env python3
"""ARRI ALEXA Log C V3 — the curve, and the fp's table built from it.

    python3 tools/logc.py --self-test
    python3 tools/logc.py --ei 800 --table          # the 2048-entry camera table
    python3 tools/logc.py --ei 800 --cube out.cube  # the matching Resolve decode

**One source of truth.** The camera-side table, the `.cube` and the DCTL are all
produced here, so the encode and the decode cannot drift — `PLAN.md` §10 C1.

Source: *ALEXA Log C Curve — Usage in VFX*, Harald Brendel, ARRI, rev 09-Mar-17
(`resources/ARRI_ALEXA_LogC_Curve_in_VFX-1.pdf`). Both parameter tables
from the appendix are transcribed below and the self-test checks them against
three independent numbers the document states separately, so a typo cannot
survive.

---

## Which parameter set, and why it matters here

The document gives two: one for **sensor signal** (a linear normalisation of the
16-bit sensor code value) and one for **exposure value** (*"relative to a
theoretical perfectly exposed white card having a value of 1.0"*).

**fpLog uses the exposure-value set**, because that is what the fp's gamma stage
is fed. `results/invert/` put the curve on `GAM_TOP GAMMA TABLE`, and the stock
table there was then identified exactly:

    stock curve #82  ==  sRGB OETF( index / 1918 )     max error 2 of 8190 codes

So the table's input is **scene-linear, normalised to diffuse white = 1.0 at
index 1918** — ARRI's "exposure value" by definition. 18% middle grey lands at
index 345 and renders to 0.4614, which is textbook.

## The range problem, stated before anyone is surprised by it

The table's input runs to index 2047 = **1.067 × white, 0.094 stops above it**.
Log C at EI 800 expects scene values up to ~36 × white. So a spec-exact Log C
table uses only

    LogC(0) = 0.0928   to   LogC(1.067) = 0.5776

— **about 48% of the output range**, and in the 8-bit MOV that is roughly codes
24..147 of 0..255. `PLAN.md` §2 warned about exactly this.

**That is deliberate for the first card.** Spec-exact makes the expected values
unambiguous, so an exposure sweep either matches Log C or does not, with nothing
to argue about — and Resolve's stock *ARRI LogC3 EI800* decode applies directly.
`--fit-range` rescales the output to use the whole range once the sweep has
confirmed the mapping; it needs the matching decode, which this file also emits.

**What the sweep is really testing** is whether the fp's highlight range even
reaches this stage. If measured code values track Log C over many stops, it
does. If they flatten above white, something upstream (`PRE_TOP APKNEE`,
`MAT_TOP PSTAPKNEE`) compressed them first, and no curve here recovers them.
"""
import argparse, math, sys

# --- Appendix, "conversion between Log C values and EXPOSURE VALUES" ---------
#     EI: (cut, a, b, c, d, e, f, e_cut_plus_f)
#     The last column is the document's own, kept as a checksum, not used.
EXPOSURE = {
     160: (0.005561, 5.555556, 0.080216, 0.269036, 0.381991, 5.842037, 0.092778, 0.125266),
     200: (0.006208, 5.555556, 0.076621, 0.266007, 0.382478, 5.776265, 0.092782, 0.128643),
     250: (0.006871, 5.555556, 0.072941, 0.262978, 0.382966, 5.710494, 0.092786, 0.132021),
     320: (0.007622, 5.555556, 0.068768, 0.259627, 0.383508, 5.637732, 0.092791, 0.135761),
     400: (0.008318, 5.555556, 0.064901, 0.256598, 0.383999, 5.571960, 0.092795, 0.139142),
     500: (0.009031, 5.555556, 0.060939, 0.253569, 0.384493, 5.506188, 0.092800, 0.142526),
     640: (0.009840, 5.555556, 0.056443, 0.250219, 0.385040, 5.433426, 0.092805, 0.146271),
     800: (0.010591, 5.555556, 0.052272, 0.247190, 0.385537, 5.367655, 0.092809, 0.149658),
    1000: (0.011361, 5.555556, 0.047996, 0.244161, 0.386036, 5.301883, 0.092814, 0.153047),
    1280: (0.012235, 5.555556, 0.043137, 0.240810, 0.386590, 5.229121, 0.092819, 0.156799),
    1600: (0.013047, 5.555556, 0.038625, 0.237781, 0.387093, 5.163350, 0.092824, 0.160192),
}

# --- Appendix, "conversion between Log C values and SENSOR SIGNAL" ----------
#     Not used to build the table; kept because the document's own black and
#     clipping-level table is stated against THIS set, and the self-test needs it.
SENSOR = {
     160: (0.004680,  40.0, -0.076072, 0.269036, 0.381991,  42.062665, -0.071569, 0.125266),
     200: (0.004597,  50.0, -0.118740, 0.266007, 0.382478,  51.986387, -0.110339, 0.128643),
     250: (0.004518,  62.5, -0.171260, 0.262978, 0.382966,  64.243053, -0.158224, 0.132021),
     320: (0.004436,  80.0, -0.243808, 0.259627, 0.383508,  81.183335, -0.224409, 0.135761),
     400: (0.004369, 100.0, -0.325820, 0.256598, 0.383999, 100.295280, -0.299079, 0.139142),
     500: (0.004309, 125.0, -0.427461, 0.253569, 0.384493, 123.889239, -0.391261, 0.142526),
     640: (0.004249, 160.0, -0.568709, 0.250219, 0.385040, 156.482680, -0.518605, 0.146271),
     800: (0.004201, 200.0, -0.729169, 0.247190, 0.385537, 193.235573, -0.662201, 0.149658),
    1000: (0.004160, 250.0, -0.928805, 0.244161, 0.386036, 238.584745, -0.839385, 0.153047),
    1280: (0.004120, 320.0, -1.207168, 0.240810, 0.386590, 301.197380, -1.084020, 0.156799),
    1600: (0.004088, 400.0, -1.524256, 0.237781, 0.387093, 371.761171, -1.359723, 0.160192),
}

# The document's own "Black / Clipping Level" table, against SENSOR parameters.
CLIP_LEVEL = {160: 0.8128, 200: 0.8341, 250: 0.8549, 320: 0.8773, 400: 0.8968,
              500: 0.9158, 640: 0.9362, 800: 0.9539, 1000: 0.9711, 1280: 0.9895,
              1600: 1.0000}
BLACK_LOGC = 0.0928              # constant in Log C V3, all EIs
SENSOR_BLACK = 256 / 65535       # "black will be represented by 256/65535"

# --- the fp's gamma stage, measured ----------------------------------------
WHITE_INDEX = 1918               # index where the stock table reaches full scale
TABLE_N = 2048                   # entries in one GAM_TOP curve
TABLE_MAX = 8190                 # the stock curve's own maximum (13-bit)


def lin2log(x, ei=800, table=EXPOSURE):
    """Encode. x is linear-domain (exposure value, white = 1.0)."""
    cut, a, b, c, d, e, f, _ = table[ei]
    return c * math.log10(a * x + b) + d if x > cut else e * x + f


def log2lin(t, ei=800, table=EXPOSURE):
    """Decode. Inverse of lin2log, exactly as the document writes it."""
    cut, a, b, c, d, e, f, _ = table[ei]
    return (10 ** ((t - d) / c) - b) / a if t > e * cut + f else (t - f) / e


def span(ei=800, white=WHITE_INDEX, n=TABLE_N):
    """The Log C values at the two ends of the table's input domain."""
    return lin2log(0.0, ei), lin2log((n - 1) / white, ei)


def stretch_span(ei=800):
    """Log C at the two ends of the USABLE input: black and diffuse white."""
    return lin2log(0.0, ei), lin2log(1.0, ei)


def encode(x, ei=800, white=WHITE_INDEX, fit_range=False, n=TABLE_N,
           stretch=False):
    """Linear -> normalised 0..1 output. THE definition, shared by everything.

    `fit_range` rescales so the table's own domain spans the whole output.
    **That is not cosmetic and it is not optional in practice** -- see below.

    `stretch` is the full-code-range form, 2026-09-23. The INPUT mapping is
    spec-exact's, untouched: index/1918 = scene linear, diffuse white = 1.0. It
    is not a fit of ARRI's whole range (that was the reverted `3d10409`). Only
    the output moves: Log C over the usable input, black..diffuse white, is
    stretched to fill 0..1 -- 2.09x -- and held at full scale above white,
    exactly as curve #82 holds its own top. So every one of 0..255 is used and
    each stop gets 38 codes instead of 18.

    It is `--fit-range` with its top at diffuse white and a flat top, which is
    two codes from it through the midtones. `results/logc2/` saw fit-range cast
    the upper midtones violet/cyan -- from a run that may not have finished. A
    complete write of this form is the test of whether that was real.
    """
    if stretch:
        if x >= 1.0:
            return 1.0
        lo, hi = stretch_span(ei)
        return (lin2log(x, ei) - lo) / (hi - lo)
    y = lin2log(x, ei)
    if fit_range:
        lo, hi = span(ei, white, n)
        y = (y - lo) / (hi - lo)
    return y


def srgb(L):
    """The stock curve. `curve #82 == sRGB OETF(index/1918)`, max error 2/8190."""
    L = max(0.0, L)
    return 12.92 * L if L <= 0.0031308 else 1.055 * L ** (1 / 2.4) - 0.055


# Measured on hardware, 2026-09-22 (`results/logc2/`): a chroma-suppression
# stage fires on OUTPUT CODE, over roughly 8-bit 184..207, and it is calibrated
# to the stock curve -- where that band sits 1.06..0.68 stops under diffuse
# white, i.e. on near-white highlights with little saturation to lose. Any curve
# that puts saturated MIDTONES at those codes gets them visibly desaturated and
# then over-saturated on recovery. A full-range log curve does exactly that,
# which is why `fit_range` was tried and rejected.
#
# Spec-exact Log C tops out at 8-bit 147 and never enters the band at all.
# That is why it looks right, and it is why the fix below changes only the
# highlight end and leaves every Log C value alone.
SUPPRESS_LO_CODE = 184 / 255.0

def rolloff_hermite(t, y0, m0, y1=1.0):
    """Cubic Hermite from (0, y0) with slope m0, to (1, y1) with slope 0.

    *** REJECTED ON HARDWARE, 2026-09-22 (results/logc3/). OFF BY DEFAULT. ***

    It removes the highlight cliff and introduces something worse. The table is
    applied PER CHANNEL, so spreading index 1918..2047 across codes 145..255
    lifts whichever channel exceeds diffuse white while the others stay at their
    Log C values. On a warm subject red crosses white first, so red and green
    lift and blue does not: R-G goes from +5 under spec-exact to **+68**. That
    is a red/yellow cast over everything with one channel over white -- which
    includes plenty of mid-luma pixels.

    The stock sRGB curve does not have the problem and does not solve it with a
    roll-off: it is ALREADY at full scale by diffuse white, so every channel
    above white clips to the same value and highlights converge to neutral.
    A log curve puts white at code 145, so there is a 110-code gap between "just
    under white" and "clipped" that no in-table shape can close -- spread it and
    you separate the channels, collapse it and you are back to the cliff.

    So the cliff is a property of the stage, not a bug in the curve, and it is
    the lesser evil: it fringes blown highlights only, where a spread casts the
    whole warm midrange. Kept behind a flag as the negative record.
    """
    h00 = 2 * t ** 3 - 3 * t ** 2 + 1
    h10 = t ** 3 - 2 * t ** 2 + t
    h01 = -2 * t ** 3 + 3 * t ** 2
    return h00 * y0 + h10 * m0 + h01 * y1


def curve_norm(i, ei=800, white=WHITE_INDEX, n=TABLE_N,
               fit_range=False, rolloff=False, rolloff_from=None, stretch=False):
    """Normalised 0..1 output for table index `i`. THE definition."""
    if stretch:
        return encode(i / white, ei, white, stretch=True)
    if fit_range:                                  # rejected -- see SUPPRESS_LO_CODE
        return encode(i / white, ei, white, True, n)
    y = lin2log(i / white, ei)
    if not rolloff:
        return y
    j = white if rolloff_from is None else rolloff_from
    if i <= j:
        return y                                   # bit-exact Log C. Untouched.
    yj = lin2log(j / white, ei)
    mj = (lin2log((j + 1) / white, ei) - lin2log((j - 1) / white, ei)) / 2
    span_i = (n - 1) - j
    return rolloff_hermite((i - j) / span_i, yj, mj * span_i, 1.0)


def camera_table(ei=800, white=WHITE_INDEX, n=TABLE_N, vmax=TABLE_MAX,
                 fit_range=False, rolloff=False, rolloff_from=None, stretch=False):
    """The 2048 u16 to write into one GAM_TOP curve.

    index i  ->  linear x = i / white  ->  Log C  ->  0..vmax

    THE TABLE'S TOP ENTRY MUST BE vmax.  Measured on hardware, 2026-09-22
    (`results/logc1/`): input above the table's domain does **not** clamp to
    `table[n-1]`, it goes to full scale.  So a table whose top is below full
    scale leaves a cliff between its own ceiling and everything brighter, and
    the three channels cross that cliff at different scene levels because of
    the white-balance gains -- which renders as a hard-edged coloured halo
    around every highlight.  A spec-exact Log C table tops out at 4730 of 8190
    and produced exactly that, a 108-code step.

    The stock sRGB curve does not have the problem because it reaches full
    scale at index 1918 and holds it flat to 2047.

    So `fit_range=True` is the shippable form.  Spec-exact is kept because it
    is the one that makes an exposure series unambiguous, and because the halo
    it produces is what measured the out-of-domain behaviour in the first place.
    """
    ys = [curve_norm(i, ei, white, n, fit_range, rolloff, rolloff_from, stretch)
          for i in range(n)]
    return [min(vmax, max(0, round(y * vmax))) for y in ys]


def decode_lut(ei=800, white=WHITE_INDEX, size=4096, fit_range=False,
               rolloff=False, rolloff_from=None, stretch=False):
    """1D decode: recorded 0..1 -> scene linear, white = 1.0.

    Inverted NUMERICALLY from the curve actually written, so it is right for
    every form including the highlight roll-off, which has no closed-form
    inverse. Below the junction the result is Log C to the last decimal, because
    the curve there IS Log C.
    """
    if stretch:
        # closed form: undo the 2.09x, then ARRI's own decode. Exact, and it
        # maps the top code to diffuse white (1.0), where the flat top begins.
        lo, hi = stretch_span(ei)
        return [log2lin(lo + (k / (size - 1)) * (hi - lo), ei) for k in range(size)]
    xs = [i / white for i in range(TABLE_N)]
    ys = [curve_norm(i, ei, white, TABLE_N, fit_range, rolloff, rolloff_from)
          for i in range(TABLE_N)]
    out = []
    for k in range(size):
        t = k / (size - 1)
        if t <= ys[0]:
            out.append(0.0)
        elif t >= ys[-1]:
            out.append(xs[-1])
        else:
            j = 0                                  # ys is monotonic
            while j < len(ys) - 2 and ys[j + 1] < t:
                j += 1
            f = 0.0 if ys[j + 1] == ys[j] else (t - ys[j]) / (ys[j + 1] - ys[j])
            out.append(xs[j] + f * (xs[j + 1] - xs[j]))
    return out


def write_cube(path, ei=800, white=WHITE_INDEX, size=4096, fit_range=False,
               rolloff=False, rolloff_from=None, stretch=False):
    lut = decode_lut(ei, white, size, fit_range, rolloff, rolloff_from, stretch)
    with open(path, 'w') as fh:
        fh.write(f'# fpLog decode -- ARRI Log C V3 EI {ei}, exposure-value set\n')
        if stretch:
            lo, hi = stretch_span(ei)
            fh.write(f'# STRETCH: Log C {lo:.4f}..{hi:.4f} (black..diffuse white at index\n'
                     f'# {white}) stretched to 0..1. Decodes to scene linear, white = 1.0.\n')
        else:
            fh.write(f'# white = 1.0 at table index {white}. Log C is BIT-EXACT up to\n'
                     f'# diffuse white; above it the curve rolls off to clipping.\n'
                     f'# Resolve\'s stock ARRI LogC3 EI{ei} decode is exact over that range.\n'
                     if rolloff and not fit_range else
                     f'# white = 1.0 at table index {white};'
                     f'{" output refitted to full range" if fit_range else " spec-exact"}\n')
        fh.write('# generated by tools/logc.py -- do not edit\n')
        fh.write(f'LUT_1D_SIZE {size}\n')
        for v in lut:
            fh.write(f'{v:.8f} {v:.8f} {v:.8f}\n')
    return path


def write_dctl(path, ei=800, white=WHITE_INDEX, fit_range=False,
               rolloff=False, rolloff_from=None, stretch=False):
    cut, a, b, c, d, e, f, _ = EXPOSURE[ei]
    lo, hi = stretch_span(ei) if stretch else span(ei, white)
    pre = (f'    t = {lo:.8f}f + t * {hi - lo:.8f}f;\n' if (fit_range or stretch) else '')
    src = f'''// fpLog decode -- ARRI Log C V3 EI {ei} (exposure-value parameters)
// white = 1.0 at fp gamma-table index {white}.
// {'STRETCH: Log C black..diffuse white stretched to 0..1; undone first, below.' if stretch else 'Output refitted to full range.' if fit_range else 'Log C is BIT-EXACT up to diffuse white.'}
// {'Above index ' + str(white) + ' the table is flat at full scale, so the top code decodes to 1.0.' if stretch else '' if fit_range else 'Above white the camera rolls the curve off to clipping; this decode'}
// {'' if (fit_range or stretch) else 'extrapolates there, and those values are blown highlights either way.'}
// Generated by tools/logc.py -- do not edit; regenerate so encode and decode cannot drift.
__DEVICE__ float fplog_decode(float t) {{
{pre}    if (t > {e:.8f}f * {cut:.8f}f + {f:.8f}f)
        return (_powf(10.0f, (t - {d:.8f}f) / {c:.8f}f) - {b:.8f}f) / {a:.8f}f;
    return (t - {f:.8f}f) / {e:.8f}f;
}}

__DEVICE__ float3 transform(int p_Width, int p_Height, int p_X, int p_Y,
                            __TEXTURE__ p_TexR, __TEXTURE__ p_TexG, __TEXTURE__ p_TexB) {{
    float3 o;
    o.x = fplog_decode(_tex2D(p_TexR, p_X, p_Y));
    o.y = fplog_decode(_tex2D(p_TexG, p_X, p_Y));
    o.z = fplog_decode(_tex2D(p_TexB, p_X, p_Y));
    return o;
}}
'''
    open(path, 'w').write(src)
    return path


# ---------------------------------------------------------------------------
def self_test():
    ok = True

    def chk(label, got, want, tol):
        nonlocal ok
        good = abs(got - want) <= tol
        ok &= good
        print(f'  {label:<52} {got:.6f} vs {want:.6f}  '
              f'{"PASS" if good else "FAIL"}')

    print('Against numbers the document states SEPARATELY from the parameter tables:\n')
    # 1. e*cut+f, the appendix's own last column, for both tables and every EI.
    #    The tolerance is DERIVED, not chosen: every parameter is printed to six
    #    decimals, so cut and e each carry up to 5e-7 of rounding, and the
    #    product amplifies cut's by e -- which reaches 371.76 in the sensor set.
    #    A flat tolerance here either passes everything or fails the sensor set
    #    for being printed rather than for being wrong.
    worst_ratio = 0.0
    for name, tbl in (('exposure', EXPOSURE), ('sensor', SENSOR)):
        for ei, p in tbl.items():
            cut, _, _, _, _, e, f, printed = p
            budget = abs(e) * 5e-7 + 5e-7 + 5e-7 + 5e-7
            worst_ratio = max(worst_ratio, abs(e * cut + f - printed) / budget)
    chk('e*cut+f matches its printed column, as a fraction of the '
        'rounding budget', worst_ratio, 0.0, 1.0)

    # 2. black is 0.0928 for every EI (exposure set: x=0 -> f)
    worst = max(abs(lin2log(0.0, ei) - BLACK_LOGC) for ei in EXPOSURE)
    chk('black (exposure set, x=0) == 0.0928 for every EI', worst, 0.0, 5e-5)

    # 3. the ASA table's clipping levels, sensor set at sensor signal 1.0.
    #    EI 1600 is excluded deliberately and checked separately below: the
    #    document says its curve "will rise just above 1.0" and that those
    #    values should be clipped, so 1.0 in the table is a clamp, not a value.
    worst = max(abs(lin2log(1.0, ei, SENSOR) - CLIP_LEVEL[ei])
                for ei in CLIP_LEVEL if ei != 1600)
    chk('clipping level at sensor signal 1.0, EI 160..1280', worst, 0.0, 6e-5)

    over = lin2log(1.0, 1600, SENSOR)
    good = 1.0 < over < 1.01
    ok &= good
    print(f'  {"EI 1600 rises just above 1.0, as the document says":<52} '
          f'{over:.6f}       {"PASS" if good else "FAIL"}')

    # 4. "maps the sensor signal corresponding to 18% gray to 0.391, = 400/1023"
    chk('18% grey -> 0.391 (EI 800, exposure set)',
        lin2log(0.18, 800), 400 / 1023, 6e-4)

    # 5. black in the sensor set is the stated 256/65535
    chk('sensor black 256/65535 -> 0.0928 (EI 800, sensor set)',
        lin2log(SENSOR_BLACK, 800, SENSOR), BLACK_LOGC, 3e-4)

    # 6. round trip, both parameter sets, across the whole domain
    worst = 0.0
    for name, tbl in (('exposure', EXPOSURE), ('sensor', SENSOR)):
        for ei in tbl:
            for k in range(0, 2001):
                x = k / 2000 * (2.0 if tbl is EXPOSURE else 1.0)
                worst = max(worst, abs(log2lin(lin2log(x, ei, tbl), ei, tbl) - x))
    chk('log2lin(lin2log(x)) == x, both sets, all EIs', worst, 0.0, 1e-9)

    print('\nAgainst the fp stage, and the table this builds:\n')
    t = camera_table(800)                       # the default: spec-exact Log C
    roll = camera_table(800, rolloff=True)      # rejected, kept as the record

    def yes(label, good, detail=''):
        nonlocal ok
        ok &= bool(good)
        print(f'  {label:<52} {detail}{"PASS" if good else "FAIL"}')

    # The default must be Log C and nothing but Log C, everywhere.
    worst = max(abs(t[i] / TABLE_MAX - lin2log(i / WHITE_INDEX, 800))
                for i in range(TABLE_N))
    yes('default table is spec-exact Log C, every entry',
        worst <= 1 / TABLE_MAX, f'{worst * TABLE_MAX:.2f} codes  ')

    # It has a cliff, and that is the accepted trade, not an oversight: input
    # above the table's domain goes to full scale (results/logc1/), so the top
    # entry being 4730 leaves a step. Spreading it is worse -- see below.
    cliff = 255 - round(t[-1] / TABLE_MAX * 255)
    yes('spec-exact tops out at 147 (clean when fully written)', cliff > 50,
        f'{cliff} of 255  ')

    # Why the roll-off is off: the table is per-channel, so spreading the top
    # separates channels instead of converging them. A warm pixel with red just
    # over white and green/blue under it.
    R, G = 1990, 1700
    sep_spec = round(t[R] / TABLE_MAX * 255) - round(t[G] / TABLE_MAX * 255)
    sep_roll = round(roll[R] / TABLE_MAX * 255) - round(roll[G] / TABLE_MAX * 255)
    yes('roll-off separates channels, and fixes nothing',
        sep_spec < 15 and sep_roll > 50, f'R-G {sep_spec:+d} -> {sep_roll:+d}  ')

    # Resolve's stock dropdown must decode the whole thing.
    worst = max(abs(log2lin(curve_norm(i), 800) - i / WHITE_INDEX) / (i / WHITE_INDEX)
                for i in range(1, TABLE_N))
    yes('stock ARRI LogC3 decode is exact, whole table', worst < 1e-9,
        f'{worst * 100:.2e}%  ')

    # The chroma-suppression band measured on hardware at 8-bit 184..207.
    o = [v / TABLE_MAX * 255 for v in t]
    fr = [v / TABLE_MAX * 255 for v in camera_table(800, fit_range=True)]
    yes('nothing lands in the 184..207 suppression band',
        sum(1 for v in o if 184 <= v <= 207) == 0,
        f'0 vs {sum(1 for v in fr if 184 <= v <= 207)} for --fit-range  ')

    bad = [e for e in EXPOSURE
           if any(camera_table(e)[k + 1] < camera_table(e)[k] for k in range(TABLE_N - 1))]
    yes('monotonic after quantisation, every EI', not bad, f'{len(bad)} bad  ')

    # --- the STRETCH form ------------------------------------------------------
    stt = camera_table(800, stretch=True)
    slo, shi = stretch_span(800)
    yes('stretch: black 0, white index 1918 full scale, flat above',
        stt[0] == 0 and all(v == TABLE_MAX for v in stt[WHITE_INDEX:]),
        f'{stt[0]}, {stt[WHITE_INDEX]}..{stt[-1]}  ')
    # the input mapping is spec-exact's: undo the stretch, apply ARRI's decode,
    # and index/1918 comes back -- so it is NOT a fit of ARRI's whole range
    worst = max(abs(log2lin(slo + curve_norm(i, stretch=True) * (shi - slo), 800)
                    - i / WHITE_INDEX) / (i / WHITE_INDEX)
                for i in range(1, WHITE_INDEX))
    yes('stretch: IS Log C of index/1918, affinely rescaled', worst < 1e-9,
        f'{worst * 100:.1e}%  ')
    c8 = lambda v: round(v / TABLE_MAX * 255)
    per_st, per_sp = c8(stt[690]) - c8(stt[345]), c8(t[690]) - c8(t[345])
    yes('stretch: about twice the codes per stop of spec-exact',
        per_st >= 2 * per_sp - 1, f'{per_sp} -> {per_st} around grey  ')
    # "Uses 0..255" means the RANGE is 0..255 and nothing jumps: the hardware
    # interpolates between entries, so the output is continuous. The table
    # itself lands on only ~242 distinct 8-bit values because in the deepest
    # toe one index moves ~1.5 codes -- the same is true of the stock curve.
    step = max((stt[k + 1] - stt[k]) / TABLE_MAX * 255 for k in range(TABLE_N - 1))
    yes('stretch: spans 0..255, no step between entries over 2 codes',
        c8(stt[0]) == 0 and c8(stt[-1]) == 255 and step <= 2.0,
        f'biggest step {step:.2f}  ')
    bad = [e for e in EXPOSURE
           if any(camera_table(e, stretch=True)[k + 1] < camera_table(e, stretch=True)[k]
                  for k in range(TABLE_N - 1))]
    yes('stretch: monotonic after quantisation, every EI', not bad, f'{len(bad)} bad  ')
    # reported, not asserted: the open question this form retests
    print(f'  {"stretch: entries in the 184..207 band (RETEST)":<52} '
          f'{sum(1 for v in stt if 184 <= c8(v) <= 207)} -- see results/logc2/')

    print(f'\n  8-bit: black {round(t[0] / TABLE_MAX * 255)}, '
          f'18% grey {round(t[round(0.18 * WHITE_INDEX)] / TABLE_MAX * 255)}, '
          f'diffuse white {round(t[WHITE_INDEX] / TABLE_MAX * 255)}, '
          f'top {round(t[-1] / TABLE_MAX * 255)}')
    print(f'  ARRI paper EI 800: black {lin2log(0.0) * 255:.1f}, '
          f'18% grey {lin2log(0.18) * 255:.1f} (0.391 = 400/1023), '
          f'white {lin2log(1.0) * 255:.1f}')

    print('\nSELF-TEST ' + ('PASSED' if ok else 'FAILED'))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ei', type=int, default=800, choices=sorted(EXPOSURE))
    ap.add_argument('--white', type=int, default=WHITE_INDEX)
    ap.add_argument('--fit-range', action='store_true')
    ap.add_argument('--table', action='store_true')
    ap.add_argument('--cube')
    ap.add_argument('--dctl')
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.table:
        for i, v in enumerate(camera_table(a.ei, a.white, fit_range=a.fit_range)):
            print(f'{i} {v}')
    if a.cube:
        print('wrote', write_cube(a.cube, a.ei, a.white, fit_range=a.fit_range))
    if a.dctl:
        print('wrote', write_dctl(a.dctl, a.ei, a.white, fit_range=a.fit_range))
    if not (a.table or a.cube or a.dctl):
        ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
