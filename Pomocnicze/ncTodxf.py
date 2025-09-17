#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NC1 -> DXF:
- OUTER (AK) jako jedna zamknięta LWPOLYLINE (warstwa OUTER)
- CUTS (warstwa cutout):
    * IK (wewnętrzne kontury) jako LWPOLYLINE
    * BO:
        - zwykłe otwory jako CIRCLE (Ø)
        - sloty (fasolki) jako LWPOLYLINE (2 półokręgi + 2 proste)

Zasada segmentów (AK/IK):
  Wiersz:  x y k
  Segment: (x,y) -> (x_next,y_next)
    - k == 0 : linia prosta (bulge=0 przy punkcie startowym)
    - k != 0 : łuk o promieniu |k|, kierunek CCW jeśli k > 0 (bulge > 0)
Punkty XY muszą być 1:1 jak w .nc1 (bez przesuwania).

Slot (BO) wg przykładu:
  "… X  Y  Ø  (pole)  l  dx  dy  (opc.) …"
    X,Y – pierwszy środek półokręgu, Ø – średnica,
    dx,dy – wektor do drugiego środka.
"""

import math
import re
from pathlib import Path
from tkinter import Tk, filedialog
import ezdxf

EPS = 1e-9
FLOAT_RE = r"[+-]?\d+(?:[.,]\d+)?"
TAG_RE = re.compile(r"^[A-Z]{2}\s*$")

# ---------- utils ----------

def fnum(s: str) -> float:
    return float(s.replace(",", "."))

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
    theta = 2.0 * math.asin(arg)   # kąt środkowy
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
            ccw = (k > 0)   # ważne: kierunek łuku wg znaku k
            b = bulge_from_points_radius((x,y),(x2,y2), r, ccw=ccw)
        out.append((x,y,b))
    return out

# ---------- slot helper ----------

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
        # brak długości – zrób zwykły otwór
        if r > 0:
            msp.add_circle((x1, y1), r, dxfattribs={"layer": layer})
        return

    # wektor osi i normalny (CCW)
    vx, vy = dx / L, dy / L
    nx, ny = -vy, vx   # obrót o +90° (CCW)

    # punkty obrysu na kapsule (porządek CCW):
    P0 = (x1 - nx*r, y1 - ny*r)   # start: „prawa” krawędź dolnego łuku
    P1 = (x2 - nx*r, y2 - ny*r)   # prawa krawędź górnego łuku
    P2 = (x2 + nx*r, y2 + ny*r)   # lewa krawędź górnego łuku
    P3 = (x1 + nx*r, y1 + ny*r)   # lewa krawędź dolnego łuku

    # półokręgi: bulge = tan(pi/4) = 1 (dodatni => CCW)
    verts_xyb = [
        (P0[0], P0[1], 0.0),  # P0 -> P1 (linia)
        (P1[0], P1[1], 1.0),  # P1 -> P2 (łuk górny CCW)
        (P2[0], P2[1], 0.0),  # P2 -> P3 (linia)
        (P3[0], P3[1], 1.0),  # P3 -> P0 (łuk dolny CCW)
    ]

    msp.add_lwpolyline(verts_xyb, format="xyb", close=True,
                       dxfattribs={"layer": layer})

# ---------- main ----------

def main():
    Tk().withdraw()
    path = filedialog.askopenfilename(
        title="Wybierz plik .nc1 (DSTV)",
        filetypes=[("DSTV NC1","*.nc1 *.nc *.dstv"), ("Wszystkie pliki","*.*")]
    )
    if not path:
        print("❌ Nie wybrano pliku.")
        return

    txt = Path(path).read_text(encoding="utf-8", errors="replace")

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
                # SLOT z wektorem: wymagaj X,Y,Ø,(coś),dx,dy => >=6 liczb
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
                # w razie innych wariantów BO można tu dopisać kolejne wzorce

    # Tworzenie DXF
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    if "OUTER" not in doc.layers:
        doc.layers.add("OUTER")
        doc.layers.add("cutout", color=4)  # ACI 4 = cyan
    else:
        doc.layers.get("cutout").dxf.color = 4

    # OUTER (AK)
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

    out = Path(path).with_name(Path(path).stem + "_OUTER_CUTS.dxf")
    doc.saveas(out)
    print(f"✅ Zapisano: {out}")

if __name__ == "__main__":
    main()
