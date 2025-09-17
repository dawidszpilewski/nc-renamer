#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wystawia licencję .lic:
  payload = { "fp": "...", "name": "...", "expires": "YYYY-MM-DD" | null, "features": [...] }
  plik licencji = {"payload": payload, "sig": "<base64-ed25519-signature>"}

Użycie:
  python issue_license.py --key private_key.pem --fp "WIN|..." --name "Klient" \
                          --expires 2026-12-31 --out program.lic
  # expires można pominąć → licencja bezterminowa
"""

import argparse, json, base64, sys
from pathlib import Path
from datetime import datetime
from nacl import signing, encoding

def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True, help="private_key.pem (Base64 z gen_keys.py)")
    ap.add_argument("--fp", required=True, help="Fingerprint komputera (WIN|..., LIN|..., MAC|...)")
    ap.add_argument("--name", required=True, help="Nazwa klienta / użytkownika")
    ap.add_argument("--expires", default=None, help="Data YYYY-MM-DD lub pomiń dla bezterminowej")
    ap.add_argument("--features", default="DXF", help="CSV cech, np. DXF,RENAMER")
    ap.add_argument("--out", default="program.lic", help="Nazwa pliku licencji")
    args = ap.parse_args()

    sk_b64 = Path(args.key).read_bytes()
    try:
        sk = signing.SigningKey(sk_b64, encoder=encoding.Base64Encoder)
    except Exception:
        print("❌ Nieprawidłowy plik klucza prywatnego (spodziewany Base64 Ed25519).")
        sys.exit(1)

    expires = args.expires
    if expires:
        # walidacja formatu
        try:
            datetime.strptime(expires, "%Y-%m-%d")
        except ValueError:
            print("❌ Data expires musi być w formacie YYYY-MM-DD (np. 2026-12-31).")
            sys.exit(1)
    else:
        expires = None

    features = [s.strip() for s in args.features.split(",") if s.strip()] or ["DXF"]

    payload = {
        "fp": args.fp.strip().upper(),
        "name": args.name.strip(),
        "expires": expires,
        "features": features,
    }
    msg = canonical_bytes(payload)
    sig = sk.sign(msg).signature
    lic = {
        "payload": payload,
        "sig": base64.b64encode(sig).decode(),
    }
    Path(args.out).write_text(json.dumps(lic, indent=2), encoding="utf-8")
    print(f"✅ Zapisano licencję: {args.out}")
    print(f"   fp={payload['fp']}  expires={payload['expires']}  features={features}")

if __name__ == "__main__":
    main()
