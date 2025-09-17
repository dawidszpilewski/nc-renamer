#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Generuje klucze Ed25519: private_key.pem, public_key.pem i pokazuje publiczny w Base64.

from nacl import signing, encoding
from pathlib import Path

def main():
    sk = signing.SigningKey.generate()
    pk = sk.verify_key

    priv_pem = sk.encode(encoder=encoding.Base64Encoder)
    pub_raw = pk.encode()  # 32 bajty
    pub_b64 = encoding.Base64Encoder.encode(pub_raw)

    Path("private_key.pem").write_bytes(priv_pem)
    Path("public_key.pem").write_bytes(pub_raw)

    print("✅ Wygenerowano klucze:")
    print(" - private_key.pem  (Base64, trzymaj w tajemnicy!)")
    print(" - public_key.pem   (surowe 32 bajty)")
    print("\n🔑 PUBLIC_KEY_BASE64 (wklej do main_app.py):")
    print(pub_b64.decode())

if __name__ == "__main__":
    main()
