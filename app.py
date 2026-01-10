# =====================================================
# Streamlit MVP: GeoJSON → SHP alineado a Catálogo IDERA
# =====================================================
import streamlit as st
import geopandas as gpd
import pandas as pd
import difflib
import tempfile
import zipfile
import os
import json
from io import BytesIO
from shapely.geometry import MultiPolygon, MultiLineString, MultiPoint
import re
import unicodedata

# ------------------------------
# CONFIGURACIÓN GENERAL
# ------------------------------
st.set_page_config( 
    page_title="Laboratorio de la Brújula | Validador de Objetos Geográficos IDERA", 
    layout="wide" 
) 
st.subheader("LABORATORIO DE LA BRÚJULA") 
st.title("VALIDADOR DE OBJETOS GEOGRÁFICOS IDERA") 
st.markdown("Herramienta para la normalización y depuración de datos espaciales alineada al **Catálogo de Objetos de la IDERA**.") 
st.markdown("_Última actualización del catalogo, septiembre 2025._")
st.divider()

# ------------------------------
# CARGA CATÁLOGO IDERA
# ------------------------------
@st.cache_data
def cargar_catalogo(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

try:
    CATALOGO = cargar_catalogo("./catalogo/catalogo_idera.json")
except FileNotFoundError:
    st.error("No se encontró el archivo catalogo_idera.json. Verifique la ruta.")
    st.stop()

# ------------------------------
# MAPEO GEOMETRÍAS IDERA → GIS
# ------------------------------
MAPEO_GEOMETRIA = {
    "Punto": ["Point", "MultiPoint"],
    "Línea": ["LineString", "MultiLineString"],
    "Polígono": ["Polygon", "MultiPolygon"]
}

# ------------------------------
# CRS DISPONIBLES
# ------------------------------
CRS_SALIDA = {
    "Mantener sistema de proyección original": None,
    "EPSG:5340 – POSGAR 2007 / Argentina": 5340,
    "EPSG:5343 – POSGAR 2007 / Argentina 1": 5343,
    "EPSG:5344 – POSGAR 2007 / Argentina 2": 5344,
    "EPSG:5345 – POSGAR 2007 / Argentina 3": 5345,
    "EPSG:5346 – POSGAR 2007 / Argentina 4": 5346,
    "EPSG:5347 – POSGAR 2007 / Argentina 5": 5347,
    "EPSG:5348 – POSGAR 2007 / Argentina 6": 5348,
    "EPSG:5349 – POSGAR 2007 / Argentina 7": 5349,
    "EPSG:4326 – WGS 84": 4326
}

# ------------------------------
# FUNCIONES AUXILIARES
# ------------------------------
def reparar_encoding(texto):
    if not isinstance(texto, str):
        return texto
    try:
        return texto.encode("latin1").decode("utf-8")
    except Exception:
        return texto

def normalizar_geometria(gdf, og):
    tipo_actual = gdf.geom_type.unique()
    if len(tipo_actual) > 1:
        raise ValueError(f"El archivo contiene múltiples tipos geométricos: {tipo_actual}")
    tipo_actual = tipo_actual[0]
    tipos_validos = []
    for g in og["geometria"]:
        tipos_validos.extend(MAPEO_GEOMETRIA.get(g, []))
    if tipo_actual not in tipos_validos:
        if tipo_actual == "Point" and "MultiPoint" in tipos_validos:
            gdf["geometry"] = gdf.geometry.apply(lambda g: MultiPoint([g]))
        elif tipo_actual == "LineString" and "MultiLineString" in tipos_validos:
            gdf["geometry"] = gdf.geometry.apply(lambda g: MultiLineString([g]))
        elif tipo_actual == "Polygon" and "MultiPolygon" in tipos_validos:
            gdf["geometry"] = gdf.geometry.apply(lambda g: MultiPolygon([g]))
        else:
            raise ValueError(
                f"Tipo geométrico {tipo_actual} no permitido por IDERA "
                f"(permitidos: {og['geometria']})"
            )
    return gdf

def truncar_unico(cols):
    usados = {}
    resultado = []
    for c in cols:
        base = c[:10]
        if base not in usados:
            usados[base] = 1
            resultado.append(base)
        else:
            usados[base] += 1
            suf = str(usados[base])
            resultado.append(base[:10-len(suf)] + suf)
    return resultado

def validar_idera(gdf, og):
    errores = []
    for campo, reglas in og["atributos"].items():
        if reglas.get("obligatorio"):
            if campo not in gdf.columns:
                errores.append(f"Falta el campo obligatorio: {campo}")
            elif gdf[campo].isna().any():
                errores.append(f"Campo obligatorio vacío: {campo}")
    if not gdf.is_valid.all():
        errores.append("Existen geometrías inválidas")
    return errores

def exportar_shp_zip(gdf, nombre):
    buffer = BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        shp_path = os.path.join(tmp, nombre + ".shp")
        gdf.to_file(shp_path, driver="ESRI Shapefile", encoding="utf-8")
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
            for f in os.listdir(tmp):
                z.write(os.path.join(tmp, f), arcname=f)
    buffer.seek(0)
    return buffer

def normalizar_nombre_archivo(texto):
    texto = unicodedata.normalize("NFKD", texto)
    texto = texto.encode("ascii", "ignore").decode("ascii")
    texto = texto.lower().replace(" ", "_")
    texto = re.sub(r"[^a-z0-9_]", "", texto)
    return texto

# ------------------------------
# 1. CARGA DE DATOS
# ------------------------------
st.header("1. Carga de datos geoespaciales") 
uploaded = st.file_uploader("Arrastrar o seleccionar GeoJSON", type=["geojson", "json"])

if not uploaded:
    st.stop()

gdf = gpd.read_file(uploaded)
gdf_original = gdf.copy()
st.success(f"Archivo cargado correctamente ({len(gdf)} registros)")

# ------------------------------
# 2. CRS
# ------------------------------
st.divider()
st.header("2. Sistema de referencia de salida")
crs_actual = gdf.crs.to_epsg() if gdf.crs else None
st.info(f"CRS detectado: {crs_actual if crs_actual else 'No definido'}")

crs_sel = st.selectbox("Seleccione sistema de referencia de salida", options=list(CRS_SALIDA.keys()))
epsg_salida = CRS_SALIDA[crs_sel]

if epsg_salida is not None:
    if gdf.crs is None:
        st.error("El archivo no tiene CRS definido.")
        st.stop()
    elif crs_actual != epsg_salida:
        gdf = gdf.to_crs(epsg=epsg_salida)

# ------------------------------
# 3. SELECCIÓN OBJETO IDERA
# ------------------------------
st.divider()
st.header("3. Objeto geográfico IDERA")
clase = st.selectbox("Clase", options=list(CATALOGO.keys()), format_func=lambda c: f"{c} – {CATALOGO[c]['nombre']}")
subclase = st.selectbox("Subclase", options=list(CATALOGO[clase]["subclases"].keys()), format_func=lambda s: f"{s} – {CATALOGO[clase]['subclases'][s]['nombre']}")
objetos = CATALOGO[clase]["subclases"][subclase]["objetos"]
og_cod = st.selectbox("Objeto geográfico", options=list(objetos.keys()), format_func=lambda o: f"{o} – {objetos[o]['nombre']}")
og = objetos[og_cod]

# ------------------------------
# 4. NORMALIZACIÓN GEOMÉTRICA
# ------------------------------
st.divider()
st.header("4. Normalización geométrica")
try:
    gdf = normalizar_geometria(gdf, og)
    st.success("Geometría compatible con el objeto IDERA seleccionado.")
except ValueError as e:
    st.error(str(e))
    st.stop()

# ------------------------------
# 5. VISTA PREVIA ATRIBUTOS ORIGINALES
# ------------------------------
st.divider()
st.header("5. Vista previa – atributos originales")
st.markdown("Tabla de atributos original del archivo cargado (sin modificaciones).")
st.dataframe(gdf_original.drop(columns="geometry", errors="ignore"), width="stretch")

# ------------------------------
# 6. MAPEO DE ATRIBUTOS
# ------------------------------
st.divider()
st.header("6. Mapeo de atributos IDERA")
columnas_origen = [c for c in gdf.columns if c != "geometry"]
atributos_idera = list(og["atributos"].keys())

mapeo = {}
for attr in atributos_idera:
    sugerencias = difflib.get_close_matches(attr.lower(), [c.lower() for c in columnas_origen], n=1, cutoff=0.6)
    sugerida = None
    if sugerencias:
        sugerida = columnas_origen[[c.lower() for c in columnas_origen].index(sugerencias[0])]
    
    sel = st.selectbox(f"Origen para campo IDERA: **{attr}**", options=["— sin asignar —"] + columnas_origen, 
                       index=(columnas_origen.index(sugerida) + 1) if sugerida else 0, key=f"sel_{attr}")
    if sel != "— sin asignar —":
        mapeo[attr] = sel

# ------------------------------
# 7. VISTA Y EDICIÓN – TABLA IDERA
# ------------------------------
st.divider()
st.header("7. Vista y edición de atributos IDERA")

# Sincronización de estado: Si cambia el objeto o el mapeo, regeneramos la tabla limpia
mapeo_key = f"{og_cod}_{hash(frozenset(mapeo.items()))}"
if "last_mapeo_key" not in st.session_state or st.session_state.last_mapeo_key != mapeo_key:
    gdf_limpio = gdf[["geometry"]].copy()
    for attr in atributos_idera:
        if attr in mapeo:
            gdf_limpio[attr] = gdf[mapeo[attr]].apply(reparar_encoding)
        else:
            gdf_limpio[attr] = pd.NA
    st.session_state.gdf_editado = gdf_limpio[atributos_idera + ["geometry"]]
    st.session_state.last_mapeo_key = mapeo_key

# Asignación masiva
st.markdown("### Asignación masiva de valores")
col1, col2 = st.columns([3, 5])
with col1:
    at_const = st.selectbox("Seleccionar Atributo", options=atributos_idera, key="at_const")
with col2:
    val_const = st.text_input("Ingresar valor único para todas las filas", key="val_const")

if st.button("Aplicar masivamente"):
    if val_const:
        st.session_state.gdf_editado[at_const] = val_const
        st.success(f"Se ha asignado '{val_const}' a la columna {at_const}")
        st.rerun()

# Editor de tabla (Persistente)
st.markdown("Edición manual de celdas:")
df_for_editor = st.session_state.gdf_editado.drop(columns="geometry")
edited_df = st.data_editor(df_for_editor, width="stretch", key="data_editor_main")

# Sincronizar el GeoDataFrame con lo que el usuario editó a mano
if edited_df is not None:
    st.session_state.gdf_editado[atributos_idera] = edited_df

# ------------------------------
# 8 & 9. VALIDACIÓN Y EXPORTACIÓN
# ------------------------------
if st.button("Validar y generar descarga de Shapefile"):
    errores = validar_idera(st.session_state.gdf_editado, og)
    if errores:
        st.error("Se detectaron errores en la validación IDERA:")
        for e in errores: st.write(f"- {e}")
    else:
        st.success("¡Validación IDERA superada!")
        gdf_out = st.session_state.gdf_editado.copy()
        
        # Aplicar truncamiento de nombres para compatibilidad con DBF (máx 10 chars)
        gdf_out.columns = truncar_unico(gdf_out.columns)
        
        og_name = normalizar_nombre_archivo(og["nombre"])
        nombre_zip = f"{og_cod}_{og_name}"
        zip_file = exportar_shp_zip(gdf_out, nombre_zip)
        
        st.divider()
        st.download_button(
            label="Descargar SHP IDERA (ZIP)", 
            data=zip_file, 
            file_name=f"{nombre_zip}.zip", 
            mime="application/zip"
        )

st.divider()
st.markdown("Creado por el **Laboratorio de la Brújula** | Innovación digital para el territorio.")