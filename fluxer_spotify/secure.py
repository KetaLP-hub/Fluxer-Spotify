"""Encrypt secrets at rest, stdlib only (CONTRIBUTING: no new dependencies).

Windows: DPAPI (CryptProtectData / CryptUnprotectData) through ctypes. The blob can only be decrypted by the same
Windows user on the same machine, so a copied or leaked state.json is useless to anyone else.
Elsewhere there is no backend (`default_backend()` returns None) and Store keeps plaintext with mode 0600.

A backend has `prefix` (marks sealed values in state.json), `name`, `protect(bytes) -> bytes`, `unprotect(bytes) -> bytes`.
"""
import os

CRYPTPROTECT_UI_FORBIDDEN = 0x1


class Dpapi:
    prefix = "dpapi:"
    name = "Windows DPAPI"

    @staticmethod
    def _call(function, data):
        import ctypes
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        fn = getattr(crypt32, function)
        fn.restype = wintypes.BOOL
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                       ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        buf = ctypes.create_string_buffer(data, len(data))  # keeps the input alive during the call
        src = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        out = Blob()
        if not fn(ctypes.byref(src), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
            raise OSError(f"{function} failed (error {ctypes.get_last_error()})")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))

    def protect(self, data):
        return self._call("CryptProtectData", data)

    def unprotect(self, blob):
        return self._call("CryptUnprotectData", blob)


def default_backend():
    return Dpapi() if os.name == "nt" else None
