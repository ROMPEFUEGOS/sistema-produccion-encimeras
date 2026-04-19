# Briefing — Diseño de libreta para medidas de trabajos en piedra (marmolería)

**Destinatario**: otra IA (Claude.ai, GPT, etc.) encargada de **diseñar las plantillas
de libreta impresa** que sustituirán a las notas manuscritas libres actuales.

**Objetivo**: que la información capturada en el taller/obra sea **sistemática**
(cabecera, observaciones, medidas) para minimizar errores de interpretación
posterior, aunque los dibujos de las piezas sigan siendo **a mano alzada** por la
variedad de formas.

**Alcance**: **libreta ÚNICA para todos los trabajos** de la marmolería (no una
por tipo). La libreta debe tener un campo "tipo de trabajo" en la cabecera y
sub-secciones que el operario usa según corresponda. El **80-90% de los trabajos
son encimeras de cocina** — el diseño debe optimizarse para ese caso, con
flexibilidad para el resto (baño, lápidas, escaleras, revestimientos, etc.).

---

## 1. Contexto del negocio

- **Empresa**: **marmolería** en Galicia (España). Dos marcas: **Cocimoble** y **ACyC
  Accesorios y Cocinas**. Fabricación, mecanizado e instalación de piezas en piedra
  natural y superficies técnicas.
- **Línea principal**: encimeras de cocina (≈80-90% del volumen). Dos o tres decenas
  al mes.
- **Otras líneas habituales** (agrupadas por frecuencia):
  - **Baños**: encimeras de lavabo (tocadores), platos de ducha, revestimientos.
  - **Recercados**: ventanas y puertas (gamas + dintel + antepecho).
  - **Escaleras**: huellas, contrahuellas, rodapiés escalonados, peldaños macizos.
  - **Revestimientos**: frontales de chimenea, paredes, fachadas.
  - **Lápidas y elementos funerarios**: losa, base, floreros, inscripciones.
  - **Mesas y encimeras sueltas**: sobremesas, bancos, encimeras de bar.
  - **Piezas especiales**: fuentes, bancos de jardín, jardineras, alféizares.
- **Materiales habituales**: granito (20/30mm), porcelánico Dekton/Coverlam/Neolith
  (12/20/30mm), cuarzo Silestone/Compac (20mm), Sogestone, Laminam, mármoles, calizas.
- **Acabados de superficie posibles**: pulido, apomazado, abujardado, flameado,
  envejecido, natural, grabado.
- **Piezas típicas por trabajo**: de 1 (una lápida) a 25+ (cocina grande con isla).

### El problema a resolver

Actualmente las medidas se toman en notas manuscritas libres sobre papel cuadriculado.
Esas notas:
- Tienen símbolos y convenciones del taller muy cargados de contexto
- Contienen errores menores (medidas corregidas encima), tachaduras, añadidos
- Mezclan información (nombre cliente, material, medidas, dibujos, aparatos) en
  posiciones libres de la hoja
- Son difíciles de digitalizar de forma consistente

**El objetivo de la libreta** es:
- **Estandarizar la cabecera** (datos del pedido, cliente, material)
- **Estandarizar el formato de símbolos y convenciones** (con leyenda impresa)
- **Mejorar el sustrato visual** (fondo blanco plano, no cuadriculado — mejor contraste
  con boli negro para la digitalización)
- **Mantener los dibujos libres** de las piezas (el geometría variable lo exige)
- **Seccionar** las observaciones para que queden referidas a piezas concretas

---

## 2. Información de cabecera (obligatoria en cada hoja)

Debe ir en la parte superior de la hoja, en campos estructurados fáciles de rellenar.
Formato del **nombre de archivo final** que estos datos componen (separadores reales
del uso actual):

```
{Número de Medida}_{Referencia Cliente Final}_{Nombre Cliente Final}_
{Nombre Cliente Intermedio}_{Dirección-Ciudad}_{Tipo de trabajo}-
{Material} {Espesor}
```

**Campos individuales**:

