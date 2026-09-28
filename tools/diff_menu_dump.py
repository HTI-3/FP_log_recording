#!/usr/bin/env python3
"""Diff the two `menu dump` hex dumps inside a captured TONE.TXT."""
import pathlib, re, sys
p = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else 'TONE.TXT')
t = p.read_text(errors='replace')
blocks, cur = [], None
for line in t.splitlines():
    if line.startswith('addr='):
        cur = {}; blocks.append(cur); continue
    m = re.match(r'0x([0-9A-F]{8}) \| ((?:[0-9A-F]{2} ){1,16})', line)
    if m and cur is not None:
        off = int(m.group(1), 16)
        for i, b in enumerate(m.group(2).split()):
            cur[off + i] = int(b, 16)
print(f'{len(blocks)} settings dumps found')
if len(blocks) < 2:
    print('Need two. The second `menu dump` may not have run.'); sys.exit(1)
a, b = blocks[0], blocks[-1]
diff = sorted(o for o in a if o in b and a[o] != b[o])
print(f'{len(diff)} bytes differ between them\n')
runs, cur = [], []
for o in diff:
    if cur and o == cur[-1] + 1: cur.append(o)
    else:
        if cur: runs.append(cur)
        cur = [o]
if cur: runs.append(cur)
for r in runs:
    print(f'  +0x{r[0]:04X}  {len(r)} byte(s)   '
          + ' '.join(f'{a[o]:02X}' for o in r) + '  ->  '
          + ' '.join(f'{b[o]:02X}' for o in r))
print(f'\nSettings block base is 0xC31B32BC, so +0x{runs[0][0]:04X} is '
      f'0x{0xC31B32BC + runs[0][0]:08X}' if runs else
      '\nNothing changed -- every setter was rejected, or the values were no-ops.')
