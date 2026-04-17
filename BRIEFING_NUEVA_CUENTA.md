# BRIEFING PARA NUEVA SESIÓN DE CLAUDE
## Sistema de Diseño y Producción de Encimeras de Cocina
**Fecha**: 2026-04-18 | **Directorio de trabajo**: `/home/kecojones/Documents/ProgramaDeAcotacionesDXF/`

---

## ¿QUIÉN SOY Y QUÉ HACEMOS?

Soy el dueño de un negocio de fabricación e instalación de encimeras de cocina de piedra natural
y porcelánico en Galicia (España), con dos marcas: **Cocimoble** y **ACyC Accesorios y Cocinas**.

Estamos construyendo un **sistema automatizado de producción** que:
1. Lee los planos de medidas manuscritos de cada cocina (fotos en Trello)
2. Genera automáticamente los archivos DXF para la máquina CNC de corte
3. Calcula cuántas tablas de material necesitamos (nesting)
4. Genera PDFs acotados para el taller

---

## REPOSITORIOS GITHUB (cuenta: ROMPEFUEGOS)

- **ExtractorPiezas** (presupuestos): https://github.com/ROMPEFUEGOS/extractor-piezas-cocina
- **Sistema de Producción** (DXF CNC): https://github.com/ROMPEFUEGOS/sistema-produccion-encimeras

---

## ESTRUCTURA DE ARCHIVOS

```
/home/kecojones/Documents/ProgramaDeAcotacionesDXF/
├── dxf_auto_dim_v1.3.py          ← Acotador DXF→PDF (COMPLETO, en producción)
├── dxf_watcher.py                 ← Watcher de carpeta (COMPLETO)
├── trello_uploader.py             ← Sube PDFs a Trello (COMPLETO)
├── watcher_config.json            ← Config (credenciales Trello aquí)
│
├── ExtractorPiezas/               ← Extractor de presupuestos (COMPLETO)
│   ├── main.py
│   ├── claude_extractor.py        ← System prompt + extracción Claude Vision
│   ├── file_readers.py            ← PDF/Excel/imagen readers + EasyOCR
│   ├── models.py                  ← Modelos de datos
│   ├── generar_dxf.py             ← DXF de presupuesto (estimado, no producción)
│   └── calcular_tablas.py         ← Estimador de tablas necesarias
│
├── SistemaProduccion/             ← Pipeline producción (EN DESARROLLO)
│   ├── trello_client.py           ← API Trello: buscar tarjetas, descargar imgs
│   ├── medidas_extractor.py       ← Claude Vision para notas manuscritas
│   ├── dxf_produccion.py          ← Generador DXF para CNC (capas correctas)
│   └── main.py                    ← Orquestador completo
│
├── 1-DISEÑOS MAQUINA/             ← DXFs de producción reales (ejemplos)
│   ├── T7060_Laura_*/             ← Ejemplo con nota Trello + DXF manual
│   ├── J0288_Mercedes_*/
│   └── V0275_Manuel_*/
│
├── 2026-04-15CatalogoMateriales.xlsx  ← Base de datos materiales (precios, tablas)
├── Fotos Materiales (2)/          ← Imágenes de materiales (copiándose aún)
├── Guía de Lectura de Planos...docx   ← Reglas de dominio para leer planos
└── Informacion para hacer diseños.docx ← Parámetros CNC, capas DXF
```

---

## CREDENCIALES Y ACCESOS

**Anthropic API Key**: exportar como `ANTHROPIC_API_KEY` en el entorno

**Trello**:
- API key y token: en `/tmp/watcher_config_backup.json` (solo local, no subido a GitHub)
- Tablero: "Planificador de Trabajo" (ID: 62a382a99f14ff1369e0da58)
- Listas de trabajo: **COBRADO** + **COBRADO 2025**

El archivo con credenciales reales (no en GitHub) está en:
`/tmp/watcher_config_backup.json` — copiar a `watcher_config.json` antes de usar.

---

## SISTEMA DXF ACOTADOR AUTOMÁTICO (ya en producción)

`dxf_auto_dim_v1.3.py` + `dxf_watcher.py`:
- Vigila la carpeta `1-DISEÑOS MAQUINA/`
- Cuando detecta un `.dxf` nuevo, genera un PDF acotado automáticamente
- Sube el PDF a la tarjeta Trello correspondiente