| Campo | Ejemplo | Formato |
|-------|---------|---------|
| Número de Medida | `V0275`, `J0245`, `T7060`, `F170`, `P182` | Letra+dígitos. Prefijos tienen significado: V=estándar, T=taller/reposición, J=Cocimoble, F=factura ACyC, P=proyecto, A=obra especial |
| Referencia Cliente Final | `17815` | Suele ser numérico (pedido externo) |
| Nombre Cliente Final | `Fernando García` | Texto libre |
| Nombre Cliente Intermedio | `Valmi-Vigo`, `Lina-Ceramix`, `Anantia Mobel` | Texto libre (distribuidor/mueblero) |
| Dirección-Ciudad | `Camiño do Eirado 9 – Belvedere`, `Rúa del Sol 12 – Baiona` | Texto libre |
| Tipo de trabajo | ver abajo | Selector/casillas |
| Material | `Belvedere`, `Baroco Extrem Vintage`, `Mondariz`, `Silvestre`, `Dekton Entzo` | Texto libre |
| Espesor | `20`, `12`, `30` | mm |
| **Fecha de medición** | `2026-04-19` | dd/mm/aaaa o aaaa-mm-dd |
| **Tomó medidas** | iniciales del operario | 2-3 letras |
| **Teléfono cliente final** | `+34 600 123 456` | opcional |
| **Teléfono cliente intermedio** | `+34 986 987 654` | opcional |
| **Observaciones generales de la obra** | texto libre corto | p.ej. "Obra cerrada por vacaciones hasta agosto" |

**Valores del selector "Tipo de trabajo"** (casillas / checkboxes, puede marcarse
más de una si el trabajo combina):

- `Cocina — encimera`
- `Cocina — encimera + chapeado`
- `Cocina — isla`
- `Cocina — reposición / taller`
- `Baño — encimera / tocador`
- `Baño — plato de ducha`
- `Baño — revestimiento`
- `Recercado — ventana`
- `Recercado — puerta`
- `Escalera — peldaños (huella + contrahuella)`
- `Escalera — rodapié escalonado`
- `Revestimiento — fachada / pared / chimenea`
- `Lápida — conjunto funerario`
- `Mesa / sobremesa / banco`
- `Pieza especial` (campo texto libre al lado)

El diseño del resto de la hoja se adapta según lo marcado; pero la cabecera y el
área de croquis son comunes.

---

## 3. Tipos de pieza (vocabulario del taller)

La libreta debe incluir una **leyenda impresa** con los tipos de pieza y su
significado, tanto para consistencia al dibujar como para la digitalización
posterior. Se agrupan por línea de trabajo.

### Cocinas (el grueso del volumen)

| Tipo | Qué es |
|------|--------|
| `encimera` | Superficie horizontal sobre muebles bajos. Fondo típico 600-650mm. |
| `isla` | Encimera central sin apoyo en pared (se pule perimetralmente). |
| `cascada` | Costado vertical de una isla que "cae" hasta el suelo. |
| `costado` | Panel vertical lateral (similar cascada, contexto diferente). |
| `chapeado` / `frontal` | Panel vertical entre encimera y muebles altos. Suele llevar enchufes. |
| `copete` | Franja pegada a pared sobre la encimera. Altura típica 50mm. **Largo superior pulido por convención**. |
| `rodapié` | Franja a pie de muebles bajos. Altura típica 95-100mm. **No se pule por defecto**. |
| `zócalo` | Parecido a rodapié pero a otros niveles. Altura variable. |
| `pilastra` | Revestimiento de pilar. |

### Recercados (ventana / puerta)

| Tipo | Abreviatura | Qué es |
|------|-------------|--------|
| `gama` | **G** | Lateral del recercado. Por defecto **2 unidades simétricas**. |
| `dintel` | **D** | Pieza superior del recercado. 1 unidad. |
| `antepecho` | **AP** | Pieza inferior del recercado (solo ventanas, no puertas). 1 unidad. |

### Escaleras

| Tipo | Qué es |
|------|--------|
| `huella` | Parte horizontal del peldaño (donde se pisa). Largo × ancho. Suele llevar vuelo pulido en el canto anterior. |
| `contrahuella` | Parte vertical entre dos huellas. Largo × alto. |
| `peldaño_macizo` | Huella + contrahuella en una sola pieza (tallada). |
| `paso` / `tabica` | Sinónimo de escalón en plano de cocina/vivienda. |
| `rodapié_escalera` | Rodapié que sigue la diagonal de la escalera (pieza poligonal). |

### Baño

