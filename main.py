import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta


# ==========================================
# 1. CLASES DE LÓGICA
# ==========================================
class Paciente:
    def __init__(self, nombre, apellido, edad, dni, dx, hospital):
        self.nombre = nombre
        self.apellido = apellido
        self.edad = edad
        self.dni = dni
        self.dx = dx
        self.hospital = hospital  # <-- NUEVO DATO
        self.estudios = []

    def __str__(self):
        return f"{self.apellido}, {self.nombre} (DNI: {self.dni}) - Hospital: {self.hospital}"


class Rotem:
    def __init__(self, extem_ct=None, extem_a5=None, extem_a10=None, extem_ml=None,
                 fibtem_a5=None, fibtem_a10=None, fibtem_ml=None,
                 intem_ct=None, heptem_ct=None, aptem_ml=None,
                 fecha_manual=None, sugerencia_manual=None):

        self.extem_ct = extem_ct
        self.extem_a5 = extem_a5
        self.extem_a10 = extem_a10
        self.extem_ml = extem_ml

        self.fibtem_a5 = fibtem_a5
        self.fibtem_a10 = fibtem_a10
        self.fibtem_ml = fibtem_ml

        self.intem_ct = intem_ct
        self.heptem_ct = heptem_ct
        self.aptem_ml = aptem_ml

        # Si viene del Excel, usamos los datos guardados. Si es nuevo, calculamos.
        if fecha_manual and sugerencia_manual:
            self.fecha_hora = fecha_manual
            self.sugerencia = sugerencia_manual
        else:
            hora_arg = datetime.utcnow() - timedelta(hours=3)
            self.fecha_hora = hora_arg.strftime("%d/%m/%Y %H:%M")
            self.sugerencia = self.interpretar()

    def interpretar(self):
        recomendaciones = []

        if self.extem_ml is not None and self.extem_ml > 15:
            if self.aptem_ml is not None and self.aptem_ml < 15:
                recomendaciones.append("1º - HIPERFIBRINOLISIS: Considerar Ac. Tranexámico")
            elif self.fibtem_ml is not None and self.fibtem_ml > 15:
                recomendaciones.append("1º - HIPERFIBRINOLISIS (Por EXTEM/FIBTEM): Considerar Ac. Tranexámico")

        if self.intem_ct is not None and self.intem_ct > 240:
            if self.heptem_ct is not None:
                if self.heptem_ct < 240:
                    recomendaciones.append("2º - EFECTO HEPARINA: Considerar Protamina")
                else:
                    recomendaciones.append("- DEFICIT FACTORES VÍA INTRÍNSECA o EXCESO PROTAMINA: Considerar PFC")
            else:
                recomendaciones.append("- INTEM CT Prolongado (>240): Falta HEPTEM para descartar Heparina.")

        firmeza_baja_extem = False
        if (self.extem_a5 is not None and self.extem_a5 < 30) or (self.extem_a10 is not None and self.extem_a10 < 40):
            firmeza_baja_extem = True

        if firmeza_baja_extem:
            if (self.fibtem_a5 is not None and self.fibtem_a5 < 9) or (
                    self.fibtem_a10 is not None and self.fibtem_a10 < 10):
                recomendaciones.append("3º - DEFICIT FIBRINÓGENO: Considerar Fibrinógeno Conc o Crioprecipitados")
            elif (self.fibtem_a5 is not None and self.fibtem_a5 >= 9) or (
                    self.fibtem_a10 is not None and self.fibtem_a10 >= 10):
                recomendaciones.append("4º - DEFICIT PLAQUETAS: Considerar Plaquetas")
            else:
                recomendaciones.append(
                    "- Firmeza baja en EXTEM: Falta cargar FIBTEM para diferenciar Plaquetas vs Fibrinógeno.")

        if self.extem_ct is not None and self.extem_ct > 80:
            recomendaciones.append("5º - DEFICIT FACTORES (Vit K dep.): Considerar Conc. Protrombínico o PFC")

        extem_normal = (self.extem_ct is not None and self.extem_ct <= 80) and \
                       ((self.extem_a5 is not None and self.extem_a5 >= 30) or (
                                   self.extem_a10 is not None and self.extem_a10 >= 40))
        intem_normal = (self.intem_ct is not None and self.intem_ct <= 240)

        if extem_normal and intem_normal and not recomendaciones:
            recomendaciones.append(
                "TRAZADO NORMAL. Si paciente sangra considerar: Ca, pH, Temp, Hb, Von Willebrand, inhibidores Xa, Quirúrgico.")

        if not recomendaciones:
            return "No se ingresaron datos suficientes o no superan umbrales."
        return "\n".join(recomendaciones)


# ==========================================
# 2. CONEXIÓN A GOOGLE SHEETS
# ==========================================
def conectar_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    skey = dict(st.secrets["gcp_service_account"])
    credentials = Credentials.from_service_account_info(skey, scopes=scopes)
    cliente = gspread.authorize(credentials)
    # Abre la planilla llamada Base_ROTEM y selecciona la Hoja 1
    sheet = cliente.open("Base_ROTEM").sheet1
    return sheet


