# Reglas del negocio — sintetizador de piezas

## 🗂 Metadatos top-level del JSON (desde libreta/nota)

La libreta impresa (`docs/libreta_completa_3_variantes_y_ejemplo.pdf`) estandariza
la cabecera de toda medición. Los campos top-level a rellenar en cada síntesis son:

| Campo | Ejemplo | Obligatorio |
|-------|---------|-------------|
| `numero` | "J0317" | ✓ |
| `referencia_cliente_final` | "18422" | si aparece |
| `cliente_final` | "Fernando García Pérez" | ✓ |
| `cliente_intermedio` | "Valmi-Vigo" | si aparece |
| `tlf_cliente_final` | "+34 666 123 456" | si aparece |
| `tlf_cliente_intermedio` | "+34 986 987 654" | si aparece |
| `direccion` | "Camiño do Eirado 9 — Belvedere (Vigo)" | ✓ |
| `fecha_medicion` | "19/04/2026" | si aparece |
| `tomo_medidas` | "KC" (iniciales) | si aparece |
| `material` | "Belvedere (granito)" | ✓ |
| `grosor_mm` | 20 | ✓ |
| `acabado_superficie` | "pulido" \| "apomazado" \| "abujardado" \| "flameado" \| "envejecido" \| "natural" | default "pulido" |
| `tipo_trabajo` | `["cocina_encimera", "cocina_isla"]` (array) | si la libreta tiene casillas marcadas |

**Compat legacy**: `cliente` sigue como alias de `cliente_final`.

---


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

## ⚠ Convenciones de pulido por tipo de pieza (REGLA CRÍTICA)

Hay DOS capas de reglas que funcionan en conjunto:

### (A) Marcadores explícitos de la nota — SIEMPRE se respetan

Cuando la nota marca una arista específica como pulida, **SIEMPRE aplica** el
pulido en esa arista, independientemente del tipo de pieza (encimera, rodapié,
copete, chapeado, etc.). Los marcadores posibles son:

| Marcador en la nota | Significado |
|---------------------|-------------|
| **X sobre una línea** | Esa arista del rectángulo va pulida |
| **CI** | Cabeza Izquierda pulida |
| **CD** | Cabeza Derecha pulida |
| **CP** | Cabeza Pulida (identificar cuál por contexto/posición en la nota). **Aplica solo a UNA cabeza, NO al largo.** |
| **LP** | Largo Pulido (suele referirse al largo superior, fondo) |
| **X pequeña + número** junto a arista | Arista pulida parcialmente con `extension_mm` indicada |

Estos marcadores SIEMPRE ganan. No importa si la pieza es rodapié o encimera.

### (B) Defaults por tipo cuando la nota NO marca nada

Si la nota NO menciona ni marca nada sobre el pulido de una pieza, aplican estos
defaults:

| Tipo pieza | `fondo` (largo sup.) | `frente` (largo inf.) | `cabeza_izq` / `cabeza_der` |
|------------|----------------------|------------------------|------------------------------|
| **copete**  | **SÍ pulido** (convención taller) | NO | NO |
| **rodapié** | NO | NO | NO |
| **zócalo**  | NO | NO | NO |
| **chapeado / frontal** | NO | NO | NO |
| **encimera** (pegada a pared) | NO (fondo = pared) | SÍ (frente visible de la cocina) | NO |
| **isla** (sin pared) | SÍ (perímetro visible) | SÍ | SÍ |
| **costado / cascada** | SÍ | — | SÍ |

### Errores frecuentes a NO repetir

- ❌ Poner `fondo=pulido` a TODOS los rodapiés "por si acaso" — incorrecto si la
  nota no marca "LP" en ese rodapié.
- ❌ **Ignorar un marcador "CP" o "CI/CD" en un rodapié** porque "los rodapiés no
  se pulen" — incorrecto. La capa (A) gana sobre la (B). Si la nota marca CP,
  **esa cabeza va pulida**, aunque sea rodapié.
- ❌ Interpretar "CP" como "largo pulido también" — NO. "CP" solo marca UNA cabeza.
- ❌ Confundir copete y rodapié: **copete** va arriba en la pared (largo superior
  se pule por default); **rodapié** va abajo al suelo (no se pule nada por
  default — solo lo que marque la nota).

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

## Recercados de ventanas/puertas (G, D, AP)

Abreviaturas de la nota manuscrita para piezas que forman un **recercado** de
ventana o puerta:

| Abreviatura | Nombre | Qué es |
|-------------|--------|--------|
| **G** | Gama | Pieza LATERAL del recercado (vertical, en los lados de la abertura). Suelen ir 2 (izquierda y derecha). |
| **D** | Dintel | Pieza SUPERIOR del recercado (horizontal, arriba de la abertura). Normalmente 1 sola. |
| **AP** | Antepecho | Pieza INFERIOR del recercado (horizontal, abajo de la abertura — sólo en ventanas, no en puertas). Normalmente 1 sola. |

