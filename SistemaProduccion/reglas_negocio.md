# Reglas del negocio — sintetizador de piezas

Este archivo se inyecta automáticamente en el system prompt del sintetizador cada
vez que se llama a `/sintetizar` o `/refinar`. Edita libremente en lenguaje natural.
Cada regla nueva se aplica en la siguiente llamada a Claude — no hace falta reiniciar.

El archivo lo versiona git. Cuando añadas una regla nueva, el commit deja trazabilidad
de cuándo y por qué.

---

## Contornos y forma de pieza

- **"Si van separadas se dibujan separadas."** Una pieza = un contorno cerrado
  continuo en la nota. Varias piezas = varios contornos dibujados por separado.
- Escuadras internas, marcas de ángulo, diagonales o cualquier señal interior NO
  dividen una pieza en varias. Esas marcas indican uniones con piezas adyacentes
  (que están dibujadas aparte), pilares o referencias de montaje.
- `forma = "L"` o `"U"` solo si el contorno EXTERIOR dibujado describe realmente
  esa forma (cambio de dirección >90° a lo largo del perímetro). Contorno
  rectangular con marcas interiores → `forma = "rectangular"`.

## Altura de copete por defecto

Si un **copete** no tiene altura especificada en la nota (ni alto_mm ni texto
"N cm de alto" cerca de él), usa **alto_mm = 50** (5cm) — es la altura estándar
del taller. El código dibuja ese default y lo reporta en el PDF como
"MEDIDA ESTÁNDAR: alto copete 50mm — confirmar en obra".

Esta convención SOLO aplica a copetes. Rodapiés, zócalos, chapeados y demás tiras
requieren la altura explícita de la nota; si falta, `alto_mm = null` + "FALTA".

## Convención "largo pulido" (copetes, rodapiés, zócalos, chapeados, tiras)

Cuando la nota dice **"largo pulido"** o **"LP"** junto a una pieza tipo tira (copete,
rodapié, zócalo, chapeado, frontal), significa que **el LARGO SUPERIOR va pulido**
(`acabados_aristas.fondo.tipo = "pulido"`).

**Por defecto**: los copetes SIEMPRE llevan "largo pulido" — emite el pulido del
fondo aunque la nota no lo indique explícitamente (es la convención del taller).
Lo mismo aplica por defecto a rodapiés SOLO si la nota los marca "LP" (no hay
convención universal para rodapiés).

**Las cabezas** (cabeza_izq, cabeza_der) NO se pulen por defecto en copetes/rodapiés.
Se pulen SOLO cuando:
- La nota marca una **"X"** sobre la arista de cabeza, o
- Escribe explícitamente "CI" (cabeza izq pulida) / "CD" (cabeza der pulida), o
- Dice "cabeza pulida" explícito.

**El largo inferior (frente) normalmente NO se pule** en copetes/rodapiés. Solo
si hay una X dibujada en el largo inferior.

**En chapeados/frontales** esta convención NO aplica por defecto — respeta solo
lo que marque la nota explícitamente con X o texto.

## Acabados de aristas

- **Inglete** por defecto = **45.5°** (no 45°, por holgura de montaje). Si la
  anotación no dice ángulo pero sí "inglete/ingletes", usa 45.5.
- **Bisel**: solo si se menciona explícitamente. Ángulo y profundidad_mm variables
  según el trabajo.
- **Pulido**: post-proceso manual (canteadora). Sin ángulo ni profundidad.
  - La **X** sobre una línea marca esa arista como pulida.
  - `|X` + número pequeño (25-30mm) = vuelo pulido (sobresale del frente del mueble).
- Aristas de una pieza: `frente` (lado visible inferior), `fondo` (pegado a pared),
  `cabeza_izq`, `cabeza_der`.

## Producción — defaults controlados para huecos

- **Esto sigue siendo producción**. Si la **pieza principal** (encimera, chapeado,
  rodapié, etc.) no tiene largo/ancho/alto, `null` y "FALTA: {qué}". NO inventes
  dimensiones de piezas.
