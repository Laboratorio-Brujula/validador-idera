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
    page_title="Laboratorio de la Brújula | _Validador de Objetos Geográficos IDERA_", 
    layout="wide" ) 
st.subheader("LABORATORIO DE LA BRÚJULA") 
st.title("VALIDADOR DE OBJETOS GEOGRÁFICOS IDERA") 
st.markdown("Herramienta para la normalización y depuración de datos espaciales. Se trata de una app que facilita la reproyección a fajas locales, la corrección de tipos geométricos y la edición de tablas de atributos, asegurando que los archivos exportados en formato shapefile sean 100% interoperables y cumplan con la normativa vigente según el **Catálogo de Objetos de la Infraestructura de Datos Espaciales de la República Argentina**.") 
st.markdown("_Última actualización del catalogo, septiempre 2025._")
st.divider()

# ------------------------------
# CARGA CATÁLOGO IDERA
# ------------------------------
@st.cache_data
def cargar_catalogo(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

CATALOGO = cargar_catalogo("./catalogo/catalogo_idera.json")

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
st.markdown("_En esta primera versión de la aplicación, solo se admiten archivos únicos en formato geojson._")

uploaded = st.file_uploader(
    "Arrastrar o seleccionar archivo GeoJSON",
    type=["geojson", "json"]
)

if not uploaded:
    st.stop()

gdf = gpd.read_file(uploaded)
gdf_original = gdf.copy()

st.success(f"Archivo cargado correctamente ({len(gdf)} registros)")

# ------------------------------
# 2. SISTEMA DE REFERENCIA
# ------------------------------
st.divider()
st.header("2. Sistema de referencia de salida")
st.markdown("A continuación se visualiza el CRS detectado automáticamente.")

crs_actual = gdf.crs.to_epsg() if gdf.crs else None
st.info(f"CRS detectado: {crs_actual if crs_actual else 'No definido'}")

crs_sel = st.selectbox(
    "Si desea reproyectar el dato espacial, seleccione sistema de referencia de salida del siguiente desplegable.",
    options=list(CRS_SALIDA.keys())
)

epsg_salida = CRS_SALIDA[crs_sel]

if epsg_salida is not None:
    if gdf.crs is None:
        st.error("El archivo no tiene CRS definido. No puede reproyectarse.")
        st.stop()
    elif crs_actual != epsg_salida:
        gdf = gdf.to_crs(epsg=epsg_salida)
        st.success(f"Reproyectado a EPSG:{epsg_salida}")
else:
    st.info("Se mantiene el sistema de proyección original")

# ------------------------------
# 3. SELECCIÓN OBJETO IDERA
# ------------------------------
st.divider()
st.header("3. Objeto geográfico IDERA")
st.markdown("Seleccione la Clase, Subclase y nomenclación del Objeto geográfico. Automáticamente verificará que el tipo de geometría sea el correcto, de lo contrario se visualizará una adevertencia.")

clase = st.selectbox(
    "Clase",
    options=list(CATALOGO.keys()),
    format_func=lambda c: f"{c} – {CATALOGO[c]['nombre']}"
)

subclase = st.selectbox(
    "Subclase",
    options=list(CATALOGO[clase]["subclases"].keys()),
    format_func=lambda s: f"{s} – {CATALOGO[clase]['subclases'][s]['nombre']}"
)

objetos = CATALOGO[clase]["subclases"][subclase]["objetos"]

og_cod = st.selectbox(
    "Objeto geográfico",
    options=list(objetos.keys()),
    format_func=lambda o: f"{o} – {objetos[o]['nombre']}"
)

og = objetos[og_cod]

st.markdown("Si desea conocer la definición del Objeto geográfico según lo establecido por IDERA utilice el siguiente desplegable.")

with st.expander("Definición IDERA"):
    st.write(og.get("definicion", ""))

# =====================================================
# 4. NORMALIZACIÓN GEOMÉTRICA
# =====================================================
st.divider()
st.header("4. Normalización geométrica")
st.markdown("Automáticamente verificará que el tipo de geometría sea el correcto, de lo contrario se visualizará una adevertencia.")

gdf = normalizar_geometria(gdf, og)
st.success("Geometría compatible con IDERA")

# ------------------------------
# 5. VISTA PREVIA ATRIBUTOS
# ------------------------------
st.divider()
st.header("5. Vista previa – atributos originales")
st.markdown("La tabla a continuación muestra los atributos originales del dato espacial.")
st.dataframe(gdf_original.drop(columns="geometry"), use_container_width=True)

# ------------------------------
# 6. MAPEO DE ATRIBUTOS
# ------------------------------
st.divider()
st.header("6. Mapeo de atributos IDERA")
st.markdown("La sección lista las columnas obligatorias según el Catalogo por lo que se requiere seleccionar cuales se recuperan de la tabla de atributos del dato espacial original.")
st.markdown("_Aclaración: Si bien no es recomendable, pueden repetirse los contenidos y puede no asignarse valores referencias desde el original resultando en columnas vacías pero no nulas._")

columnas_origen = [c for c in gdf.columns if c != "geometry"]
atributos_idera = list(og["atributos"].keys())

mapeo = {}

for attr in atributos_idera:
    sugerencias = difflib.get_close_matches(
        attr.lower(),
        [c.lower() for c in columnas_origen],
        n=1,
        cutoff=0.6
    )
    sugerida = None
    if sugerencias:
        sugerida = columnas_origen[
            [c.lower() for c in columnas_origen].index(sugerencias[0])
        ]

    sel = st.selectbox(
        f"{attr}",
        options=["— sin asignar —"] + columnas_origen,
        index=(columnas_origen.index(sugerida) + 1) if sugerida else 0,
        key=attr
    )

    if sel != "— sin asignar —":
        mapeo[attr] = sel

# =====================================================
# 7 VISTA Y EDICIÓN – TABLA IDERA LIMPIA
# =====================================================
st.divider()
st.header("7. Vista y edición de atributos IDERA")
st.markdown("Vista previa de la tabla de atributos antes de la exportación. Si se desea realizar algún cambio en la misma, la misma puede ser editada.")
st.markdown("_Al final hacer click en el botón de -validar y generar SHP-_")

if not mapeo:
    st.info("Primero debe completar el mapeo de atributos IDERA.")
else:
    # Construir GDF limpio
    gdf_limpio = gdf[["geometry"]].copy()

    for attr_idera, col_origen in mapeo.items():
        gdf_limpio[attr_idera] = gdf[col_origen].apply(reparar_encoding)

    # Atributos definidos en el catálogo (todos)
    atributos_catalogo = list(og["atributos"].keys())

    # Crear columnas vacías para todos los atributos IDERA
    for attr in atributos_catalogo:
        if attr not in gdf_limpio.columns:
            gdf_limpio[attr] = pd.NA

    # Sobrescribir solo los atributos mapeados
    for attr_idera, col_origen in mapeo.items():
        gdf_limpio[attr_idera] = gdf[col_origen].apply(reparar_encoding)

    # Reordenar columnas: IDERA + geometría
    gdf_limpio = gdf_limpio[atributos_catalogo + ["geometry"]]

    # Mostrar editor (sin geometría)
    tabla_editable = st.data_editor(
        gdf_limpio.drop(columns="geometry"),
        use_container_width=True,
        num_rows="dynamic"
    )

    # Reinyectar cambios (TODOS los atributos IDERA)
    gdf_limpio[atributos_catalogo] = tabla_editable

    # Guardar en sesión
    st.session_state.gdf_editado = gdf_limpio

    st.success("Tabla IDERA lista para validación")

gdf_final = st.session_state.get("gdf_editado")

if gdf_final is None:
    st.error("No hay una tabla IDERA editada lista para validar.")
    st.stop()


if st.button("Validar y generar SHP"):
    st.divider()
    st.header("8. Validación final")
    st.markdown("Instancia final de validación del dato espacial.")
    # ------------------------------
    # VALIDACIÓN IDERA
    # ------------------------------
    errores = validar_idera(gdf_final, og)

    if errores:
        st.error("Errores de validación IDERA:")
        for e in errores:
            st.write(f"- {e}")
        st.stop()

    st.success("Validación IDERA superada correctamente")

    # ------------------------------
    # 8. VALIDACIÓN Y EXPORTACIÓN
    # ------------------------------
    st.divider()
    st.header("9. Exportación final del dato espacial")
    st.markdown("Haga click en el botón de descarga para finalizar el proceso y obtener el dato espacial validado según el Catálogo de Objetos de la Infraestructura de Datos Espaciales de la República Argentina.")
    # ------------------------------
    # AJUSTE FINAL SHAPEFILE
    # ------------------------------
    gdf_out = gdf_final.copy()

    # Nombres de campos ≤ 10 caracteres
    gdf_out.columns = truncar_unico(gdf_out.columns)

    # ------------------------------
    # NOMBRE DE ARCHIVO
    # ------------------------------
    og_name = normalizar_nombre_archivo(og["nombre"])

    nombre_zip = f"{og_cod}_{og_name}"

    # ------------------------------
    # EXPORTACIÓN
    # ------------------------------
    zip_file = exportar_shp_zip(gdf_out, nombre_zip)

    st.download_button(
        "Descargar SHP IDERA (ZIP)",
        data=zip_file,
        file_name=f"{nombre_zip}.zip",
        mime="application/zip"
    )
st.divider()
st.markdown("Creado en el **Laboratorio de la Brújula |** Innovación digital para el desarrollo territorial | _https://santifederico-validador-idera-app-uhrhkz.streamlit.app/_")