def cargar_desde_sheets():
    try:
        sheet = conectar_sheets()
        filas = sheet.get_all_values()

        if not filas or len(filas) <= 1:
            return []

        datos = filas[1:]
        pacientes_dict = {}

        for fila in datos:
            # Ahora rellenamos hasta 7 columnas por si es un paciente viejo
            while len(fila) < 7:
                fila.append("No especificado")

            # Extraemos las 7 variables
            fecha, dni, apellido, nombre, dx, sugerencia, hospital = fila[:7]

            if dni not in pacientes_dict:
                pac = Paciente(nombre, apellido, "", dni, dx, hospital)
                pacientes_dict[dni] = pac

            estudio_recuperado = Rotem(fecha_manual=fecha, sugerencia_manual=sugerencia)
            pacientes_dict[dni].estudios.append(estudio_recuperado)

        return list(pacientes_dict.values())
    except Exception as e:
        st.error(f"Error de conexión inicial con Google Sheets: {e}")
        return []


def guardar_en_sheets(paciente, estudio):
    try:
        sheet = conectar_sheets()
        # Agregamos paciente.hospital al final de la lista
        nueva_fila = [
            estudio.fecha_hora,
            paciente.dni,
            paciente.apellido,
            paciente.nombre,
            paciente.dx,
            estudio.sugerencia,
            paciente.hospital  # <-- NUEVO DATO
        ]
        sheet.append_row(nueva_fila)
        return True
    except Exception as e:
        st.error(f"Error al guardar en la nube: {e}")
        return False


# ==========================================
# 3. INTERFAZ WEB (STREAMLIT)
# ==========================================
st.set_page_config(page_title="Sistema ROTEM", page_icon="🩸", layout="centered")

st.title("🩸 Gestión de ROTEM")
st.subheader("Servicio de Hemoterapia")

# Cargar la base de datos al iniciar la app
if 'pacientes' not in st.session_state:
    with st.spinner('Conectando con la base de datos del hospital...'):
        st.session_state.pacientes = cargar_desde_sheets()

tab_cargar, tab_buscar, tab_teoria = st.tabs(["📝 Cargar Nuevo Estudio", "🔍 Buscar Historial", "📚 Teoría y Protocolo"])

with tab_cargar:
    st.markdown("### Datos del Paciente")

    # Menú desplegable para elegir el hospital
    hospital_input = st.selectbox("🏥 Institución", ["Hospital Córdoba", "Hospital de Niños", "Hospital San Roque", "Otro"])

    col1, col2 = st.columns(2)
    with col1:
        dni_input = st.text_input("DNI del Paciente")
        nombre_input = st.text_input("Nombre")
    with col2:
        apellido_input = st.text_input("Apellido")
        edad_input = st.text_input("Edad")
    dx_input = st.text_input("Diagnóstico")

    st.markdown("---")
    st.markdown("### Valores ROTEM (Dejar vacío si no se realizó)")

    col_ex, col_fi, col_otros = st.columns(3)
    with col_ex:
        st.markdown("**EXTEM**")
        ex_ct = st.number_input("CT (>80)", value=None, format="%.1f", key="ex_ct")
        ex_a5 = st.number_input("A5 (<30)", value=None, format="%.1f", key="ex_a5")
        ex_a10 = st.number_input("A10 (<40)", value=None, format="%.1f", key="ex_a10")
        ex_ml = st.number_input("ML (>15)", value=None, format="%.1f", key="ex_ml")

    with col_fi:
        st.markdown("**FIBTEM**")
        fi_a5 = st.number_input("A5 (<9)", value=None, format="%.1f", key="fi_a5")
        fi_a10 = st.number_input("A10 (<10)", value=None, format="%.1f", key="fi_a10")
        fi_ml = st.number_input("ML (>15)", value=None, format="%.1f", key="fi_ml")
        st.markdown("**APTEM**")
        ap_ml = st.number_input("ML (<15)", value=None, format="%.1f", key="ap_ml")

    with col_otros:
        st.markdown("**INTEM**")
        in_ct = st.number_input("CT (>240)", value=None, format="%.1f", key="in_ct")
        st.markdown("**HEPTEM**")
        hep_ct = st.number_input("CT (>240)", value=None, format="%.1f", key="hep_ct")

    if st.button("Analizar y Guardar Estudio", type="primary"):
        if not dni_input:
            st.error("⚠️ El DNI es obligatorio para guardar el estudio.")
        else:
            paciente_actual = next((p for p in st.session_state.pacientes if p.dni == dni_input), None)

            if not paciente_actual:
                if not nombre_input or not apellido_input:
                    st.error("⚠️ Paciente nuevo detectado. Por favor, complete Nombre y Apellido.")
                    st.stop()
                paciente_actual = Paciente(nombre_input, apellido_input, edad_input, dni_input, dx_input,
                                           hospital_input)
                st.session_state.pacientes.append(paciente_actual)

            nuevo_estudio = Rotem(ex_ct, ex_a5, ex_a10, ex_ml, fi_a5, fi_a10, fi_ml, in_ct, hep_ct, ap_ml)
            paciente_actual.estudios.append(nuevo_estudio)

            # 🚀 GUARDAR EN LA NUBE (GOOGLE SHEETS) 🚀
            if guardar_en_sheets(paciente_actual, nuevo_estudio):
                st.success("✅ Estudio analizado y guardado permanentemente en la nube.")
                st.info(f"**SUGERENCIA TERAPÉUTICA:**\n\n{nuevo_estudio.sugerencia}")