- Sin embargo, para los **huecos** se aplican estos defaults **documentados** (el
  código `dxf_produccion.py` los aplica al dibujar y los marca en el PDF con un
  aviso "MEDIDA ESTÁNDAR — falta confirmar"):

| Hueco | Campo faltante | Default aplicado | Aviso en PDF |
|-------|----------------|-------------------|---------------|
| Placa | `distancia_frente_mm` | **70mm** | Sí |
| Placa | `largo_mm` + `ancho_mm` | **562 × 492** | Sí |
| Fregadero **bajo encimera** | `distancia_frente_mm` | **100mm** | Sí |
| Fregadero **sobre encimera** | `distancia_frente_mm` | **80mm** | Sí |
| Fregadero (cualquiera) | `largo_mm` + `ancho_mm` | **NO se dibuja**, se añade texto "FREGADERO — FALTAN MEDIDAS" en la posición esperada | Sí |

- **Cómo escribir el JSON**: cuando el dato NO aparece en la nota, deja `null` en el
  campo del hueco. NO inventes el valor en el JSON. El código aplicará el default en
  el momento de dibujar y lo dejará anotado para el PDF.
- Para dimensiones de la pieza principal (encimera fondo, chapeado alto, etc.) NO
  hay defaults — siguen siendo obligatorias o "FALTA".

## Convenciones de la nota

- Dimensiones en mm a menos que el contexto diga lo contrario.
- `"B/E"` o `"bajoencimera"` → `subtipo="bajo_encimera"`.
- `"SE"` o `"sobre"` → `subtipo="sobre_encimera"`.
- `"568-"` (guión al final) → `tiene_guion=true`. El código restará grosor+2mm al
  dibujar. Si el grosor es conocido (ver abajo), puedes YA emitir el valor final
  en el JSON (ej: granito 20mm, 568- → emite 546). Si no sabes el grosor, emite
  el valor crudo (568) y deja `tiene_guion=true`.
- Flecha `→N` indica medida en esa dirección.
- Una pieza **tachada** en la nota se incluye en la respuesta para trazabilidad
  pero con nota "NO FABRICAR" — el operario decide si la elimina.

## ⚠ Descuadros — signo crítico

En la nota, un descuadro es un número pequeño junto a la esquina superior (pared)
que indica cuánto se desvía de 90° esa esquina respecto al frente.

**Convención de signo del sistema**:
- Si el valor es **positivo** (ej: "+5" o "5") → el fondo en ese lado es **MÁS LARGO**
  que el frente. La pared se aleja hacia afuera en esa esquina.
- Si es **negativo** (ej: "−5" o "5-") → el fondo en ese lado es **MÁS CORTO** que el
  frente. La pared cierra hacia dentro.

**Regla de validación obligatoria**: `largo_fondo = largo_mm + descuadro_izq_mm +
descuadro_der_mm`. Si la nota da frente Y fondo, comprueba que los descuadros cuadren.

**Ejemplo T4070 encimera**: frente 2210, fondo 2205 → cabeza der 5mm más corta arriba
→ `descuadro_der_mm: -5`. **NO** `+5`.

## ⚠ Semántica de distancias de huecos (convención plano cocina)

- `distancia_frente_mm`: del **frente de la pieza** al **borde más cercano** del hueco.
  (Así aparece en los planos: "a X mm del frente" significa desde el borde frente
  de la encimera hasta donde EMPIEZA el hueco.)
- `distancia_lado_mm`: del **lado** (izq o der, según `posicion`) al **CENTRO** del
  hueco. Convención estándar en planos de cocina: "la placa a 450mm de la cabeza
  izq" = el CENTRO de la placa queda a 450mm desde la cabeza izq.
- `radio_esquina_mm`: radio de redondeo en las 4 esquinas del hueco (para fregaderos
  suele ser 50-60mm; para placas 5-10mm). Si > 0, las esquinas se dibujan con arcos
  en capa `0-CON` (fresado).

## ⚠ Huecos múltiples en la misma pieza — posiciones distintas obligatorias

