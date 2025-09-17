#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nctodxf: zmiana nazw NC + generowanie DXF (OUTER + cutout) z licencją offline (.lic obok programu).

Metadane DXF:
- $LASTSAVEDBY = "PRIMES sp. z o.o. / nctodxf"
- XDATA (appid: NCTODXF) na MODEL_SPACE.block_record:
  program, owner, version, license_to, license_fp, license_expires, generated

Łuki (AK/IK): bulge > 0 = CCW gdy k > 0. XY 1:1 z NC1.
"""

import math, re, sys, json, base64, platform, subprocess, uuid
from pathlib import Path
from tkinter import Tk, filedialog
from datetime import datetime, date
from ezdxf.document import Drawing
import _cffi_backend  # wymusza zapakowanie przez PyInstaller

import ezdxf
from nacl import signing, exceptions as nacl_exc

# ====== KONFIG / BRAND ======
PROGRAM_NAME    = "nctodxf"
PROGRAM_OWNER   = "PRIMES sp. z o.o."
PROGRAM_VERSION = "1.0.0"

# Wklej swój publiczny klucz (Base64 z gen_keys.py / license_gui.py):
PUBLIC_KEY_BASE64 = "cJrzx9tGemj8dGrZC1gVek+vohIP4iiJ2dYMJ5WyePI="

# Batch ustawienia
TARGET_EXT = ".nc1"
RECURSIVE  = False

# --- stałe/regex ---
EPS = 1e-9
FLOAT_RE = r"[+-]?\d+(?:[.,]\d+)?"
TAG_RE   = re.compile(r"^[A-Z]{2}\s*$")

# ---------- fingerprint ----------
def get_program_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def get_machine_fingerprint() -> str:
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
                    out = subprocess.check_output(["wmic","csproduct","get","uuid"], text=True, stderr=subprocess.DEVNULL)
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
                out = subprocess.check_output(["ioreg","-rd1","-c","IOPlatformExpertDevice"], text=True)
                for line in out.splitlines():
                    if "IOPlatformUUID" in line:
                        ident = line.split("=",1)[1].strip().strip('"')
                        break
            except Exception:
                pass
    except Exception:
        pass
    if not ident:
        ident = f"MAC-{uuid.getnode():012X}"
    prefix = {"windows":"WIN","linux":"LIN","darwin":"MAC"}.get(sysname,"UNK")
    return f"{prefix}|{ident}".upper()

def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

def verify_license_or_exit():
    """
    Weryfikuje program.lic (obok EXE/skryptu), zwraca payload licencji (dict),
    m.in. {"fp","name","expires", "features"}.
    """
    lic_path = get_program_dir() / "program.lic"
    if not lic_path.exists():
        fp = get_machine_fingerprint()
        print(f"❌ Brak pliku licencji program.lic obok programu.\n   Fingerprint tego komputera: {fp}")
        input("\nNaciśnij Enter, aby zamknąć...")
        sys.exit(1)

    try:
        data = json.loads(lic_path.read_text(encoding="utf-8"))
        payload = data["payload"]
        sig_b64 = data["sig"]
    except Exception:
        print("❌ Nieprawidłowy format pliku licencji (JSON).")
        input("\nNaciśnij Enter, aby zamknąć...")
        sys.exit(1)

    try:
        vk = signing.VerifyKey(base64.b64decode(PUBLIC_KEY_BASE64))
    except Exception:
        print("❌ PUBLIC_KEY_BASE64 w programie jest nieprawidłowy. Wklej klucz z generatora.")
        input("\nNaciśnij Enter, aby zamknąć...")
        sys.exit(1)

    msg = canonical_bytes(payload)
    try:
        vk.verify(msg, base64.b64decode(sig_b64))
    except nacl_exc.BadSignatureError:
        print("❌ Podpis licencji nieprawidłowy.")
        input("\nNaciśnij Enter, aby zamknąć...")
        sys.exit(1)

    # fingerprint
    fp_here = get_machine_fingerprint()
    if payload.get("fp","").upper() != fp_here:
        print("❌ Licencja nie pasuje do tego komputera.")
        print(f"   W licencji: {payload.get('fp')}\n   Ten komputer: {fp_here}")
        input("\nNaciśnij Enter, aby zamknąć...")
        sys.exit(1)

    # data ważności
    exp = payload.get("expires")
    if exp:
        try:
            if date.today() > datetime.strptime(exp, "%Y-%m-%d").date():
                print(f"❌ Licencja wygasła: {exp}")
                input("\nNaciśnij Enter, aby zamknąć...")
                sys.exit(1)
        except Exception:
            pass

    return payload  # <-- użyjemy do komunikatu i metadanych

# ---------- utils DXF/NC ----------
def sanitize(text: str) -> str:
    if not text:
        return "NA"
    return re.sub(r'[\\/:*?"<>|\r\n]+', "_", text.strip())

def fnum(s: str) -> float:
    return float(s.replace(",", "."))

def to_float(s: str):
    try:
        return float(s.replace(",", "."))
    except Exception:
        return None

def norm_num(s: str) -> str | None:
    v = to_float(s)
    if v is None:
        return None
    return f"{v:.3f}".rstrip("0").rstrip(".")

def parse_header_fields(lines):
    try:
        st_idx = next(i for i, ln in enumerate(lines) if ln.strip().upper() == "ST")
    except StopIteration:
        st_idx = -1
    seq = []
    src = lines[st_idx+1:] if st_idx >= 0 else lines
    for ln in src[:30]:
        s = ln.strip()
        if not s or s.startswith("**"):
            continue
        seq.append(s)
        if len(seq) >= 9:
            break
    ID         = seq[0] if len(seq) > 0 else ""
    type_code  = seq[1] if len(seq) > 1 else ""
    piece      = seq[2] if len(seq) > 2 else ""
    assembly   = seq[3] if len(seq) > 3 else ""
    grade      = seq[4] if len(seq) > 4 else ""
    qty        = seq[5] if len(seq) > 5 else ""
    profile    = seq[6] if len(seq) > 6 else ""
    try:
        b_idx = next(i for i, ln in enumerate(lines) if ln.strip().upper() == "B")
    except StopIteration:
        b_idx = -1
    return piece, assembly, grade, qty, profile, type_code, b_idx

def parse_thickness_from_B(lines, b_idx):
    if b_idx < 0:
        return None
    vals = []
    for ln in lines[b_idx+1:b_idx+1+20]:
        s = ln.strip()
        if not s:
            continue
        m = re.search(r'([+-]?\d+(?:[.,]\d+)?)', s)
        if m:
            vals.append(m.group(1))
        if len(vals) >= 12:
            break
    if len(vals) >= 3:
        return norm_num(vals[2])
    return None

def pick_qty_simple(qty_str: str) -> str:
    try:
        q = int(qty_str.strip())
        return str(q if q > 0 else 1)
    except Exception:
        return "1"

def pick_grade_simple(grade: str, lines):
    if grade and grade.strip():
        return grade.strip().upper()
    patterns = [r'\bS[2-9][0-9]{2}[A-Z0-9]{0,3}\b', r'\bA36\b', r'\b1\.[0-9]{4}\b']
    for rx in patterns:
        pat = re.compile(rx, re.IGNORECASE)
        for ln in lines[:60]:
            m = pat.search(ln)
            if m:
                return m.group(0).upper()
    return "NA"

def parse_nc1_for_name(text: str, fallback_stem: str):
    lines = text.splitlines()
    piece, assembly, grade_raw, qty_raw, profile, type_code, b_idx = parse_header_fields(lines)
    name = piece if piece else fallback_stem
    thickness = parse_thickness_from_B(lines, b_idx)
    grade = pick_grade_simple(grade_raw, lines)
    qty = pick_qty_simple(qty_raw)
    name = sanitize(name)
    grade = sanitize(grade)
    thickness = sanitize(thickness if thickness else "NA")
    return name, thickness, grade, qty

def tokenize_blocks(text: str):
    lines = text.splitlines()
    cur_tag = None
    cur = []
    for ln in lines:
        s = ln.strip()
        if TAG_RE.fullmatch(s):
            if cur_tag is not None:
                yield cur_tag, cur
                cur = []
            cur_tag = s
            if cur_tag == "EN":
                break
        else:
            if cur_tag is not None:
                cur.append(ln)
    if cur_tag is not None and cur_tag != "EN":
        yield cur_tag, cur

def parse_points_k(block_lines):
    pts = []
    for ln in block_lines:
        nums = re.findall(FLOAT_RE, ln)
        if len(nums) >= 2:
            x = fnum(nums[0]); y = fnum(nums[1])
            k = fnum(nums[2]) if len(nums) >= 3 else 0.0
            pts.append((x,y,k))
    return pts

def bulge_from_points_radius(p1, p2, r, ccw=True):
    d = math.dist(p1, p2)
    if r < EPS:
        return 0.0
    arg = max(-1.0, min(1.0, d/(2.0*r)))
    theta = 2.0 * math.asin(arg)
    b = math.tan(theta/4.0)
    return b if ccw else -b

def build_xyb_from_points(pts):
    n = len(pts)
    if n < 2:
        return []
    out = []
    for i in range(n):
        x,y,k = pts[i]
        x2,y2,_ = pts[(i+1)%n]
        if abs(k) < EPS:
            b = 0.0
        else:
            r = abs(k)
            ccw = (k > 0)
            b = bulge_from_points_radius((x,y),(x2,y2), r, ccw=ccw)
        out.append((x,y,b))
    return out

def add_slot_capsule(msp, c1, c2, dia, layer="cutout"):
    x1, y1 = c1
    x2, y2 = c2
    r = dia / 2.0
    dx, dy = (x2 - x1, y2 - y1)
    L = math.hypot(dx, dy)
    if L < EPS:
        if r > 0:
            msp.add_circle((x1, y1), r, dxfattribs={"layer": layer})
        return
    nx, ny = -dy / L, dx / L   # normalny CCW
    P0 = (x1 - nx*r, y1 - ny*r)
    P1 = (x2 - nx*r, y2 - ny*r)
    P2 = (x2 + nx*r, y2 + ny*r)
    P3 = (x1 + nx*r, y1 + ny*r)
    verts_xyb = [
        (P0[0], P0[1], 0.0),
        (P1[0], P1[1], 1.0),
        (P2[0], P2[1], 0.0),
        (P3[0], P3[1], 1.0),
    ]
    msp.add_lwpolyline(verts_xyb, format="xyb", close=True, dxfattribs={"layer": layer})

def add_doc_metadata(doc: Drawing, msp, lic_payload: dict) -> None:
    """Ustawia $LASTSAVEDBY i XDATA (appid NCTODXF) z informacjami o pochodzeniu."""
    # 1) $LASTSAVEDBY
    try:
        doc.header["$LASTSAVEDBY"] = f"{PROGRAM_OWNER} / {PROGRAM_NAME}"
    except Exception:
        pass

    # 2) AppID do XDATA
    try:
        doc.appids.add("NCTODXF")
    except ezdxf.DXFTableEntryError:
        pass  # już istnieje

    # 3) Zestaw metadanych jako XDATA na block_record modelspace (nie-rysowalne)
    try:
        lic_name    = lic_payload.get("name", "")
        lic_fp      = lic_payload.get("fp", "")
        lic_expires = lic_payload.get("expires") or "bezterminowo"
        now_iso     = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

        xdata = [
            (1000, f"program={PROGRAM_NAME}"),
            (1000, f"owner={PROGRAM_OWNER}"),
            (1000, f"version={PROGRAM_VERSION}"),
            (1000, f"license_to={lic_name}"),
            (1000, f"license_fp={lic_fp}"),
            (1000, f"license_expires={lic_expires}"),
            (1000, f"generated={now_iso}"),
        ]
        msp.block_record.set_xdata("NCTODXF", xdata)
    except Exception:
        pass

def generate_dxf_from_nc_text(txt: str, out_path: Path, lic_payload: dict):
    outer_pts = None
    inner_contours = []
    bo_items = []

    for tag, lines in tokenize_blocks(txt):
        if tag == "AK":
            outer_pts = parse_points_k(lines)
        elif tag == "IK":
            pts = parse_points_k(lines)
            if pts:
                inner_contours.append(pts)
        elif tag == "BO":
            for ln in lines:
                nums = re.findall(FLOAT_RE, ln)
                is_slot = ("l" in ln.lower())
                if is_slot and len(nums) >= 6:
                    x = fnum(nums[0]); y = fnum(nums[1]); dia = fnum(nums[2])
                    dx = fnum(nums[4]); dy = fnum(nums[5])
                    c1 = (x, y); c2 = (x + dx, y + dy)
                    bo_items.append(("slot", c1, c2, dia))
                elif len(nums) >= 3:
                    x = fnum(nums[0]); y = fnum(nums[1]); dia = fnum(nums[2])
                    bo_items.append(("circle", (x, y), None, dia))

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # Warstwy
    if "OUTER" not in doc.layers:
        doc.layers.add("OUTER")
    if "cutout" not in doc.layers:
        doc.layers.add("cutout", color=4)  # cyan
    else:
        doc.layers.get("cutout").dxf.color = 4

    # OUTER
    if outer_pts:
        verts = build_xyb_from_points(outer_pts)
        if verts:
            msp.add_lwpolyline(verts, format="xyb", close=True, dxfattribs={"layer": "OUTER"})

    # IK
    for pts in inner_contours:
        iverts = build_xyb_from_points(pts)
        if iverts:
            msp.add_lwpolyline(iverts, format="xyb", close=True, dxfattribs={"layer": "cutout"})

    # BO
    for item in bo_items:
        kind = item[0]
        if kind == "circle":
            _, (x, y), _, dia = item
            r = dia / 2.0
            if r > 0:
                msp.add_circle((x, y), r, dxfattribs={"layer": "cutout"})
        elif kind == "slot":
            _, c1, c2, dia = item
            add_slot_capsule(msp, c1, c2, dia, layer="cutout")

    # Metadane dokumentu
    add_doc_metadata(doc, msp, lic_payload)

    # Zapis
    try:
        if out_path.exists():
            out_path.unlink()
    except Exception:
        pass
    doc.saveas(out_path)

# ---------- main ----------
def main():
    lic = verify_license_or_exit()

    # Komunikat branding/licencja:
    lic_to = lic.get("name","(brak)")
    exp    = lic.get("expires")
    period = "bezterminowo" if not exp else f"do {exp}"
    print(f"{PROGRAM_NAME} — właściciel: {PROGRAM_OWNER}")
    print(f"Licencja przypisana dla: {lic_to} — okres: {period}\n")

    Tk().withdraw()
    folder = filedialog.askdirectory(title="Wybierz katalog z plikami DSTV/NC")
    if not folder:
        print("❌ Nie wybrano katalogu – koniec programu.")
        sys.exit(0)

    root = Path(folder)
    globber = "**/*" if RECURSIVE else "*"
    candidates = [p for p in root.glob(globber)
                  if p.is_file() and p.suffix.lower() in (".nc", ".nc1", ".dstv")]

    if not candidates:
        print("Brak plików .nc/.nc1/.dstv w wybranym katalogu.")
        input("\nNaciśnij Enter, aby zamknąć...")
        return

    renamed = 0
    dxf_ok = 0
    dxf_err = 0

    for p in candidates:
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"⚠️  {p.name}: błąd odczytu ({e})")
            continue

        name, thickness, grade, qty = parse_nc1_for_name(txt, fallback_stem=p.stem)
        new_stem = f"{grade}-{thickness}-({name})-{qty}"
        new_name = sanitize(new_stem) + TARGET_EXT
        target = p.with_name(new_name)

        try:
            if target.name != p.name:
                if target.exists() and target != p:
                    target.unlink()
                p.rename(target)
                print(f"✅ {p.name}  ->  {target.name}")
                renamed += 1
                final_nc_path = target
            else:
                print(f"=  {p.name} (już poprawna)")
                final_nc_path = p
        except Exception as e:
            print(f"❌ {p.name}: błąd zmiany nazwy ({e})")
            final_nc_path = p

        out_dxf = final_nc_path.with_suffix(".dxf")
        try:
            generate_dxf_from_nc_text(txt, out_dxf, lic_payload=lic)
            print(f"   ↳ DXF: {out_dxf.name} ✔")
            dxf_ok += 1
        except Exception as e:
            print(f"   ↳ DXF: {out_dxf.name} ✖  ({e})")
            dxf_err += 1

    print(f"\nGotowe. Zmieniono nazw: {renamed}. DXF OK: {dxf_ok}, błędów DXF: {dxf_err}.")
    input("\nNaciśnij Enter, aby zamknąć...")

if __name__ == "__main__":
    main()
