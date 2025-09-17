#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import platform, subprocess, uuid
from pathlib import Path

def get_machine_fingerprint():
    sysname = platform.system().lower()
    ident = None
    try:
        if sysname == "windows":
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
                    ident, _ = winreg.QueryValueEx(k, "MachineGuid")
                    ident = str(ident).strip()
            except Exception:
                try:
                    out = subprocess.check_output(["wmic", "csproduct", "get", "uuid"], text=True)
                    parts = [p.strip() for p in out.splitlines() if p.strip() and "UUID" not in p]
                    if parts:
                        ident = parts[0]
                except Exception:
                    pass
        elif sysname == "linux":
            try:
                ident = Path("/etc/machine-id").read_text().strip()
            except Exception:
                pass
        elif sysname == "darwin":
            try:
                out = subprocess.check_output(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], text=True)
                for line in out.splitlines():
                    if "IOPlatformUUID" in line:
                        ident = line.split("=", 1)[1].strip().strip('"')
                        break
            except Exception:
                pass
    except Exception:
        pass
    if not ident:
        mac = uuid.getnode()
        ident = f"MAC-{mac:012X}"
    prefix = {"windows":"WIN","linux":"LIN","darwin":"MAC"}.get(sysname,"UNK")
    return f"{prefix}|{ident}".upper()

if __name__ == "__main__":
    print(get_machine_fingerprint())