Si una pieza (ej. encimera) tiene **varios huecos** (placa + fregadero + enchufes),
cada uno DEBE tener su propia posición explícita: `posicion` + `distancia_lado_mm`
si es izq/der. NO dejes ambos con `posicion: null` — el código defaultea a "centro"
y se superponen.

Ejemplo: placa a la izquierda, fregadero a la derecha:
```
"huecos": [
  {"tipo": "placa",     "posicion": "izquierda", "distancia_lado_mm": 150, ...},
  {"tipo": "fregadero", "posicion": "derecha",   "distancia_lado_mm": 150, ...}
]
```

## ⚠ Pulido parcial en una arista (solo una porción)

Si la nota indica que solo una PORCIÓN de una arista va pulida (ej: "cabeza izq
pulida 30mm" significa que solo los primeros 30mm desde el frente están pulidos,
no toda la cabeza), añade los campos opcionales al acabado:

```
"acabados_aristas": {
  "cabeza_izq": {
    "tipo": "pulido",
    "extension_mm": 30,     // longitud del tramo pulido
    "desde": "frente"        // desde dónde comienza: "frente"|"fondo"|"cabeza_izq"|"cabeza_der"
  }
}
```

Si el tramo pulido abarca toda la arista, omite `extension_mm` y `desde` (o déjalos
null). El código dibuja el marcador 1007 solo en la porción indicada.

## ⚠ Grosor del material vs altura de pieza (crítico)

**El grosor del material** (granito 20mm, Dekton 12mm, Silestone 20mm, Neolith
30mm, etc.) es un dato GLOBAL del pedido, NO de cada pieza. Se emite UNA vez en:

```
{ "grosor_mm": 20, ... }
```

en el top-level del JSON (junto a cliente, material, numero). Claude debe
detectarlo en la nota y emitirlo allí.

**NUNCA metas el grosor en `alto_mm` o `ancho_mm` de las piezas**. Esos son los
dimensiones visibles de la pieza en la nota.

### Qué significa cada campo por tipo de pieza

| Tipo | `largo_mm` | `ancho_mm` | `alto_mm` |
|------|------------|------------|-----------|
| encimera / isla / cascada | largo de la encimera | **fondo** (profundidad pared-frente) | null (grosor va en grosor_mm global) |
| chapeado / frontal / pilastra | largo horizontal | null | **altura vertical** visible de la pieza |
| costado (cascada lateral de isla) | altura visible que se ve de lado | **fondo** (coincide con encimera) | null |
| copete | largo horizontal | null | **altura** visible (típico 50mm) |
| rodapié / zócalo | largo horizontal | null | **altura** visible (típico 95-100mm) |
| paso / tabica | largo | null | **altura** del escalón |

**Regla práctica**: si ves "20mm" en la nota y es el grosor del material, va a
`grosor_mm` global. NUNCA a `alto_mm` ni `ancho_mm` de rodapiés/chapeados/copetes.

**Caso costado**: un costado es una cascada lateral de isla. `largo_mm` es la
altura visible (lo que ves de frente), `ancho_mm` es el fondo (para que case con
la encimera). Si no tienes una de las dos medidas, déjala `null` + FALTA.

## Materiales típicos

- Porcelánico (Dekton, Coverlam, Neolith, Laminam, Ceratop, Lapitec): fregadero
  va SOBRE encimera por defecto; pilares llevan ingletes en esquinas vistas.
- Cuarzo (Silestone, Compac): igual que granito para fregadero/nesting.
- Todos los "Familía Guidoni" son granito de importación.

## Capas CAM (para el DXF generado)

- Layer `0` → cortes normales con disco.
- Layer `0-CON` → fresado (huecos con curvas grandes, r>20mm).
- Layer `1006` → taladros (enchufe/grifo), CIRCLE con Ø fijo por herramienta.
- Layer `1000INC{ang}` → corte inclinado del disco (ingletes y biseles).
- Layer `1007` → guía visual (pulido, no mecaniza).

Estas son referencias para el código que genera el DXF; el sintetizador no
necesita emitirlas, solo saber que existen.

---

<!-- REGLAS NUEVAS SE AÑADEN AL FINAL -->