| Tipo | Qué es |
|------|--------|
| `encimera_lavabo` / `tocador` | Encimera de baño con huecos para lavabo(s). |
| `lavabo_sobrepuesto` | Si va tallado en la propia piedra. |
| `plato_ducha` | Pieza única con sumidero y pendiente. Suele requerir muesca para desagüe. |
| `revestimiento_baño` | Paneles verticales (alicatado de piedra). |

### Lápidas y elementos funerarios

| Tipo | Qué es |
|------|--------|
| `losa` | Pieza horizontal principal de la sepultura. |
| `base` / `pie` | Pieza inferior sobre la que apoya la losa. |
| `cabecera` / `estela` | Pieza vertical con la inscripción. |
| `florero` | Jarroneros/floreros tallados o ensamblados. |
| `marco_perimetral` | Marco rectangular alrededor de la sepultura. |
| `inscripción` | Texto grabado (va aparte en la sección "observaciones"). |

### Revestimientos y generales

| Tipo | Qué es |
|------|--------|
| `revestimiento` | Placa rectangular para pared/fachada. |
| `losa` / `baldosa` | Pieza de suelo (acabado típico mate o apomazado). |
| `alféizar` / `vierteaguas` | Pieza de remate de ventana exterior. |
| `mesa` / `sobremesa` | Pieza plana tipo tablero. |
| `banco` | Pieza maciza o compuesta. |
| `jardinera` / `fuente` / `especial` | Piezas ad-hoc. |

### Acabados de superficie (aparte de los acabados de arista)

Además del pulido de aristas, la pieza completa puede tener un acabado de superficie
global (campo aparte en la tabla de piezas):

- `pulido` (por defecto para cocinas/baños)
- `apomazado` (mate, habitual en bases de lápida y suelos)
- `abujardado` (rugoso, común en contrahuellas, exteriores, bancos)
- `flameado` (antideslizante, exteriores)
- `envejecido` / `natural` / `antikado`

Este campo se rellena UNA vez para toda la pieza (no por arista). Si el dorso va
con un acabado distinto del frente, se anota en observaciones.

### Complejidad geométrica

Las piezas pueden ser:
- **Rectangulares simples** (lo más común)
- **En L** (encimera que gira en esquina de cocina)
- **En U** (rara pero existe)
- **Con descuadro** (esquina no ortogonal: la pared no hace 90°, hay que compensar en el plano del corte)
- **Con chaflán** (esquina cortada a 45°)
- **Con esquina redondeada** (radio visible)
- **Trapezoidal** (lados no paralelos)
- **Con entrantes / muescas** (para columnas, pilares, tubos de bajante)

**Consecuencia**: los dibujos de las piezas NO pueden meterse en una forma rígida.
El formulario debe reservar un área generosa con fondo plano para croquis a mano alzada.

---

## 4. Convenciones de marcado dentro del dibujo

Estas abreviaturas y símbolos deben aparecer en la **leyenda impresa** en cada hoja
(para que el operario las vea siempre, aunque sepa ya el código):

### Acabados de aristas

| Símbolo | Significado |
|---------|-------------|
| **X** (sobre la línea) | Esa arista va pulida |
| **CP** | Cabeza Pulida (la cabeza señalada va pulida) |
| **CI** / **CD** | Cabeza Izquierda / Cabeza Derecha pulidas |
| **LP** | Largo Pulido (se pule el largo superior — convención) |
| `X30` junto a una arista | Pulido parcial de 30mm en esa zona |
| **Ing.** | Arista con inglete (por defecto 45.5° — holgura de montaje) |
| **Bisel** + ángulo + mm | Bisel con ángulo y profundidad específicos |

### Huecos

| Símbolo | Significado |
|---------|-------------|
| **B/E** o "bajoencimera" | Fregadero bajo encimera |
| **SE** o "sobre" | Fregadero sobre encimera |
| Círculo pequeño "E" | Enchufe Ø70mm |
| Número junto a enchufe `×2`, `×3` | Enchufe doble/triple (2/3 taladros tangentes) |
| Círculo etiquetado "G" | Grifo Ø35mm |
| Rectángulo con **"Freg"** o "Fregadero" | Fregadero (se miden largo × ancho) |
| Rectángulo con **"Placa"** o nombre del aparato | Placa de cocina (se miden largo × ancho) |

### Medidas especiales

