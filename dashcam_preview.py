"""In-memory, filtered preview resizing using Windows' built-in GDI.

Tk integer zoom/subsample discards pixels before enlarging them. GDI halftone
resampling avoids that thumbnail effect without an extra package or process.
"""
import ctypes
import os
import struct


def resize_ppm(frame: bytes, width: int, height: int) -> bytes:
    magic, dimensions, maximum, rgb = frame.split(b'\n', 3)
    source_width, source_height = map(int, dimensions.split())
    if magic != b'P6' or maximum != b'255' or len(rgb) != source_width * source_height * 3:
        raise ValueError('Invalid preview frame')
    if (width, height) == (source_width, source_height):
        return frame
    if os.name != 'nt':
        # This application targets Windows; retain native detail elsewhere.
        return frame
    if width % 4 or source_width % 4:
        raise ValueError('Preview widths must be aligned to four pixels')
    gdi = ctypes.windll.gdi32
    gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                   ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint]
    gdi.CreateDIBSection.restype = ctypes.c_void_p
    gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi.SelectObject.restype = ctypes.c_void_p
    gdi.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi.SetStretchBltMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
    gdi.SetBrushOrgEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    gdi.StretchDIBits.argtypes = [ctypes.c_void_p, *([ctypes.c_int] * 8), ctypes.c_void_p,
                                 ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
    def header(w, h):
        return ctypes.create_string_buffer(struct.pack('<IiiHHIIiiII', 40, w, -h, 1, 24, 0, w*h*3, 0, 0, 0, 0))
    bgr = bytearray(len(rgb))
    bgr[0::3], bgr[1::3], bgr[2::3] = rgb[2::3], rgb[1::3], rgb[0::3]
    source = (ctypes.c_ubyte * len(bgr)).from_buffer(bgr)
    dc = gdi.CreateCompatibleDC(None)
    bits = ctypes.c_void_p()
    bitmap = gdi.CreateDIBSection(dc, header(width, height), 0, ctypes.byref(bits), None, 0)
    if not dc or not bitmap:
        if bitmap: gdi.DeleteObject(bitmap)
        if dc: gdi.DeleteDC(dc)
        raise OSError('Could not allocate preview surface')
    old = gdi.SelectObject(dc, bitmap)
    try:
        gdi.SetStretchBltMode(dc, 4)  # HALFTONE filtered resampling
        gdi.SetBrushOrgEx(dc, 0, 0, None)
        if gdi.StretchDIBits(dc, 0, 0, width, height, 0, 0, source_width, source_height,
                            source, header(source_width, source_height), 0, 0x00CC0020) <= 0:
            raise OSError('Preview resize failed')
        data = ctypes.string_at(bits, width * height * 3)
        result = bytearray(len(data))
        result[0::3], result[1::3], result[2::3] = data[2::3], data[1::3], data[0::3]
        return f'P6\n{width} {height}\n255\n'.encode() + result
    finally:
        gdi.SelectObject(dc, old)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(dc)