Cada pieza de recercado es un rectángulo plano. En el schema usa `tipo`:
  - `gama`
  - `dintel`
  - `antepecho`

El sintetizador debe tratarlas como piezas tipo "chapeado" para el dibujo
(largo × alto con acabados por arista).

### Convención de cantidad (95% de los casos)

- **Gamas**: aunque la nota solo dé UNA medida de gama, **emite 2 piezas iguales**.
  - Son simétricas (una a la izquierda, otra a la derecha de la abertura).
  - Mismos largo/alto.
  - El pulido suele ir en la arista "interior" — una frente a la otra. Si la nota
    no marca de qué lado, emítelo en `cabeza_der` de la gama izquierda y en
    `cabeza_izq` de la gama derecha (se enfrentan al montar).
  - Si la nota da 2 medidas distintas, emítelas tal cual (no todas las ventanas
    son simétricas).
- **Dintel**: 1 sola pieza.
- **Antepecho**: 1 sola pieza si es ventana; 0 si es puerta.

### Convención de pulido en recercados (por defecto)

Los **largos (frente y fondo)** de TODAS las piezas de recercado van pulidos por
defecto (son las caras visibles en obra).

- **Gama**: `frente=pulido` + `fondo=pulido` + UNA cabeza pulida (la interior).
- **Dintel** y **antepecho**: `frente=pulido` + `fondo=pulido`. Las **cabezas
  NO se pulen**. Además, los largos tienen **descuento en los extremos**
  equivalente al grosor del material (= 2cm si material 20mm, = 3cm si 30mm):
  esa zona queda cubierta por la gama que apoya/ensambla ahí y no se pule.

El código DXF aplica automáticamente ese descuento (`descuento_ini_mm =
grosor_mm` y `descuento_fin_mm = grosor_mm`) en los largos del dintel/antepecho
cuando emites `tipo: "pulido"`. No hace falta que Claude lo calcule — solo
que emita la arista como pulida; el código se encarga de acortar el tramo.

### Ejemplo

Nota dice: "G 1450×180, D 1200×180, AP 1200×180".

Emite 4 piezas:
- gama izq: 1450×180, cabeza_der pulida (arista interior)
- gama der: 1450×180, cabeza_izq pulida (arista interior)
- dintel:   1200×180, frente pulido (cara visible hacia la abertura)
- antepecho: 1200×180, frente pulido

## Grifo automático detrás de fregadero bajo encimera

Si una pieza tiene un fregadero **bajo encimera** y la nota NO menciona un hueco
de grifo, el código añade automáticamente un grifo con estas especificaciones:

- Ø 35mm (radio 17.5) en la capa `1006` (taladros)
- **Centrado horizontalmente** respecto al hueco del fregadero
- **50mm detrás** del fregadero: distancia desde el **borde posterior del hueco
  del fregadero** hasta el **centro del grifo**

El auto-grifo queda anotado en `_defaults_aplicados` con el aviso
"grifo auto-añadido a X mm del fregadero — confirmar en obra". Si la nota sí
marca un grifo explícito (con medidas propias), se respeta el de la nota y
NO se añade el automático.

## ⚠ Semántica de distancias de huecos (convención plano cocina)

- `distancia_frente_mm`: del **frente de la pieza** al **borde más cercano** del hueco.
  (Así aparece en los planos: "a X mm del frente" significa desde el borde frente
  de la encimera hasta donde EMPIEZA el hueco.)
- `distancia_lado_mm`: diferente según el tipo de hueco:
  * **Placa / fregadero**: del lado de la pieza al **CENTRO** del hueco
    (convención plano cocina: "la placa a 450mm de la cabeza izq" = centro a 450mm)
  * **Enchufe / grifo / doble-enchufe**: del lado de la pieza al **BORDE** del
    taladro más cercano (del grupo de taladros si es doble/triple).
- `cantidad`: para enchufe/grifo, número de taladros consecutivos (default 1).
  Un "enchufe doble" → cantidad=2 (dos taladros Ø70mm tangentes); "triple" → 3.
- `separacion_mm`: distancia BORDE-BORDE entre taladros consecutivos del grupo.
  **Default 0** — los taladros se tocan tangencialmente (el final de uno es el
  inicio del siguiente). Solo rellenar si la nota indica una separación mayor.
- `radio_esquina_mm`: radio de redondeo en las 4 esquinas del hueco.
  - Si **≥ 20mm** (típico fregadero 50-60mm): las esquinas se dibujan con arcos
    en capa `0-CON` (fresado automático por la máquina).
  - Si **< 20mm** (típico placa 5-10mm): el DXF se dibuja con **esquinas rectas**
    (rectángulo plano, sin arcos) pero el código añade un TEXT "R{n}" en cada
    esquina (capa DEFPOINTS, no mecaniza) y el PDF muestra "esquinas R{n}" en
    la lista de avisos. El operario redondea a mano con amoladora tras el corte.

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