**Cómo funciona el watcher**:
```bash
python3 dxf_watcher.py  # En Linux
# En Windows: doble clic en INICIAR_DXF_ACOTADOR.bat
```

---

## FORMATO DXF DE PRODUCCIÓN (lo que espera la CNC)

Las piezas son solo **LINE, CIRCLE, ARC** — líneas separadas, sin bloques ni polylines.

| Capa | Uso |
|------|-----|
| `0` | Todos los cortes con disco (piezas + huecos rectangulares) |
| `0-CON` | Fresado: huecos con curvas grandes (r > 20mm) |
| `1006` | Taladros: enchufes y grifos — CIRCLE r=35mm (broca 7cm) |
| `1002` | Bounding box de pieza indivisible |
| `1007` | Guía visual (no se corta) |

| Linetype | Uso |
|----------|-----|
| CONTINUOUS | Corte normal |
| DASHED (TAB) | Pausa disco: cruces de L, cabezas de placa/fregadero |
| HIDDEN | Dirección herramienta / ingletes |
| DOTTED (UTL) | Último pase lento |

**Parámetros físicos**:
- Disco = 3.5mm de ancho
- Separación mínima interna en L desde esquina = 50mm mínimo para poder cortar
- Enchufes = círculo r=35mm en capa 1006 (70mm diámetro, broca 7cm)
- Esquinas redondeadas ≤20mm → dibujar rectas (capa 0)
- Esquinas redondeadas >20mm → capa 0-CON (fresadora)

---

## CONVENCIONES DE LAS NOTAS MANUSCRITAS (Trello)

Las fotos de cada tarjeta pueden contener:
- **Nota de medidas** (papel cuadriculado, dibujada a mano): LA QUE NOS INTERESA
- Fotos de obra / renders del cliente
- Fotos de catálogo de aparatos (placa, fregadero → tamaño del hueco)
- PDFs de presupuesto MGR

**Reglas clave de lectura de planos**:
- Descuadro: número pequeño (+3, -7) en esquina = mm que se desvía respecto a 90°
- `568-` (guión al final) = la medida debe descontarse grosor+2mm del material
  (ej: material 20mm → restar 22mm: pieza final = 568-22 = 546mm)
- `->2460` (flecha + número) = distancia en esa dirección
- `X` en el centro de una línea = zona a pulir
- `|X` + número pequeño = vuelo de encimera (parte que sobresale, pulida)
- `B/E` en hueco fregadero = bajo encimera
- Rodapiés dibujados en L = cabezas ingletadas
- Placa siempre perpendicular al frente

**Reglas de corte de encimeras largas** (cuando supera el ancho del tablero):
1. Cortar por el hueco de la placa (invisible, tapado por el aparato; mínimo 70mm frente)
2. Cortar por el fregadero (solo si es sobre encimera)
3. Cortar a lo largo
4. Cortar por fregadero bajo encimera (solo si evita usar tabla extra)

**Convención del veteado**:
- En materiales veteados: encimera y chapeado deben salir del mismo tablero
- En nesting: colocar el chapeado ENCIMA de la encimera en el slab

---

## TAMAÑOS DE TABLAS (del Excel de materiales)

La columna `Standard Slab` y `Jumbo Slab` contienen el **área en m²**:

| Material | Standard | Jumbo |
|----------|----------|-------|
| Dekton | 3200×1440mm (4.608m²) | 3200×1681mm (5.379m²) |
| Silestone | 3040×1409mm (4.284m²) | 3040×1700mm (5.168m²) |
| Guidoni | 3000×1443mm (4.329m²) | 3000×1826mm (5.478m²) |
| Laminam/Sogestone | 3200×1640mm (5.249m²) | — |
| Neolith | 3200×1655mm (5.298m²) | — |
| Granito Nacional | 3040×2000mm (6.08m²) | — |
| Granito importación | 3000×1850mm (5.55m²) | — |

---

## REGLAS DE DOMINIO CONFIRMADAS

### Materiales
- **Porcelánico** (Dekton, Coverlam, Neolith, Laminam, Ceratop, Lapitec): fregadero SOBRE encimera por defecto; inglete en esquinas vistas de pilares
- **Cuarzo** (Silestone, Compac): igual que granito para nesting
- Todos los materiales con `Família=Guidoni` son importados (granito)