| Símbolo | Significado |
|---------|-------------|
| `568-` (guión al final) | Se descuenta grosor material + 2mm al fabricar. Ej: material 20mm → real = 546 |
| `→ 2460` (flecha + número) | Distancia hasta el límite en esa dirección |
| `+3`, `-7` junto a esquina superior | Descuadro: desviación en mm respecto a 90°. Positivo = fondo más largo; negativo = fondo más corto |
| Número pequeño en esquina de fregadero | Radio de esquina en mm (ej. `R57` = esquinas redondeadas 57mm) |
| Línea en L (en rodapié) | Rodapié con entrante en L |

### Regla semántica crítica

- **"Si van separadas se dibujan separadas"**: una pieza = un contorno cerrado continuo
  en el dibujo. Varias piezas = varios contornos dibujados aparte.
- Escuadras internas, marcas de ángulo o diagonales dentro de un contorno NO dividen
  la pieza; señalan uniones con piezas adyacentes o pilares.

---

## 5. Medidas y dimensiones por tipo de pieza

El formulario debe tener una tabla donde se identifique cada pieza y sus medidas.
Campos necesarios **por pieza**:

### Cocinas / baños (rectangulares con fondo)

| Tipo | largo (mm) | ancho / fondo (mm) | alto (mm) | Obs |
|------|------------|--------------------|-----------|----|
| encimera / isla | ✓ | ✓ (fondo) | — | grosor común va en cabecera |
| encimera_lavabo | ✓ | ✓ (fondo) | — | huecos de lavabo van en sección huecos |
| chapeado / frontal | ✓ | — | ✓ (altura vertical) | nunca confundir alto con grosor |
| costado (cascada) | ✓ | ✓ (fondo, coincide con encimera) | — | |
| copete | ✓ | — | ✓ (típica 50) | largo sup. pulido siempre |
| rodapié / zócalo | ✓ | — | ✓ (típica 95-100) | no pulido por defecto |

### Recercados

| Tipo | largo (mm) | alto (mm) | Obs |
|------|------------|-----------|-----|
| gama (G) | ✓ | ✓ | 2 unidades por defecto, simétricas |
| dintel (D) / antepecho (AP) | ✓ | ✓ | pulido con descuento de grosor en extremos |

### Escaleras

| Tipo | largo (mm) | ancho (mm) | alto (mm) | Obs |
|------|------------|------------|-----------|----|
| huella | ✓ | ✓ (profundidad pisada) | — | canto anterior (vuelo) suele ir pulido, 20-30mm |
| contrahuella | ✓ | — | ✓ (diferencia de altura entre huellas) | |
| peldaño_macizo | ✓ | ✓ (profundidad) | ✓ (altura contrahuella integrada) | |
| rodapié_escalera | ✓ | — | ✓ | contorno poligonal diagonal, ver croquis |

### Baño especiales

| Tipo | largo (mm) | ancho (mm) | alto (mm) | Obs |
|------|------------|------------|-----------|----|
| plato_ducha | ✓ | ✓ | — | marcar posición sumidero + dirección pendiente |
| revestimiento_baño | ✓ | — | ✓ | grosor reducido habitual (10-15mm) |
| lavabo_sobrepuesto | ✓ | ✓ | ✓ | medidas del hueco superior del cuenco |

### Lápidas

| Tipo | largo | ancho | alto | Obs |
|------|-------|-------|------|-----|
| losa | ✓ | ✓ | — | inscripción va aparte |
| base / pie | ✓ | ✓ | ✓ | |
| cabecera / estela | ✓ | — | ✓ | suele ir con inscripción grabada |
| marco_perimetral | ✓ (perímetro o largo) | ✓ | ✓ | |
| florero | ✓ | ✓ | ✓ | hueco interior para flores |

### Revestimientos y otros

| Tipo | largo | ancho/profund. | alto | Obs |
|------|-------|----------------|------|-----|
| revestimiento / placa | ✓ | — | ✓ | |
| alféizar / vierteaguas | ✓ | ✓ (vuelo) | — | goterón en cara inferior si exterior |
| mesa / sobremesa | ✓ | ✓ | — | canto suele redondeado |
| banco | ✓ | ✓ | ✓ | |
| fuente / jardinera | variable | variable | variable | croquis detallado |

**NUNCA mezcles el grosor del material con alto_mm de una pieza**. El grosor va UNA
vez en la cabecera de la hoja. Las alturas de rodapiés/copetes son dimensiones reales
de esas piezas (95, 50, etc.), no 20mm (grosor).

