"""Locate an MSI installation without changing portable layouts."""

import os
from pathlib import Path
import sys


INSTALL_KEY = r'Software\ComiTrans\Installer'


def installed_product(root):
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, INSTALL_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            directory, _ = winreg.QueryValueEx(key, 'InstallDir')
            product, _ = winreg.QueryValueEx(key, 'ProductCode')
        if Path(directory).resolve() == Path(root).resolve():
            return product
    except (OSError, TypeError, ValueError):
        pass
    return None


def data_directory(root):
    local = Path(os.environ.get('LOCALAPPDATA', ''))
    if local.is_absolute() and installed_product(root):
        return local / 'ComiTrans'
    return Path(root)


def original_package(product):
    """Return the source MSI when it is still available, e.g. in Downloads."""
    from ctypes import WinDLL, byref, create_unicode_buffer
    from ctypes.wintypes import DWORD, LPCWSTR, LPWSTR, PDWORD

    info = WinDLL('msi.dll').MsiGetProductInfoW
    info.argtypes = (LPCWSTR, LPCWSTR, LPWSTR, PDWORD)
    info.restype = DWORD

    def read(name):
        buffer = create_unicode_buffer(32768)
        size = DWORD(len(buffer))
        return buffer.value if info(product, name, buffer, byref(size)) == 0 else ''

    source, name = Path(read('InstallSource')), read('PackageName')
    if source.is_absolute() and name and Path(name).name == name:
        return source / name
    return None
