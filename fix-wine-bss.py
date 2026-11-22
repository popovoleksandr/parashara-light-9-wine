#!/usr/bin/python3 -I
"""Make Wine's built-in DLLs digestible for the PL9 protection wrapper.

PL9.exe re-reads C:\\windows\\system32\\user32.dll from disk and parses it by
hand. Wine's DLLs carry an empty ".bss" section whose PointerToRawData is 0;
the wrapper mishandles that and crashes at startup (page fault reading 0x14).
Pointing the empty section at the next section's file offset is harmless to
Wine and keeps the wrapper's parser happy.

Idempotent. Keeps the untouched file next to it as <name>.orig.
Usage: fix-wine-bss.py <dll> [<dll> ...]
"""
import os
import shutil
import struct
import sys

for path in sys.argv[1:]:
    d = bytearray(open(path, 'rb').read())
    pe = struct.unpack_from('<I', d, 0x3C)[0]
    if d[:2] != b'MZ' or d[pe:pe + 4] != b'PE\0\0':
        print('skip (not a PE file):', path)
        continue
    nsec = struct.unpack_from('<H', d, pe + 6)[0]
    first = pe + 24 + struct.unpack_from('<H', d, pe + 20)[0]
    secs = [first + i * 40 for i in range(nsec)]
    changed = []
    for i, s in enumerate(secs):
        vsize, _va, rsize, rptr = struct.unpack_from('<IIII', d, s + 8)
        if vsize and not rsize and not rptr:
            later = [struct.unpack_from('<I', d, t + 20)[0] for t in secs[i + 1:]]
            target = next((p for p in later if p), len(d))
            struct.pack_into('<I', d, s + 20, target)
            changed.append(d[s:s + 8].rstrip(b'\0').decode(errors='replace'))
    if changed:
        shutil.copy2(path, path + '.orig')
        with open(path, 'wb') as f:
            f.write(d)
        print('patched %s: %s' % (path, ', '.join(changed)))