---

## 6. Huecos — datos a capturar por cada uno

Para CADA hueco que aparezca en una encimera/chapeado debe tomarse:

- **Tipo**: placa / fregadero / grifo / enchufe / pasacables
- **Medidas del hueco**: largo × ancho (para placa/fregadero/pasacables). Para
  grifo/enchufe los diámetros son fijos (35mm grifo, 70mm enchufe) y no hace falta.
- **Subtipo fregadero**: B/E (bajoencimera) o SE (sobre encimera)
- **Posición**: `izquierda` / `centro` / `derecha`
- **distancia_lado_mm**: si la posición es izquierda o derecha:
  - Placa/fregadero: **al CENTRO** del hueco
  - Enchufe/grifo: **al BORDE** del taladro (o del grupo de taladros si es doble)
- **distancia_frente_mm**: desde el frente de la pieza al borde más cercano del hueco
- **radio_esquina_mm** (opcional, para fregaderos): los redondos del fregadero
  (típico 50-60mm en fregaderos de fábrica; 5-10mm se hace a mano en taller)
- **Cantidad** (enchufes): 1 / 2 / 3 (para enchufes múltiples tangentes)
- **Marca/modelo** (opcional): ej. "Teka Stylo 1C", "Balay 3EB865XR"

### Defaults del sistema para huecos (si faltan datos)

Si el formulario no tiene la medida, el sistema rellenará con estos valores Y
avisará en el PDF final que se aplicó un estándar:

- Placa sin medidas → **562×492**
- Placa sin distancia al frente → **70mm**
- Fregadero B/E sin distancia al frente → **100mm**
- Fregadero SE sin distancia al frente → **80mm**
- Fregadero sin medidas → NO se dibuja, se pone aviso
- Copete sin altura → **50mm**
- **Grifo auto**: si hay fregadero B/E sin grifo explícito, se añade uno Ø35mm
  centrado 50mm detrás del fregadero

Por tanto la libreta no tiene que forzar todos los campos; si algo falta el sistema
lo suple pero el operario debe conocer que serán "medidas estándar" en el PDF final.

---

## 7. Convenciones del negocio que afectan al formulario

### Recercados (ventanas/puertas)

Cada recercado son 3-4 piezas:
- **2 gamas** (laterales) — se duplican por defecto aunque la nota solo escriba una medida
- **1 dintel** (arriba)
- **1 antepecho** (abajo, solo en ventanas)

El formulario puede tener una sección "Recercado" con 4 subcampos (G, D, AP × 2 gamas).

### Grosor del material

Dato obligatorio único de cabecera. Valores habituales: 12, 20, 30 mm. Determina el
cálculo del guión (`-`) y el descuento en extremos de dintel/antepecho.

### Teléfonos

- Cliente final (uno)
- Cliente intermedio (uno, el distribuidor/mueblero)

### Fecha y operario

- Fecha de toma de medidas
- Iniciales/firma del operario

---

## 8. Observaciones

Sección importante. Las observaciones en notas libres suelen:
- Apuntar a medidas específicas ("el 450 de cabeza izq es al centro del hueco, no al borde")
- Explicar símbolos ("la X roja es para recordar que se pule a 30mm")
- Describir el montaje ("pared inclinada, verificar en obra")
- Indicar piezas que NO se fabrican (tachadas con "NO FABRICAR")

**Propuesta**: sección de observaciones con 2-3 renglones numerados, cada uno con
un campo para referenciar "pieza #N" y texto libre. Así el operario escribe
observación 1 → "pieza #3: cabeza izq pulida solo 30mm".

---

## 9. Constraints físicos del taller (para tenerlos en cuenta al diseñar leyenda)

No afectan a la estructura de campos pero sí al diseño visual y las notas de
"cosas a comprobar":

- Disco de corte: 3.5mm de ancho (kerf)
- Separación mínima interior en una L desde esquina: 50mm (no cortable más cerca)
- Broca de enchufe: 7cm (Ø70mm)
- Broca de grifo: 3.5cm (Ø35mm)
- Radio mínimo máquina: 20mm (debajo de eso, se redondea a mano con amoladora)
- Piezas de porcelánico: fregadero suele ir SOBRE encimera (SE) por defecto
- Materiales veteados: encimera y chapeado deben salir del MISMO tablero

