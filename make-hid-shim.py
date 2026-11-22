#!/usr/bin/python3 -I
"""Build an app-local hid.dll for PL9 from Wine's own hid.dll.

PL9's dongle check calls HidD_FlushQueue after every command and aborts when
it fails. Wine does not implement that call (IOCTL_HID_FLUSH_QUEUE), so the
key is reported as "not found" although it answers. This copies Wine's 32-bit
hid.dll, makes HidD_FlushQueue simply return TRUE (the dongle has no input
queue to flush), and drops the "Wine builtin" marker so Wine loads the copy
from the program folder in place of its own.

Usage: make-hid-shim.py <wine hid.dll> <output hid.dll>
"""
import struct
import sys

src, dst = sys.argv[1], sys.argv[2]
d = bytearray(open(src, 'rb').read())
pe = struct.unpack_from('<I', d, 0x3C)[0]
assert d[pe:pe + 4] == b'PE\0\0' and struct.unpack_from('<H', d, pe + 24)[0] == 0x10B, 'need a 32-bit PE'
nsec = struct.unpack_from('<H', d, pe + 6)[0]
first = pe + 24 + struct.unpack_from('<H', d, pe + 20)[0]
secs = [struct.unpack_from('<IIII', d, first + i * 40 + 8) for i in range(nsec)]  # vsize, va, rsize, rptr


def off(rva):
    for vsize, va, rsize, rptr in secs:
        if va <= rva < va + max(vsize, rsize):
            return rva - va + rptr
    raise ValueError('rva %#x not in any section' % rva)


exp = off(struct.unpack_from('<I', d, pe + 24 + 96)[0])
nnames = struct.unpack_from('<I', d, exp + 24)[0]
funcs, names, ords = (off(x) for x in struct.unpack_from('<III', d, exp + 28))
for i in range(nnames):
    n = off(struct.unpack_from('<I', d, names + 4 * i)[0])
    if d[n:d.index(b'\0', n)] == b'HidD_FlushQueue':
        ordinal = struct.unpack_from('<H', d, ords + 2 * i)[0]
        code = off(struct.unpack_from('<I', d, funcs + 4 * ordinal)[0])
        d[code:code + 8] = bytes.fromhex('b801000000c20400')  # mov eax,1 ; ret 4
        break
else:
    sys.exit('HidD_FlushQueue export not found in ' + src)

marker = d.find(b'Wine builtin DLL', 0, pe)
if marker >= 0:
    d[marker:marker + 16] = b'PL9 local hidDLL'
with open(dst, 'wb') as f:
    f.write(d)
print('wrote', dst)
