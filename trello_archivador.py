#!/usr/bin/env python3
"""
trello_archivador.py — Archiva carpetas de trabajos cuando las tarjetas pasan
a la lista "Para Facturar" en Trello.

Flujo:
    1. Consulta Trello por las tarjetas en la lista "Para Facturar"
    2. Para cada tarjeta, busca la carpeta correspondiente en 1-DISEÑOS MAQUINA/
    3. Si hay UNA carpeta → la mueve a 1-DISEÑOS MAQUINA/Archivo/
    4. Si hay VARIAS con mismo número → LAS DEJA (archivo manual luego)
    5. Si no hay carpeta → notifica y salta

La carpeta "Archivo" se detecta case-insensitive (ARCHIVO/archivo/Archivo); si
no existe, se crea con la capitalización estándar 'Archivo'.

Uso:
    python3 trello_archivador.py                  # DRY-RUN, solo informa
    python3 trello_archivador.py --apply          # ejecuta los movimientos
    python3 trello_archivador.py --lista "Para Facturar" --apply
    python3 trello_archivador.py --base "/ruta/a/trabajos" --apply

Se recomienda ejecutar primero SIN --apply para revisar qué se movería.
"""

import argparse
import shutil
import sys
from pathlib import Path
from typing import Optional

# Importar helpers del cliente Trello existente
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR / "SistemaProduccion"))
from trello_client import cargar_config, _get, extraer_numero  # noqa: E402

BOARD_ID          = "62a382a99f14ff1369e0da58"   # Planificador de Trabajo
LISTA_DEFAULT     = "Para Facturar"
BASE_DEFAULT      = THIS_DIR / "1-DISEÑOS MAQUINA"
NOMBRE_ARCHIVO    = "Archivo"    # capitalización si hay que crearla


# ── Helpers ───────────────────────────────────────────────────────────────────

def buscar_lista_id(trello, nombre_target: str) -> Optional[str]:
    """Busca el ID de una lista por su nombre (case-insensitive)."""
    target = nombre_target.lower().strip()
    listas = _get(f"/boards/{BOARD_ID}/lists", trello.api_key, trello.token)
    for l in listas:
        if l["name"].lower().strip() == target:
            return l["id"]
    return None


def encontrar_o_crear_archivo(base: Path, dry_run: bool = False) -> Path:
    """
    Devuelve la carpeta 'Archivo' dentro de base (detección case-insensitive).
    Si no existe, la crea con la capitalización estándar 'Archivo'.
    """
    for item in base.iterdir():
        if item.is_dir() and item.name.lower() == NOMBRE_ARCHIVO.lower():
            return item
    # No existe → crear
    nueva = base / NOMBRE_ARCHIVO
    if not dry_run:
        nueva.mkdir(exist_ok=True)
    return nueva