with tab_buscar:
    st.markdown("### Buscar Historial por DNI")
    # Botón para forzar la actualización desde el Excel (por si otro médico cargó algo)
    if st.button("🔄 Refrescar base de datos"):
        st.session_state.pacientes = cargar_desde_sheets()
        st.success("Base de datos sincronizada con Google Sheets.")

    dni_buscar = st.text_input("Ingrese DNI para buscar", key="buscar")

    if st.button("Buscar Paciente"):
        if dni_buscar:
            paciente_encontrado = next((p for p in st.session_state.pacientes if p.dni == dni_buscar), None)

            if paciente_encontrado:
                st.write(
                    f"**Paciente:** {paciente_encontrado.apellido}, {paciente_encontrado.nombre} | **Hospital:** {paciente_encontrado.hospital} | **Diagnóstico:** {paciente_encontrado.dx}")
                st.markdown("---")

                # Invertimos la lista para que el estudio más nuevo salga arriba
                for i, est in enumerate(reversed(paciente_encontrado.estudios), 1):
                    with st.expander(f"🩸 Estudio #{i} - Realizado el: {est.fecha_hora}"):
                        st.write(f"**Sugerencia emitida:**")
                        st.code(est.sugerencia)
            else:
                st.warning("No se encontró ningún paciente con ese DNI en el historial.")

with tab_teoria:
    st.markdown("### 📚 Guía de Interpretación del ROTEM")
    st.write(
        "Esta sección explica el fundamento fisiológico detrás de las sugerencias del sistema, basado en el algoritmo terapéutico del hospital.")

    with st.expander("1. ¿Por qué este Orden Terapéutico?"):
        st.markdown("""
        El algoritmo sigue una lógica secuencial estricta en el manejo de la hemorragia masiva:
        * **1º Frenar la destrucción:** Si hay hiperfibrinólisis, cualquier coágulo formado se disolverá. Por eso el Ácido Tranexámico es la primera línea.
        * **2º Revertir anticoagulantes:** Si hay exceso de heparina, la cascada está frenada artificialmente. Se neutraliza con Protamina.
        * **3º y 4º Los 'ladrillos' del coágulo:** Sin una estructura física, no hay coágulo. Se prioriza el Fibrinógeno (la malla) y luego las Plaquetas (los tapones).
        * **5º El 'motor' de la coagulación:** Si ya hay ladrillos y no hay destrucción, pero el inicio es lento, recién ahí se aportan Factores (Complejo Protrombínico o PFC) para acelerar la vía.
        """)

    with st.expander("2. Significado de los Parámetros (CT, A5, A10, ML)"):
        st.markdown("""
        * **CT (Clotting Time - Tiempo de Coagulación):** Es el tiempo desde el inicio del test hasta que el coágulo alcanza 2 mm de firmeza. Mide el inicio de la coagulación y la acción de los factores (o presencia de heparina).
        * **A5 / A10 (Amplitud a los 5 o 10 min):** Mide la firmeza del coágulo a los 5 o 10 minutos de iniciado el CT. Depende principalmente de la cantidad de plaquetas y de fibrinógeno.
        * **ML (Maximum Lysis - Lisis Máxima):** Porcentaje de firmeza del coágulo que se pierde por fibrinólisis. Un valor >15% es señal de hiperfibrinólisis.
        """)

    with st.expander("3. ¿Para qué sirve cada Ensayo (POCILLO)?"):
        st.markdown("""
        * **EXTEM (Vía Extrínseca):** Se activa con factor tisular. Es una visión rápida y global de la coagulación (factores VII, X, II, V, fibrinógeno y plaquetas).
        * **INTEM (Vía Intrínseca):** Se activa con ácido elágico. Evalúa factores de contacto, VIII, IX, XI, XII. Es *muy sensible* a la heparina.
        * **FIBTEM (Fibrinógeno):** Es un EXTEM al que se le agrega *Citocalasina D*, que inhibe totalmente a las plaquetas. El coágulo resultante depende **exclusivamente del fibrinógeno**.
        * **HEPTEM (Heparinasa):** Es un INTEM al que se le agrega *Heparinasa*. Si el CT del INTEM es largo pero el del HEPTEM corrige y es normal, confirma la presencia de heparina.
        * **APTEM (Aprotinina):** Es un EXTEM al que se le agrega un inhibidor de la fibrinólisis (Aprotinina o Ac. Tranexámico in vitro). Si el EXTEM muestra lisis (ML >15%) pero el APTEM corrige, confirma la hiperfibrinólisis.
        """)