### Piezas
- Fondo mínimo encimera: 620mm (redondear desde 610mm)
- Copete: `1,2` en plantilla = espesor 1.2cm (la altura es siempre 5cm por defecto)
- Copete ≤9cm alto → tipo copete; ≥10cm → tipo frontal/chapeado
- Zócalo: altura por defecto 10cm si plantilla dice "sí" sin especificar
- Cascada (costado isla): para inglete = ancho×2; para contabilizar slab = añadir ancho a largo encimera

### Enchufes
- Plantilla tiene prioridad absoluta sobre presupuesto MGR
- Sin chapeado = sin enchufes (salvo que plantilla especifique)
- Por defecto con frontal: 1 enchufe cada 1.5ml de frontal

### Ingletes porcelánicos en pilares
- Pilar típico (2 lados vistos) = 4 cantos × altura_chapeado
- Ejemplo: 4 × 0.58m = 2.32ml ingletado

---

## ESTADO ACTUAL DEL SISTEMA DE PRODUCCIÓN

### ✅ Completado
- `SistemaProduccion/trello_client.py`: busca tarjetas, descarga imágenes, clasifica adjuntos
- `SistemaProduccion/medidas_extractor.py`: system prompt completo para Claude Vision, preprocesa imágenes, parsea JSON
- `SistemaProduccion/dxf_produccion.py`: genera DXF con capas correctas, descuadros, enchufes, huecos rectangulares
- `SistemaProduccion/main.py`: orquestador end-to-end (Trello→imgs→medidas→DXF→PDF→Trello)

### ⏳ Pendiente (próximos pasos, en orden)
1. **Prueba real** con API recargada: `python3 SistemaProduccion/main.py T7060 --guardar`
   - Comparar DXF generado con el manual en `1-DISEÑOS MAQUINA/T7060_*/`
2. **Clasificador de imágenes**: identificar cuál es la nota de medidas vs foto de obra
   - Heurística primero: tamaño archivo, aspect ratio
   - Si no es suficiente: llamada rápida Claude con miniatura
3. **Módulo de nesting** (split encimeras + packing en tablas):
   - Aplicar reglas de corte (placa > fregadero sobre > a lo largo > fregadero bajo)
   - Packing guillotina con kerf 3.5mm
   - Considerar veteado (chapeado encima de encimera)
4. **Base de datos de veteados**: analizar `Fotos Materiales (2)/` con Claude Vision
5. **Piezas complejas**: L-shape, descuadros múltiples, ingletes en DXF

### Cómo probar el pipeline sin gastar tokens
```bash
cd /home/kecojones/Documents/ProgramaDeAcotacionesDXF
python3 -c "
from SistemaProduccion.trello_client import cargar_config
t = cargar_config()
card = t.buscar_tarjeta('T7060')
print(card['name'])
adjs = t.obtener_adjuntos(card['id'])
info = t.clasificar_adjuntos(adjs)
print(info)
"
```

---

## EXTRACTOR DE PRESUPUESTOS (ya completo, uso separado)

Para analizar carpetas de proyectos Cocimoble/ACyC y generar JSON de piezas:
```bash
cd ExtractorPiezas
export ANTHROPIC_API_KEY=...
python3 main.py "/ruta/J0297_Cliente_Material" --guardar
python3 main.py "/ruta/Cocimoble2025" --batch --guardar
```

Proyectos ya procesados: J0047–J0232 (Cocimoble), J0010/J0027/J0083/J0160 (ACyC)

---

## NOTAS IMPORTANTES PARA LA IA

1. **No hay un solo archivo de credenciales en producción** — el watcher_config.json en el repo tiene placeholders; las credenciales reales están solo en local
2. **Las fotos de Trello son el input principal** del sistema de producción — no los PDFs de presupuesto MGR (esos son para el extractor de presupuestos)
3. **Los DXF de producción de ejemplo** están en `1-DISEÑOS MAQUINA/` — son el "ground truth" para validar los DXF generados automáticamente
4. **Prefijos de número de medida**: V=encimera estándar, T=taller/reposición, J=job Cocimoble, F=factura ACyC, P=proyecto, A=obra especial
5. **`Fotos Materiales (2)/`** se estaba copiando todavía — puede que no esté completa; son imágenes de alta resolución para identificar veteados
6. **El catálogo Excel** (`2026-04-15CatalogoMateriales.xlsx`) tiene Standard Slab y Jumbo Slab como áreas en m², no dimensiones directas
7. **EasyOCR** se usa en el extractor de presupuestos para leer plantillas manuscritas de Cocimoble — requiere modelo descargado
