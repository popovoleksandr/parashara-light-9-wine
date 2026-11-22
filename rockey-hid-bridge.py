#!/usr/bin/python3 -I
"""Expose a Feitian ROCKEY "HID Dongle" (096e:0006) as a Linux hidraw device.

The dongle is a HID-class device with only a control endpoint. The kernel's
usbhid driver refuses it ("couldn't find an input interrupt endpoint"), so no
/dev/hidraw node appears and Wine cannot show it to Windows programs.

This bridge creates a virtual HID device through /dev/uhid carrying the
dongle's own report descriptor, and forwards every feature/output report
request to the real dongle as plain HID control transfers over usbfs.

Usage: rockey-hid-bridge.py <usb sysfs name, e.g. 3-1>
Needs read/write access to /dev/uhid and to the dongle's /dev/bus/usb node.
"""
import ctypes
import errno
import fcntl
import os
import select
import struct
import sys

USBDEVFS_CONTROL = 0xC0185500  # _IOWR('U', 0, struct usbdevfs_ctrltransfer), 64-bit

UHID_DESTROY, UHID_START, UHID_STOP, UHID_OPEN, UHID_CLOSE, UHID_OUTPUT = 1, 2, 3, 4, 5, 6
UHID_GET_REPORT, UHID_GET_REPORT_REPLY, UHID_CREATE2 = 9, 10, 11
UHID_SET_REPORT, UHID_SET_REPORT_REPLY = 13, 14
UHID_EVENT_SIZE = 4380
BUS_USB = 3
# uhid report type -> USB HID report type (feature, output, input)
USB_RTYPE = {0: 3, 1: 2, 2: 1}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


class Dongle:
    def __init__(self, sysname):
        self.sysfs = '/sys/bus/usb/devices/' + sysname
        rd = lambda n: open(os.path.join(self.sysfs, n)).read().strip()
        self.vid, self.pid = int(rd('idVendor'), 16), int(rd('idProduct'), 16)
        self.version = int(rd('bcdDevice'), 16)
        self.name = rd('product')  # programs match on this exact string
        node = '/dev/bus/usb/%03d/%03d' % (int(rd('busnum')), int(rd('devnum')))
        self.fd = os.open(node, os.O_RDWR)

    def present(self):
        return os.path.exists(self.sysfs)

    def control(self, req_type, request, value, index, data_or_len, timeout=2000):
        if isinstance(data_or_len, int):
            length, buf = data_or_len, ctypes.create_string_buffer(max(data_or_len, 1))
        else:
            length, buf = len(data_or_len), ctypes.create_string_buffer(bytes(data_or_len), max(len(data_or_len), 1))
        arg = bytearray(struct.pack('<BBHHHI4xQ', req_type, request, value, index, length,
                                    timeout, ctypes.addressof(buf)))
        n = fcntl.ioctl(self.fd, USBDEVFS_CONTROL, arg, True)
        return buf.raw[:n]

    def report_descriptor(self):
        return self.control(0x81, 6, 0x2200, 0, 512)

    def get_report(self, rtype, rnum, length):
        return self.control(0xA1, 0x01, (rtype << 8) | rnum, 0, length)

    def set_report(self, rtype, rnum, data):
        self.control(0x21, 0x09, (rtype << 8) | rnum, 0, data)


def report_length(desc):
    """Bytes in the (single, unnumbered) report: report size * report count."""
    size = count = 0
    i = 0
    while i < len(desc):
        tag, n = desc[i] & 0xFC, desc[i] & 3
        n = 4 if n == 3 else n
        val = int.from_bytes(desc[i + 1:i + 1 + n], 'little')
        if tag == 0x74:
            size = val
        elif tag == 0x94:
            count = val
        i += 1 + n
    return max(1, size * count // 8)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    dongle = Dongle(sys.argv[1])
    desc = dongle.report_descriptor()
    rlen = report_length(desc)
    log('dongle %04x:%04x "%s", report descriptor %d bytes, report %d bytes'
        % (dongle.vid, dongle.pid, dongle.name, len(desc), rlen))

    uhid = os.open('/dev/uhid', os.O_RDWR)
    create = struct.pack('<I128s64s64sHHIIII', UHID_CREATE2, dongle.name.encode()[:127],
                         ('rockey-bridge/' + sys.argv[1]).encode()[:63], b'',
                         len(desc), BUS_USB, dongle.vid, dongle.pid, dongle.version, 0) + desc
    os.write(uhid, create)

    def strip_id(rnum, data):
        # hidraw passes unnumbered reports with a leading 0 byte; USB wants it gone
        return data[1:] if rnum == 0 and len(data) == rlen + 1 and data[0] == 0 else data

    poller = select.poll()
    poller.register(uhid, select.POLLIN)
    while True:
        if not poller.poll(2000):
            if not dongle.present():
                log('dongle removed, exiting')
                break
            continue
        ev = os.read(uhid, UHID_EVENT_SIZE)
        etype = struct.unpack_from('<I', ev)[0]
        try:
            if etype == UHID_GET_REPORT:
                rid, rnum, rtype = struct.unpack_from('<IBB', ev, 4)
                err, data = 0, b''
                try:
                    data = dongle.get_report(USB_RTYPE.get(rtype, 3), rnum, rlen)
                    if rnum == 0:
                        data = b'\0' + data  # same layout usbhid gives hidraw
                except OSError as e:
                    err = e.errno or errno.EIO
                    log('get_report failed:', e)
                os.write(uhid, struct.pack('<IIHH', UHID_GET_REPORT_REPLY, rid, err, len(data)) + data)
            elif etype == UHID_SET_REPORT:
                rid, rnum, rtype, size = struct.unpack_from('<IBBH', ev, 4)
                data = strip_id(rnum, ev[12:12 + size])
                err = 0
                try:
                    dongle.set_report(USB_RTYPE.get(rtype, 3), rnum, data)
                except OSError as e:
                    err = e.errno or errno.EIO
                    log('set_report failed:', e)
                os.write(uhid, struct.pack('<IIH', UHID_SET_REPORT_REPLY, rid, err))
            elif etype == UHID_OUTPUT:
                size, rtype = struct.unpack_from('<HB', ev, 4 + 4096)
                data = ev[4:4 + size]
                try:
                    dongle.set_report(USB_RTYPE.get(rtype, 2), 0, strip_id(0, data))
                except OSError as e:
                    log('output report failed:', e)
        except OSError as e:
            if e.errno == errno.ENODEV or not dongle.present():
                log('dongle removed, exiting')
                break
            raise
    os.write(uhid, struct.pack('<I', UHID_DESTROY))


if __name__ == '__main__':
    main()
