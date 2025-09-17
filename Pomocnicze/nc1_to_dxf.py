#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch: zmiana nazw NC + generowanie DXF o tych samych nazwach.

DXF:
- OUTER (AK) jako zamknięta LWPOLYLINE (warstwa OUTER)
- cutout (kolor cyan):
    * IK jako LWPOLYLINE
    * BO:
        - CIRCLE dla zwykłych otworów (Ø)
        - sloty/fasolki (w linii jest 'l' + wektor dx,dy) jako LWPOLYLINE
          (2 półokręgi + 2 proste)

Łuki (AK/IK): bulge dodatni (CCW) gdy k > 0. Punkty XY 1:1 z NC1.
"""

import math
import re
import sys
from pathlib import Path
from tkinter import Tk, filedialog
import ezdxf

# ——— Ustawienia ——————————————————————————————————————
TARGET_EXT = ".nc1"   # docelowe rozszerzenie
RECURSIVE = False     # True → skanuj podfoldery

# ——— Util —————————————————————————————————————————————
EPS = 1e-9
FLOAT_RE = r"[+-]?\d+(?:[.,]\d+)?"
TAG_RE = re.compile(r"^[A-Z]{2}\s*$")

def sanitize(text: str) -> str:
    if not text:
        return "NA"
    # zachowujemy nawiasy okrągłe; usuwamy znaki niedozwolone
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

# ——— Parsowanie nagłówka DSTV/NC1 (do nazwy) ————————————
def parse_header_fields(lines):
    """
    Zwraca (piece_mark, assembly_mark, grade, qty, profile, type_code, idx_B)
    Układ typowy dla blach (typ 6):
    ST
    ** (opcjonalny komentarz)
    <ID>
    <TYPE>
    <PIECE>     ← nazwa (bierzemy tę linię)
    <ASSEMBLY>
    <GRADE>
    <QTY>
    <PROFILE>
    B
    """
    # znajdź ST
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

    # znajdź blok B
    try:
        b_idx = next(i for i, ln in enumerate(lines) if ln.strip().upper() == "B")
    except StopIteration:
        b_idx = -1

    return piece, assembly, grade, qty, profile, type_code, b_idx

def parse_thickness_from_B(lines, b_idx):
    """Zwraca grubość (pole nr 3 bloku B)."""
    if b_idx < 0:
        return None
    vals = []
    for ln in lines[b_idx+1 : b_idx+1+20]:
        s = ln.strip()
        if not s:
            continue
        m = re.search(r'([+-]?\d+(?:[.,]\d+)?)', s)
        if m:
            vals.append(m.group(1))
        if len(vals) >= 12:
            break
    if len(vals) >= 3:
        return norm_num(vals[2])  # 3-cia wartość = grubość
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

def parse_nc1(text: str, fallback_stem: str):
    lines = text.splitlines()
    piece, assembly, grade_raw, qty_raw, profile, type_code, b_idx = parse_header_fields(lines)
    name = piece if piece else fallback_stem
    thickness = parse_thickness_from_B(lines, b_idx)
    grade = pick_grade_simple(grade_raw, lines)
    qty = pick_qty_simple(qty_raw)
    # Sanitizacja
    name = sanitize(name)
    grade = sanitize(grade)
    thickness = sanitize(thickness if thickness else "NA")
    return name, thickness, grade, qty

# ——— Parser bloków AK/IK/BO (do DXF) ————————————————
def tokenize_blocks(text: str):
    """Zwraca kolejne bloki (TAG, [linie]) aż do EN."""
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
    """Parser AK/IK: linie z x y [k] -> [(x,y,k), ...]."""
    pts = []
    for ln in block_lines:
        nums = re.findall(FLOAT_RE, ln)
        if len(nums) >= 2:
            x = fnum(nums[0]); y = fnum(nums[1])
            k = fnum(nums[2]) if len(nums) >= 3 else 0.0
            pts.append((x,y,k))
    return pts

def bulge_from_points_radius(p1, p2, r, ccw=True):
    """Bulge dla łuku o promieniu r między p1->p2."""
    d = math.dist(p1, p2)
    if r < EPS:
        return 0.0
    arg = max(-1.0, min(1.0, d/(2.0*r)))
    theta = 2.0 * math.asin(arg)
    b = math.tan(theta/4.0)
    return b if ccw else -b

def build_xyb_from_points(pts):
    """
    Zwraca [(x,y,bulge), ...] dla zamkniętej polilinii,
    zachowując XY dokładnie jak w NC1.
    """
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
            ccw = (k > 0)   # bulge > 0 = CCW
            b = bulge_from_points_radius((x,y),(x2,y2), r, ccw=ccw)
        out.append((x,y,b))
    return out

# ——— Slot helper (BO: 'l' + dx,dy) ————————————————
def add_slot_capsule(msp, c1, c2, dia, layer="cutout"):
    """
    Rysuje slot (fasolkę) jako zamkniętą LWPOLYLINE z 2 łukami (bulge=1) i 2 odcinkami.
    c1, c2 – środki półokręgów (x,y), dia – średnica (szerokość slotu).
    """
    x1, y1 = c1
    x2, y2 = c2
    r = dia / 2.0
    dx, dy = (x2 - x1, y2 - y1)
    L = math.hypot(dx, dy)
    if L < EPS:
        if r > 0:
            msp.add_circle((x1, y1), r, dxfattribs={"layer": layer})
        return
    # oś i normalny (CCW)
    vx, vy = dx / L, dy / L
    nx, ny = -vy, vx   # +90° CCW
    # obrys CCW
    P0 = (x1 - nx*r, y1 - ny*r)
    P1 = (x2 - nx*r, y2 - ny*r)
    P2 = (x2 + nx*r, y2 + ny*r)
    P3 = (x1 + nx*r, y1 + ny*r)
    verts_xyb = [
        (P0[0], P0[1], 0.0),  # linia
        (P1[0], P1[1], 1.0),  # półokrąg CCW
        (P2[0], P2[1], 0.0),  # linia
        (P3[0], P3[1], 1.0),  # półokrąg CCW do P0
    ]
    msp.add_lwpolyline(verts_xyb, format="xyb", close=True,
                       dxfattribs={"layer": layer})

# ——— Generator DXF ————————————————————————————————
def generate_dxf_from_nc_text(txt: str, out_path: Path):
    outer_pts = None
    inner_contours = []   # list[list[(x,y,k)]]
    bo_items = []         # ("circle", (x,y), None, dia) lub ("slot", c1, c2, dia)

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
                # slot: X Y Ø (coś) l dx dy (...)
                if is_slot and len(nums) >= 6:
                    x = fnum(nums[0]); y = fnum(nums[1]); dia = fnum(nums[2])
                    dx = fnum(nums[4]); dy = fnum(nums[5])
                    c1 = (x, y)
                    c2 = (x + dx, y + dy)
                    bo_items.append(("slot", c1, c2, dia))
                elif len(nums) >= 3:
                    # zwykły otwór
                    x = fnum(nums[0]); y = fnum(nums[1]); dia = fnum(nums[2])
                    bo_items.append(("circle", (x, y), None, dia))

    # DXF
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
            msp.add_lwpolyline(verts, format="xyb", close=True,
                               dxfattribs={"layer": "OUTER"})

    # IK -> cutout
    for pts in inner_contours:
        iverts = build_xyb_from_points(pts)
        if iverts:
            msp.add_lwpolyline(iverts, format="xyb", close=True,
                               dxfattribs={"layer": "cutout"})

    # BO -> cutout
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

    # Zapis (nadpisz, jeśli istnieje)
    try:
        if out_path.exists():
            out_path.unlink()
    except Exception:
        pass
    doc.saveas(out_path)

# ——— Program główny ————————————————————————————————
def main():
    # wybór folderu (jak w Twoim kodzie)
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

        # — nowa nazwa — #
        name, thickness, grade, qty = parse_nc1(txt, fallback_stem=p.stem)
        new_stem = f"{grade}-{thickness}-({name})-{qty}"
        new_name = sanitize(new_stem) + TARGET_EXT
        target = p.with_name(new_name)

        # — zmiana nazwy — #
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
            final_nc_path = p  # generuj DXF do bieżącej nazwy

        # — DXF o tym samym stem — #
        out_dxf = final_nc_path.with_suffix(".dxf")
        try:
            generate_dxf_from_nc_text(txt, out_dxf)
            print(f"   ↳ DXF: {out_dxf.name} ✔")
            dxf_ok += 1
        except Exception as e:
            print(f"   ↳ DXF: {out_dxf.name} ✖  ({e})")
            dxf_err += 1

    print(f"\nGotowe. Zmieniono nazw: {renamed}. DXF OK: {dxf_ok}, błędów DXF: {dxf_err}.")
    input("\nNaciśnij Enter, aby zamknąć...")

if __name__ == "__main__":
    main()

