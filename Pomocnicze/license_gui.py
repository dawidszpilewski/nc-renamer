#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# GUI: generator kluczy (Ed25519) + wystawca licencji .lic (offline, podpis ed25519).
# Zależności: tkinter (wbudowane), PyNaCl

import json, base64, os
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from nacl import signing, encoding, exceptions as nacl_exc

APP_TITLE = "NC2DXF – Generator kluczy i licencji"
DEFAULT_FEATURES = "DXF"  # CSV

# ---------- helpers ----------
def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

def is_valid_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False

def copy_to_clipboard(win: tk.Tk, text: str):
    try:
        win.clipboard_clear()
        win.clipboard_append(text)
        win.update()
    except Exception:
        pass

# ---------- GUI app ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("720x560")
        self.minsize(680, 520)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.frame_keys = ttk.Frame(self.notebook)
        self.frame_lic  = ttk.Frame(self.notebook)

        self.notebook.add(self.frame_keys, text="Klucze (Ed25519)")
        self.notebook.add(self.frame_lic,  text="Licencja (.lic)")

        self.build_keys_tab()
        self.build_license_tab()

    # ----- Tab: keys -----
    def build_keys_tab(self):
        frm = self.frame_keys

        row = 0
        ttk.Label(frm, text="Prywatny klucz (Base64) – ZAPISZ do pliku i trzymaj w tajemnicy:", font=("Segoe UI", 10, "bold")).grid(row=row, column=0, sticky="w", padx=8, pady=(12,6), columnspan=3)
        row += 1
        self.txt_priv = tk.Text(frm, height=6, wrap="word")
        self.txt_priv.grid(row=row, column=0, columnspan=3, sticky="nsew", padx=8)
        row += 1

        ttk.Label(frm, text="Publiczny klucz (Base64) – wklej do main_app.py → PUBLIC_KEY_BASE64:", font=("Segoe UI", 10, "bold")).grid(row=row, column=0, sticky="w", padx=8, pady=(12,6), columnspan=3)
        row += 1
        self.txt_pub = tk.Text(frm, height=3, wrap="none")
        self.txt_pub.grid(row=row, column=0, columnspan=3, sticky="nsew", padx=8)
        row += 1

        btn_gen = ttk.Button(frm, text="Generuj parę kluczy", command=self.gen_keys)
        btn_gen.grid(row=row, column=0, sticky="w", padx=8, pady=10)

        btn_save_priv = ttk.Button(frm, text="Zapisz prywatny klucz do pliku…", command=self.save_private_key_to_file)
        btn_save_priv.grid(row=row, column=1, sticky="w", padx=8, pady=10)

        btn_copy_pub = ttk.Button(frm, text="Skopiuj publiczny do schowka", command=lambda: copy_to_clipboard(self, self.txt_pub.get("1.0","end").strip()))
        btn_copy_pub.grid(row=row, column=2, sticky="e", padx=8, pady=10)

        # grid weights
        frm.rowconfigure(1, weight=1)
        frm.rowconfigure(3, weight=1)
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=0)
        frm.columnconfigure(2, weight=0)

    def gen_keys(self):
        sk = signing.SigningKey.generate()
        pk = sk.verify_key
        priv_b64 = encoding.Base64Encoder.encode(sk.encode()).decode()
        pub_b64  = encoding.Base64Encoder.encode(pk.encode()).decode()

        self.txt_priv.delete("1.0","end")
        self.txt_priv.insert("1.0", priv_b64)
        self.txt_pub.delete("1.0","end")
        self.txt_pub.insert("1.0", pub_b64)

        messagebox.showinfo("Gotowe", "Wygenerowano parę kluczy.\nZapisz prywatny do pliku i przechowuj bezpiecznie.")

    def save_private_key_to_file(self):
        data = self.txt_priv.get("1.0","end").strip()
        if not data:
            messagebox.showwarning("Brak danych", "Najpierw wygeneruj lub wklej prywatny klucz (Base64).")
            return
        path = filedialog.asksaveasfilename(
            title="Zapisz prywatny klucz",
            defaultextension=".pem",
            filetypes=[("PEM/Base64", "*.pem"), ("Wszystkie pliki", "*.*")]
        )
        if not path:
            return
        try:
            Path(path).write_text(data, encoding="utf-8")
            messagebox.showinfo("Zapisano", f"Zapisano prywatny klucz do:\n{path}")
        except Exception as e:
            messagebox.showerror("Błąd zapisu", str(e))

    # ----- Tab: license -----
    def build_license_tab(self):
        frm = self.frame_lic

        # Private key source
        grp_key = ttk.LabelFrame(frm, text="Prywatny klucz (Base64 z pliku .pem albo wklejony)")
        grp_key.grid(row=0, column=0, sticky="ew", padx=8, pady=(10,6), columnspan=3)
        grp_key.columnconfigure(1, weight=1)

        ttk.Label(grp_key, text="Źródło klucza:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.var_key_mode = tk.StringVar(value="file")
        rb_file = ttk.Radiobutton(grp_key, text="Plik…", variable=self.var_key_mode, value="file")
        rb_text = ttk.Radiobutton(grp_key, text="Wklejony tekst", variable=self.var_key_mode, value="text")
        rb_file.grid(row=0, column=1, sticky="w", padx=4)
        rb_text.grid(row=0, column=2, sticky="w", padx=4)

        self.ent_keyfile = ttk.Entry(grp_key)
        self.ent_keyfile.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0,8))
        btn_browse = ttk.Button(grp_key, text="Wybierz plik…", command=self.browse_key_file)
        btn_browse.grid(row=1, column=2, sticky="w", padx=4, pady=(0,8))

        self.txt_keytext = tk.Text(grp_key, height=4, wrap="word")
        self.txt_keytext.grid(row=2, column=0, columnspan=3, sticky="ew", padx=8, pady=(0,8))

        # Payload
        grp_payload = ttk.LabelFrame(frm, text="Dane licencji")
        grp_payload.grid(row=1, column=0, sticky="nsew", padx=8, pady=6, columnspan=3)
        for c in range(2):
            grp_payload.columnconfigure(c, weight=1)

        ttk.Label(grp_payload, text="Fingerprint (WIN|... / LIN|... / MAC|...)").grid(row=0, column=0, sticky="w", padx=8, pady=(8,2))
        self.ent_fp = ttk.Entry(grp_payload)
        self.ent_fp.grid(row=1, column=0, sticky="ew", padx=8, pady=(0,8))

        ttk.Label(grp_payload, text="Nazwa klienta / użytkownika").grid(row=0, column=1, sticky="w", padx=8, pady=(8,2))
        self.ent_name = ttk.Entry(grp_payload)
        self.ent_name.grid(row=1, column=1, sticky="ew", padx=8, pady=(0,8))

        self.var_noexp = tk.BooleanVar(value=True)
        chk_noexp = ttk.Checkbutton(grp_payload, text="Bezterminowa", variable=self.var_noexp, command=self.toggle_expiry)
        chk_noexp.grid(row=2, column=0, sticky="w", padx=8, pady=(0,2))

        ttk.Label(grp_payload, text="Data wygaśnięcia (YYYY-MM-DD)").grid(row=2, column=1, sticky="w", padx=8, pady=(0,2))
        self.ent_exp = ttk.Entry(grp_payload)
        self.ent_exp.grid(row=3, column=1, sticky="ew", padx=8, pady=(0,8))
        self.ent_exp.configure(state="disabled")  # domyślnie bezterminowa

        ttk.Label(grp_payload, text="Funkcje (CSV)").grid(row=3, column=0, sticky="w", padx=8, pady=(0,2))
        self.ent_features = ttk.Entry(grp_payload)
        self.ent_features.insert(0, DEFAULT_FEATURES)
        self.ent_features.grid(row=4, column=0, sticky="ew", padx=8, pady=(0,8))

        # Output
        grp_out = ttk.LabelFrame(frm, text="Wynik")
        grp_out.grid(row=2, column=0, sticky="nsew", padx=8, pady=(6,8), columnspan=3)
        grp_out.rowconfigure(1, weight=1)
        grp_out.columnconfigure(0, weight=1)

        self.txt_preview = tk.Text(grp_out, height=10, wrap="none")
        self.txt_preview.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=8, pady=(0,8))

        btn_gen = ttk.Button(grp_out, text="Generuj licencję (podpisz)", command=self.generate_license)
        btn_gen.grid(row=0, column=0, sticky="w", padx=8, pady=8)

        btn_copy = ttk.Button(grp_out, text="Skopiuj JSON do schowka", command=lambda: copy_to_clipboard(self, self.txt_preview.get("1.0","end").strip()))
        btn_copy.grid(row=0, column=1, sticky="w", padx=8, pady=8)

        btn_save = ttk.Button(grp_out, text="Zapisz do pliku…", command=self.save_license_to_file)
        btn_save.grid(row=0, column=2, sticky="e", padx=8, pady=8)

        # expand rows/cols
        self.frame_lic.rowconfigure(2, weight=1)
        self.frame_lic.columnconfigure(0, weight=1)
        self.frame_lic.columnconfigure(1, weight=1)
        self.frame_lic.columnconfigure(2, weight=1)

    def toggle_expiry(self):
        if self.var_noexp.get():
            self.ent_exp.configure(state="disabled")
            self.ent_exp.delete(0, "end")
        else:
            self.ent_exp.configure(state="normal")

    def browse_key_file(self):
        path = filedialog.askopenfilename(title="Wybierz plik prywatnego klucza (Base64 .pem)",
                                          filetypes=[("PEM/Base64", "*.pem *.txt"), ("Wszystkie pliki","*.*")])
        if not path:
            return
        self.ent_keyfile.delete(0,"end")
        self.ent_keyfile.insert(0, path)

    def read_private_key(self) -> signing.SigningKey | None:
        mode = self.var_key_mode.get()
        data = ""
        if mode == "file":
            p = self.ent_keyfile.get().strip()
            if not p:
                messagebox.showwarning("Brak pliku", "Wskaż plik prywatnego klucza (Base64).")
                return None
            try:
                data = Path(p).read_text(encoding="utf-8").strip()
            except Exception as e:
                messagebox.showerror("Błąd odczytu pliku", str(e))
                return None
        else:
            data = self.txt_keytext.get("1.0","end").strip()
            if not data:
                messagebox.showwarning("Brak klucza", "Wklej prywatny klucz (Base64).")
                return None
        try:
            sk = signing.SigningKey(data.encode(), encoder=encoding.Base64Encoder)
            return sk
        except Exception:
            messagebox.showerror("Błąd klucza", "Nieprawidłowy format prywatnego klucza (spodziewany Base64 Ed25519).")
            return None

    def generate_license(self):
        sk = self.read_private_key()
        if not sk:
            return

        fp = self.ent_fp.get().strip().upper()
        name = self.ent_name.get().strip()
        if not fp or not name:
            messagebox.showwarning("Brak danych", "Uzupełnij Fingerprint oraz Nazwę klienta.")
            return

        if self.var_noexp.get():
            expires = None
        else:
            expires = self.ent_exp.get().strip()
            if not expires or not is_valid_date(expires):
                messagebox.showwarning("Data", "Podaj datę w formacie YYYY-MM-DD lub zaznacz 'Bezterminowa'.")
                return

        features = [s.strip() for s in self.ent_features.get().split(",") if s.strip()] or [DEFAULT_FEATURES]

        payload = {"fp": fp, "name": name, "expires": expires, "features": features}
        msg = canonical_bytes(payload)
        sig = sk.sign(msg).signature
        lic = {"payload": payload, "sig": base64.b64encode(sig).decode()}

        self.txt_preview.delete("1.0","end")
        self.txt_preview.insert("1.0", json.dumps(lic, indent=2, ensure_ascii=False))
        messagebox.showinfo("Gotowe", "Licencja wygenerowana. Zapisz do pliku jako 'program.lic' obok programu.")

    def save_license_to_file(self):
        data = self.txt_preview.get("1.0","end").strip()
        if not data:
            messagebox.showwarning("Brak danych", "Najpierw wygeneruj licencję.")
            return
        path = filedialog.asksaveasfilename(
            title="Zapisz licencję",
            initialfile="program.lic",
            defaultextension=".lic",
            filetypes=[("Plik licencji", "*.lic"), ("JSON", "*.json"), ("Wszystkie pliki", "*.*")]
        )
        if not path:
            return
        try:
            Path(path).write_text(data, encoding="utf-8")
            messagebox.showinfo("Zapisano", f"Zapisano licencję:\n{path}\nSkopiuj plik obok programu (.exe).")
        except Exception as e:
            messagebox.showerror("Błąd zapisu", str(e))


if __name__ == "__main__":
    app = App()
    app.mainloop()