---

## 10. Historial de errores frecuentes a evitar con la libreta

Estos son errores recurrentes con notas libres que la libreta debería minimizar:

1. Operario olvida apuntar el material o el grosor
2. Confunde "largo" con "alto" en una tira (ej. rodapié 1810 largo × 95 alto pero
   se escribe solo "1810" y queda ambiguo)
3. Distancia a borde o a centro del hueco (diferente convención por tipo — causa
   errores habituales)
4. Enchufe doble se confunde con uno solo
5. Rodapiés marcados con "CP" en cabeza se pulen a lo largo por error
6. Signo del descuadro (positivo/negativo) cambia dirección del corte
7. No distingue si un fregadero es B/E o SE
8. Pieza tachada no se marca explícitamente "NO fabricar"

La libreta impresa puede incorporar recordatorios visuales de estos puntos (iconos,
ejemplos de cómo marcar) para que el operario no los olvide.

---

## 11. Formato físico de la libreta

- **Tamaño**: A4 vertical u horizontal, a elección de quien diseñe.
- **Número de hojas por cocina**:
  - 1 hoja si cocina sencilla (≤5 piezas, sin descuadros complejos)
  - 2-3 hojas si cocina compleja (L, isla, recercado, muchos descuadros)
  - Hojas adicionales para "detalle de pieza" (zoom de una pieza con sus medidas)
- **Fondo**: blanco plano (mejor contraste con boli negro que cuadriculado). Puede
  tener algunas guías tenues muy claras (líneas de orientación) si ayuda al dibujar.
- **Tipo de impresión**: impresión láser/tinta negra, cabecera con líneas de casillas
  bien marcadas, resto de la hoja abierto para el croquis.
- **Encuadernación**: espiral A4 o cuaderno con hojas perforadas (para poder sacar
  la hoja, digitalizarla, archivarla).
- **Cantidad**: 50-100 hojas por libreta (una libreta dura varios meses).

---

## 12. Qué queremos que genere el diseñador

Pedimos **3 variantes** de diseño de hoja con enfoques distintos. Todas ellas son
**libreta única** (una sola plantilla imprimible sirve para cualquier tipo de
trabajo). Lo que cambia son las secciones activas según lo marcado en "Tipo de
trabajo" de la cabecera: el operario rellena solo lo relevante y deja el resto
en blanco.

1. **Variante "clásica"**: cabecera arriba + selector tipo de trabajo + tabla de
   piezas (filas numeradas con columnas tipo/largo/ancho/alto/acabado superficie/
   observaciones) + área de croquis a la derecha + sección huecos + observaciones
   abajo. Estilo ingeniería mecánica.

2. **Variante "densa"**: más tablas, menos espacio blanco, diseñada para trabajos
   complejos (cocina con isla + recercados) en una sola hoja. Leyenda de símbolos
   mínima al pie.

3. **Variante "abierta"**: cabecera compacta arriba, resto de la hoja libre con
   áreas sugeridas pero no delimitadas, para el operario más cómodo con el croquis
   libre. Útil sobre todo para lápidas y piezas especiales.

Para cada variante:
- Mockup visual (esquema) de la hoja en A4
- Campos exactos de la cabecera
- Disposición de la tabla de piezas (si la hay)
- Ubicación del área de croquis
- Leyenda de símbolos (X, CP, B/E, etc.)
- Sección de observaciones
- Pie de hoja (paginación, "Nota X de Y", fecha, firma)

Y un **ejemplo rellenado a mano** de una cocina típica con 6-8 piezas y un fregadero
B/E, para que el operario entienda cómo llenar los campos.

---

## 13. Consideraciones finales

- El diseño debe ser **tolerante a errores** (si el operario escribe mal o se salta
  un campo, la digitalización posterior aplicará defaults controlados — no debe
  bloquearse el workflow).
- El croquis a mano libre sigue siendo **central**. No intentes forzar todo a tabla.
- La cabecera debe ser **muy visible** y estar siempre arriba para que el
  digitalizador la encuentre al primer vistazo.
- **Preserva espacio para correcciones** (tachar una medida y escribir encima es
  frecuente en obra).

---

**Fin del briefing**. Con esto debería ser suficiente para diseñar plantillas
coherentes con el sistema de digitalización que tenemos montado.
