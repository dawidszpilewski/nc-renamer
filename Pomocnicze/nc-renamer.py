#!/usr/bin/env python3
import re
import sys
from pathlib import Path
from tkinter import Tk, filedialog

# ——— Ustawienia ——————————————————————————————————————
TARGET_EXT = ".nc1"   # docelowe rozszerzenie
RECURSIVE = False     # True → skanuj podfoldery

# ——— Util —————————————————————————————————————————————
def sanitize(text: str) -> str:
    if not text:
        return "NA"
    # zachowujemy nawiasy okrągłe; usuwamy znaki niedozwolone
    return re.sub(r'[\\/:*?"<>|\r\n]+', "_", text.strip())

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

# ——— Parsowanie nagłówka DSTV/NC1 ——————————————————
def parse_header_fields(lines):
    """
    Zwraca (piece_mark, assembly_mark, grade, qty, profile, type_code, idx_B)
    Zakładamy układ typowy dla blach (typ 6):
    ST
    ** (opcjonalny komentarz)
    <ID>
    <TYPE>      ← 6 = płyta
    <PIECE>     ← nazwa (bierzemy tę linię)
    <ASSEMBLY>
    <GRADE>
    <QTY>
    <PROFILE>   ← np. BL20
    B
    <...>
    """
    # znajdź ST
    try:
        st_idx = next(i for i, ln in enumerate(lines) if ln.strip().upper() == "ST")
    except StopIteration:
        st_idx = -1

    seq = []
    # zbierz do 30 linii po ST, pomijając puste i komentarze ** (tu nie bierzemy nazwy z **)
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
    """
    Zwraca grubość jako string z pola nr 3 bloku B (dla typu 6 – blacha).
    B
      1: X-length
      2: Y-length
      3: thickness (S)
    """
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
    # Fallback – poszukaj typowego wzorca na początku pliku
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

    # Nazwa: piece mark (pierwsza linia identyfikatora)
    name = piece if piece else fallback_stem

    # Grubość: pole 3 z bloku B
    thickness = parse_thickness_from_B(lines, b_idx)

    # Gatunek / ilość
    grade = pick_grade_simple(grade_raw, lines)
    qty = pick_qty_simple(qty_raw)

    # Sanitizacja
    name = sanitize(name)
    grade = sanitize(grade)
    thickness = sanitize(thickness if thickness else "NA")

    return name, thickness, grade, qty

# ——— Program główny ————————————————————————————————
def main():
    # wybór folderu
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
        return

    renamed = 0
    for p in candidates:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"⚠️  {p.name}: błąd odczytu ({e})")
            continue

        name, thickness, grade, qty = parse_nc1(text, fallback_stem=p.stem)

        # WZORZEC NA STAŁE: {grade}-{thickness}-({name})-{qty}.nc1
        new_stem = f"{grade}-{thickness}-({name})-{qty}"
        new_name = sanitize(new_stem) + TARGET_EXT
        target = p.with_name(new_name)

        if target.name == p.name:
            print(f"=  {p.name} (już poprawna)")
            continue

        try:
            # NADPISZ jeśli istnieje
            if target.exists() and target != p:
                target.unlink()
            p.rename(target)
            print(f"✅ {p.name}  ->  {target.name}")
            renamed += 1
        except Exception as e:
            print(f"❌ {p.name}: błąd zmiany nazwy ({e})")

    print(f"\nGotowe. Zmieniono {renamed} plików.")

if __name__ == "__main__":
    main()
    input("\nNaciśnij Enter, aby zamknąć...")