def carpetas_con_numero(base: Path, numero: str, archivo_folder: Path) -> list[Path]:
    """
    Busca carpetas en base cuyo prefijo corresponda al número de medida dado.
    Excluye la propia carpeta Archivo y subcarpetas dentro de ella.
    """
    matches: list[Path] = []
    num_up = numero.upper()
    for item in base.iterdir():
        if not item.is_dir():
            continue
        # Excluir la propia carpeta de archivo y subcarpetas dentro
        try:
            if item == archivo_folder or archivo_folder in item.parents:
                continue
        except Exception:
            pass
        # Nombre empieza por el número (extraer_numero ignora underscores)
        extr = extraer_numero(item.name)
        if extr and extr.upper() == num_up:
            matches.append(item)
    return matches


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Archiva carpetas cuando sus tarjetas pasan a 'Para Facturar'")
    parser.add_argument("--lista", default=LISTA_DEFAULT,
                        help=f"Nombre de la lista de Trello (default: '{LISTA_DEFAULT}')")
    parser.add_argument("--base", default=str(BASE_DEFAULT),
                        help=f"Carpeta base donde están las carpetas de trabajo (default: {BASE_DEFAULT})")
    parser.add_argument("--apply", action="store_true",
                        help="Ejecuta los movimientos. Sin esta flag, solo informa (dry-run).")
    parser.add_argument("--quiet", action="store_true",
                        help="Menos output (solo lo esencial).")
    args = parser.parse_args()

    base = Path(args.base)
    if not base.exists():
        print(f"✗ No existe carpeta base: {base}"); return 1

    trello = cargar_config()
    list_id = buscar_lista_id(trello, args.lista)
    if not list_id:
        print(f"✗ No se encontró lista '{args.lista}' en el tablero"); return 1

    cards = _get(f"/lists/{list_id}/cards", trello.api_key, trello.token,
                 {"fields": "id,name", "limit": "1000"})

    print(f"{'═'*62}")
    print(f"  TRELLO ARCHIVADOR — {args.lista}")
    print(f"{'═'*62}")
    print(f"  Base        : {base}")
    print(f"  Modo        : {'APLICAR (movimientos reales)' if args.apply else 'DRY-RUN (solo informa)'}")
    print(f"  Cards en lista: {len(cards)}")

    archivo = encontrar_o_crear_archivo(base, dry_run=not args.apply)
    print(f"  Carpeta archivo: {archivo.name}/  {'(existente)' if archivo.exists() else '(CREADA)' if args.apply else '(SERÁ CREADA)'}")
    print()

    a_archivar: list[tuple[dict, Path]] = []     # (card, folder)
    con_duplicados: list[tuple[dict, list[Path]]] = []
    sin_carpeta: list[dict] = []
    sin_numero: list[dict] = []

    for card in cards:
        numero = extraer_numero(card["name"])
        if not numero:
            sin_numero.append(card); continue
        carpetas = carpetas_con_numero(base, numero, archivo)
        if not carpetas:
            sin_carpeta.append(card)
        elif len(carpetas) == 1:
            a_archivar.append((card, carpetas[0]))
        else:
            con_duplicados.append((card, carpetas))

    # Resumen
    if a_archivar:
        print(f"→ A archivar ({len(a_archivar)}):")
        for card, folder in a_archivar:
            print(f"    {folder.name}")
        print()

    if con_duplicados:
        print(f"⚠ DUPLICADOS — NO se archivan automáticamente ({len(con_duplicados)}):")
        for card, folders in con_duplicados:
            print(f"    Card: {card['name'][:70]}")
            for f in folders:
                print(f"      - {f.name}")
        print(f"  (Archívalas a mano cuando decidas cuál conservar)")
        print()

    if sin_carpeta and not args.quiet:
        print(f"ℹ Cards sin carpeta asociada ({len(sin_carpeta)}):")
        for c in sin_carpeta[:10]:
            print(f"    {c['name'][:80]}")
        if len(sin_carpeta) > 10:
            print(f"    ... y {len(sin_carpeta)-10} más")
        print()

    if sin_numero and not args.quiet:
        print(f"ℹ Cards sin número extraíble del nombre ({len(sin_numero)}):")
        for c in sin_numero[:5]:
            print(f"    {c['name'][:80]}")
        print()

    if not args.apply:
        print(f"{'─'*62}")
        print(f"  DRY-RUN: no se movió nada. Usa --apply para ejecutar.")
        print(f"{'═'*62}")
        return 0

    # Aplicar movimientos
    print(f"{'─'*62}")
    print(f"  EJECUTANDO {len(a_archivar)} MOVIMIENTOS")
    print(f"{'─'*62}")
    done = 0
    for card, folder in a_archivar:
        dest = archivo / folder.name
        if dest.exists():
            print(f"  ⚠ {folder.name}: ya existe en {archivo.name}/, skipping")
            continue
        try:
            shutil.move(str(folder), str(dest))
            done += 1
            print(f"  ✓ {folder.name}")
        except Exception as e:
            print(f"  ✗ {folder.name}: {e}")

    print()
    print(f"{'═'*62}")
    print(f"  {done}/{len(a_archivar)} carpetas archivadas")
    if con_duplicados:
        print(f"  {len(con_duplicados)} cards con duplicados pendientes de archivar a mano")
    print(f"{'═'*62}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
