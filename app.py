import base64
from datetime import datetime, timedelta
import io
import random
import textwrap
import urllib.parse
import pandas as pd
import qrcode
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import streamlit as st
from twilio.rest import Client

# Importar Plotly opcionalmente para analítica gráfica
try:
    import plotly.express as px
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# =============================================================================
# FUNCIONES AUXILIARES DE CONVERSIÓN SEGURA
# =============================================================================
def safe_float(val, default=0.0):
    """Convierte un valor a float de manera segura frente a None, NaN o cadenas inválidas."""
    if val is None or pd.isna(val):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def safe_int(val, default=0):
    """Convierte un valor a int de manera segura frente a None, NaN o cadenas inválidas."""
    if val is None or pd.isna(val):
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default

# =============================================================================
# CONFIGURACIÓN DE LA PÁGINA
# =============================================================================
st.set_page_config(
    page_title="BankCali | Plataforma Financiera",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =============================================================================
# ESTILOS CSS PERSONALIZADOS, FORMATO TICKET POS Y ESTILOS DE IMPRESIÓN
# =============================================================================
st.markdown(
    textwrap.dedent("""
    <style>
        .main {
            background-color: #f8f9fa;
        }
        .css-1r6slb0, .stApp {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        h1, h2, h3 {
            color: #1E3A8A;
        }
        div.corporate-banner {
            padding: 25px 20px;
            background: linear-gradient(135deg, #0A192F 0%, #112240 50%, #1E3A8A 100%) !important;
            color: white !important;
            border-radius: 12px;
            margin-bottom: 25px;
            text-align: center;
            box-shadow: 0 6px 20px rgba(0,0,0,0.2);
            border: 1px solid #38BDF8;
        }
        div.corporate-banner h2, div.corporate-banner p {
            color: white !important;
        }
        .terms-box {
            background-color: #ffffff;
            border: 1px solid #cbd5e1;
            padding: 15px;
            border-radius: 8px;
            font-size: 0.85rem;
            max-height: 180px;
            overflow-y: scroll;
            color: #334155;
            margin-bottom: 15px;
        }
        .pos-ticket {
            background-color: #fffbeb;
            border: 1px dashed #d97706;
            padding: 20px;
            border-radius: 10px;
            font-family: 'Courier New', Courier, monospace;
            color: #1e293b;
            max-width: 420px;
            margin: 0 auto;
            box-shadow: 0 4px 10px rgba(0,0,0,0.08);
        }

        /* CONFIGURACIÓN DE IMPRESIÓN IMPRESORA TÉRMICA / PDF */
        @media print {
            body * {
                visibility: hidden;
            }
            .printable-area, .printable-area * {
                visibility: visible;
            }
            .printable-area {
                position: absolute;
                left: 0;
                top: 0;
                width: 100%;
            }
            .no-print {
                display: none !important;
            }
        }
    </style>
"""),
    unsafe_allow_html=True,
)

# =============================================================================
# CONEXIÓN Y MIGRACIÓN AUTOMÁTICA DE BASE DE DATOS EN SUPABASE
# =============================================================================
conn = st.connection("supabase", type="sql")

try:
    with conn.session as s:
        s.execute(
            text("ALTER TABLE comercios ADD COLUMN IF NOT EXISTS logo_base64 TEXT;")
        )
        s.execute(
            text("""
                CREATE TABLE IF NOT EXISTS parametros (
                    id INT PRIMARY KEY DEFAULT 1,
                    tasa_interes NUMERIC(5,2) DEFAULT 2.10,
                    pct_aval NUMERIC(5,2) DEFAULT 10.00,
                    monto_minimo INT DEFAULT 80000,
                    CONSTRAINT single_row CHECK (id = 1)
                );
            """)
        )
        s.execute(
            text("""
                INSERT INTO parametros (id, tasa_interes, pct_aval, monto_minimo)
                VALUES (1, 2.10, 10.00, 80000)
                ON CONFLICT (id) DO NOTHING;
            """)
        )
        s.commit()
except Exception:
    pass

# =============================================================================
# FUNCIONES AUXILIARES Y CONSULTA DE PARÁMETROS CENTRALIZADOS
# =============================================================================
def obtener_parametros():
    """Consulta la tasa activa, aval y monto mínimo centralizados en Supabase."""
    try:
        df_p = conn.query(
            "SELECT tasa_interes, pct_aval, monto_minimo FROM parametros WHERE id = 1",
            ttl=0,
        )
        if not df_p.empty:
            p = df_p.iloc[0]
            return (
                safe_float(p.get("tasa_interes"), 2.10) / 100.0,
                safe_float(p.get("pct_aval"), 10.00) / 100.0,
                safe_int(p.get("monto_minimo"), 80000),
            )
    except Exception:
        pass
    return 0.021, 0.10, 80000


def enviar_sms_twilio(celular_cliente, codigo_otp=None, mensaje_custom=None):
    celular_limpio = "".join(filter(str.isdigit, str(celular_cliente)))
    if not celular_limpio.startswith("57"):
        celular_limpio = "57" + celular_limpio

    numero_destino = f"+{celular_limpio}"

    if mensaje_custom:
        mensaje_body = mensaje_custom
    else:
        mensaje_body = f"Su codigo OTP para el credito BankCali en Puerto Rico es: {codigo_otp}"

    try:
        account_sid = st.secrets["twilio"]["ACCOUNT_SID"]
        auth_token = st.secrets["twilio"]["AUTH_TOKEN"]
        twilio_number = st.secrets["twilio"]["PHONE_NUMBER"]

        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=mensaje_body, from_=twilio_number, to=numero_destino
        )
        return True, message.sid
    except Exception as e:
        mensaje_encoded = urllib.parse.quote(mensaje_body)
        wa_url = f"https://api.whatsapp.com/send?phone={celular_limpio}&text={mensaje_encoded}"

        st.warning("⚠️ **Respaldo Gratuito Activado (WhatsApp):**")
        st.markdown(
            f"👉 [Clic aquí para enviar OTP por WhatsApp Gratis al cliente]({wa_url})",
            unsafe_allow_html=True,
        )
        return False, str(e)


def evaluar_riesgo_y_cupo(
    ingresos, gastos, meses_residencia=12, tiene_aval_comercio=True, moras_previas=0
):
    pct_gastos = (gastos / ingresos) if ingresos > 0 else 1
    margen_disponible = ingresos - gastos

    score_local = 100
    if meses_residencia < 6:
        score_local -= 35
    if not tiene_aval_comercio:
        score_local -= 25
    if moras_previas > 0:
        score_local -= moras_previas * 30

    if margen_disponible <= 0 or score_local < 45:
        return (
            0,
            "RECHAZADO",
            "❌ Crédito no aprobado por alto riesgo de arraigo o capacidad de pago insuficiente.",
        )

    if 100000 <= ingresos <= 1000000:
        cupo_base = 80000 if pct_gastos <= 0.40 else 50000
    elif 1000001 <= ingresos <= 2500000:
        cupo_base = margen_disponible * 0.25
    else:
        cupo_base = ingresos * 0.30

    factor_ponderador = max(0.40, score_local / 100.0)
    cupo_calculado = cupo_base * factor_ponderador
    cupo = round(max(50000, cupo_calculado) / 10000) * 10000

    estado = "APROBADO" if cupo > 0 else "RECHAZADO"
    mensaje = (
        f"✅ Cupo Aprobado por Scoring Comunitario: ${cupo:,.0f} COP (Score Local: {score_local}/100)."
        if cupo > 0
        else "❌ Crédito no aprobado por scoring insuficiente."
    )
    return cupo, estado, mensaje


def generar_tabla_amortizacion(
    monto_compra, num_cuotas, pct_aval=0.10, tasa_interes=0.021
):
    monto_aval = monto_compra * pct_aval
    subtotal = monto_compra + monto_aval
    interes_total = subtotal * (tasa_interes / 2) * num_cuotas
    total_pagar = subtotal + interes_total
    valor_cuota = total_pagar / num_cuotas

    capital_por_cuota = monto_compra / num_cuotas
    aval_por_cuota = monto_aval / num_cuotas
    interes_por_cuota = interes_total / num_cuotas

    cronograma = []
    saldo_restante = total_pagar
    fecha_base = datetime.now()

    for i in range(1, num_cuotas + 1):
        fecha_venc = fecha_base + timedelta(days=15 * i)
        saldo_restante -= valor_cuota
        cronograma.append({
            "N° Cuota": f"Cuota {i}",
            "Fecha Vencimiento": fecha_venc.strftime("%Y-%m-%d"),
            "Valor Cuota ($)": round(valor_cuota, 0),
            "Capital ($)": round(capital_por_cuota, 0),
            "Aval ($)": round(aval_por_cuota, 0),
            "Interés ($)": round(interes_por_cuota, 0),
            "Saldo Restante ($)": round(max(0, saldo_restante), 0),
        })

    df_amort = pd.DataFrame(cronograma)
    return df_amort, total_pagar, valor_cuota, monto_aval, interes_total


def reiniciar_formulario_pos():
    if "ultimo_ticket" in st.session_state:
        del st.session_state["ultimo_ticket"]
    st.session_state.compra_completada = False


# Manejo de estado de la sesión
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
    st.session_state.rol = None
    st.session_state.nombre = None
    st.session_state.documento = None
    st.session_state.comercio_asignado = None

if "compra_completada" not in st.session_state:
    st.session_state.compra_completada = False

# =============================================================================
# PANEL DE LOGIN (BARRA LATERAL)
# =============================================================================
st.sidebar.markdown(
    textwrap.dedent("""
    <div style="text-align: center; padding: 12px; background: #1E3A8A; border-radius: 8px; color: white; margin-bottom: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">
        <h3 style="color: white; margin: 0; font-size: 1.3rem;">Datos de Acceso</h3>
        <p style="font-size: 0.75rem; margin: 0; opacity: 0.85;">Plataforma BankCali</p>
    </div>
"""),
    unsafe_allow_html=True,
)

if not st.session_state.autenticado:
    st.sidebar.markdown("Por favor, ingresa tus credenciales autorizadas:")
    doc_login = st.sidebar.text_input("Documento de Usuario")
    pin_login = st.sidebar.text_input("PIN de Acceso", type="password")

    if st.sidebar.button("Iniciar Sesión", use_container_width=True):
        if doc_login and pin_login:
            try:
                usuario_db = conn.query(
                    "SELECT * FROM usuarios WHERE documento = :doc AND pin = :pin",
                    params={"doc": doc_login, "pin": pin_login},
                    ttl=0,
                )

                if not usuario_db.empty:
                    datos_usuario = usuario_db.iloc[0].to_dict()
                    st.session_state.autenticado = True
                    st.session_state.rol = datos_usuario.get("rol", "Cliente")
                    st.session_state.nombre = datos_usuario.get("nombre", "Usuario")
                    st.session_state.documento = datos_usuario.get("documento", doc_login)
                    st.session_state.comercio_asignado = datos_usuario.get(
                        "comercio_asignado", None
                    )
                    st.rerun()
                else:
                    st.sidebar.error("❌ Documento o PIN incorrectos.")
            except Exception as e:
                st.sidebar.error(f"Error al conectar con la base de datos: {e}")
        else:
            st.sidebar.warning("⚠️ Completa ambos campos.")

    st.sidebar.warning(
        "🔒 **Sistema Protegido**. Inicia sesión para habilitar las operaciones."
    )
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        "<p style='text-align: center; color: gray; font-size: 0.8rem;'>Desarrollado para Gestión Comercial<br>© 2026</p>",
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div style="text-align: center; padding: 20px;">
            <h1 style="color: #1E3A8A; font-size: 2.5rem; margin-bottom: 10px;">BankCali</h1>
            <p style="color: #555; font-size: 1.2rem; margin-bottom: 30px;">Plataforma Financiera de Crédito Rotativo • Puerto Rico (Caquetá)</p>
        </div>
    """,
        unsafe_allow_html=True,
    )

    col_centro1, col_centro2, col_centro3 = st.columns([1, 3, 1])
    with col_centro2:
        try:
            st.image("LOGOBANKCALI.jpeg", use_container_width=True)
        except Exception:
            st.error("No se pudo cargar el logo principal de BankCali.")

    st.stop()

# =============================================================================
# CONTROL DE NAVEGACIÓN Y PERMISOS SEGÚN EL ROL
# =============================================================================
st.sidebar.success(
    f"👤 **Sesión Activa:**\n\n{st.session_state.nombre}\n*({st.session_state.rol})*"
)

if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
    st.session_state.autenticado = False
    st.session_state.rol = None
    st.session_state.nombre = None
    st.session_state.documento = None
    st.session_state.comercio_asignado = None
    reiniciar_formulario_pos()
    st.rerun()

st.sidebar.markdown("---")

rol_actual = str(st.session_state.rol).strip()

es_admin = rol_actual in ["Administrador", "FUNDADOR (Administrador)", "FUNDADOR"]
es_comercio = rol_actual in ["Comercio Aliado", "Comercio"]
es_cliente = rol_actual.lower() == "cliente" or (not es_admin and not es_comercio)

# Menú de opciones según el tipo de rol
if es_cliente:
    menu_opciones = ["👤 Mi Portal de Cliente"]
elif es_comercio:
    menu_opciones = [
        "1. Simular / Solicitar Crédito (POS)",
        "2. Registrar Nuevo Cliente + Scoring de Cupo",
        "👤 Portal de Cliente (Vista Consulta)",
    ]
else:  # es_admin
    menu_opciones = [
        "1. Simular / Solicitar Crédito (POS)",
        "2. Registrar Nuevo Cliente + Scoring de Cupo",
        "3. Registrar Pagos / Abonar Cuotas",
        "4. Control de Cartera y Mora (Cobranzas)",
        "5. Gestión General de Clientes",
        "6. Gestión de Almacenes Aliados",
        "7. Panel General de Administración",
        "8. Gestión de Usuarios y Parámetros",
        "👤 Portal de Cliente (Vista Previa)",
    ]

st.sidebar.markdown("### 🧭 Menú de Navegación")
opcion = st.sidebar.selectbox(
    "Seleccione un módulo", menu_opciones, label_visibility="collapsed"
)

st.sidebar.markdown("---")
st.sidebar.markdown(
    "<p style='text-align: center; color: gray; font-size: 0.8rem;'>Sistema de Crédito Rotativo v3.0<br>Puerto Rico, Caquetá</p>",
    unsafe_allow_html=True,
)

# BANNER CORPORATIVO
st.markdown(
    textwrap.dedent("""
    <div class="corporate-banner">
        <h2 style="margin: 0; font-weight: 700; letter-spacing: 0.5px;">BankCali - Plataforma Financiera de Crédito Rotativo</h2>
        <p style="margin: 5px 0 0 0; font-size: 1.1rem; opacity: 0.95;">Puerto Rico (Caquetá) • Impulsando el comercio local</p>
    </div>
"""),
    unsafe_allow_html=True,
)

# =============================================================================
# FUNCION/MÓDULO: PORTAL DE CLIENTE
# =============================================================================
def render_modulo_cliente():
    st.header("👤 Portal del Cliente")
    st.markdown("Consulta tu cupo, estado de cuenta, plan de cuotas y comprobantes oficiales.")
    st.markdown("---")

    doc_cliente = st.session_state.get("documento", "")

    # Si es Administrador o Comercio, le permite buscar cualquier cédula para consultar
    if es_admin or es_comercio:
        doc_cliente_input = st.text_input("🔍 Consultar Cédula de Cliente:", value=doc_cliente)
        if doc_cliente_input:
            doc_cliente = doc_cliente_input.strip()

    if not doc_cliente:
        st.warning("⚠️ Ingresa un número de cédula válido para consultar la información del cliente.")
        return

    # Consultar datos del cliente en Supabase
    df_cli = conn.query("SELECT * FROM clientes WHERE cedula = :ced", params={"ced": doc_cliente}, ttl=0)

    if df_cli.empty:
        st.error(f"❌ No se encontró ningún cliente registrado con la cédula **{doc_cliente}**.")
        return

    cli = df_cli.iloc[0].to_dict()

    # Consultar créditos/solicitudes asociadas al cliente
    df_sol = conn.query(
        "SELECT * FROM solicitudes WHERE cedula_cliente = :ced ORDER BY fecha DESC",
        params={"ced": doc_cliente},
        ttl=0,
    )

    cupo_apr = safe_float(cli.get("cupo_aprobado"), 0.0)
    cupo_dis = safe_float(cli.get("cupo_disponible"), 0.0)
    cupo_uso = max(0.0, cupo_apr - cupo_dis)

    # Verificar morosidad general
    tiene_mora = False
    if not df_sol.empty:
        df_activos = df_sol[df_sol["estado"] == "ACTIVO"]
        if not df_activos.empty:
            for _, r in df_activos.iterrows():
                try:
                    f_dt = datetime.strptime(str(r["fecha"])[:10], "%Y-%m-%d")
                    if (datetime.now() - f_dt).days > 30:
                        tiene_mora = True
                        break
                except Exception:
                    pass

    estado_cuenta = "🔴 EN MORA" if tiene_mora else "🟢 AL DÍA"

    # 1. 👤 INFORMACIÓN PERSONAL & 💳 GESTIÓN DE CUPO
    col_p1, col_p2 = st.columns([1, 1], gap="large")

    with col_p1:
        st.markdown("##### 👤 Información Personal")
        st.info(f"""
        **Nombre:** {cli.get('nombre', 'N/A')}  
        **Cédula:** {cli.get('cedula', 'N/A')}  
        **Teléfono / Celular:** {cli.get('celular', 'N/A')}  
        **Correo:** {cli.get('correo_electronico', 'N/A')}  
        **Estado de Cuenta:** {estado_cuenta}
        """)

    with col_p2:
        st.markdown("##### 💳 Gestión de Cupo Rotativo")
        c1, c2, c3 = st.columns(3)
        c1.metric("Cupo Total", f"${cupo_apr:,.0f}")
        c2.metric("Cupo Usado", f"${cupo_uso:,.0f}")
        c3.metric("Disponible", f"${cupo_dis:,.0f}")

        pct_uso = (cupo_uso / cupo_apr) if cupo_apr > 0 else 0.0
        st.progress(min(1.0, max(0.0, pct_uso)), text=f"Uso del cupo: {pct_uso * 100:.1f}%")

    st.markdown("---")

    # PESTAÑAS DETALLADAS DEL CLIENTE
    tab_cuotas, tab_tickets, tab_sol = st.tabs([
        "📅 Plan de Cuotas y Vencimientos",
        "🧾 Comprobantes y Tickets POS",
        "📝 Solicitud de Crédito / Ampliación",
    ])

    # 📅 PLAN DE CUOTAS CON FECHA DE VENCIMIENTO
    with tab_cuotas:
        st.subheader("📅 Plan de Cuotas Pendientes con Fecha de Vencimiento")

        if df_sol.empty or df_sol[df_sol["estado"] == "ACTIVO"].empty:
            st.success("🎉 No tienes cuotas ni créditos pendientes por pagar actualmente.")
        else:
            df_activos = df_sol[df_sol["estado"] == "ACTIVO"]
            todas_cuotas = []
            tasa_db, aval_db, _ = obtener_parametros()

            for _, credito in df_activos.iterrows():
                n_cuotas = safe_int(credito.get("cuotas"), 1)
                monto_c = safe_float(credito.get("monto_compra"), 0.0)

                df_a, _, _, _, _ = generar_tabla_amortizacion(monto_c, n_cuotas, pct_aval=aval_db, tasa_interes=tasa_db)

                try:
                    f_inicio = datetime.strptime(str(credito["fecha"])[:10], "%Y-%m-%d")
                except Exception:
                    f_inicio = datetime.now()

                for idx, fila in df_a.iterrows():
                    f_venc = f_inicio + timedelta(days=15 * (idx + 1))
                    es_vencida = f_venc < datetime.now()

                    todas_cuotas.append({
                        "ID Crédito": credito.get("id", "N/A"),
                        "Comercio": credito.get("comercio", "N/A"),
                        "N° Cuota": fila["N° Cuota"],
                        "Fecha Vencimiento": f_venc.strftime("%Y-%m-%d"),
                        "Valor Cuota ($ COP)": f"${safe_float(fila['Valor Cuota ($)']):,.0f}",
                        "Estado": "🔴 VENCIDA" if es_vencida else "🟡 PENDIENTE",
                    })

            df_cuotas_vis = pd.DataFrame(todas_cuotas)
            st.dataframe(df_cuotas_vis, use_container_width=True, hide_index=True)

    # 🧾 COMPROBANTES Y TICKETS POS
    with tab_tickets:
        st.subheader("🧾 Historial de Compras y Comprobantes POS")

        if df_sol.empty:
            st.info("No se registran compras asociadas a este cliente.")
        else:
            for _, reg in df_sol.iterrows():
                monto_reg = safe_float(reg.get('monto_compra'), 0.0)
                saldo_reg = safe_float(reg.get('saldo_pendiente'), 0.0)
                vlr_cuota_reg = safe_float(reg.get('valor_cuota'), 0.0)
                total_reg = safe_float(reg.get('total_pagar'), 0.0)

                with st.expander(f"🛒 Compra en {reg.get('comercio', 'N/A')} - {reg.get('fecha', '')} (${monto_reg:,.0f} COP)"):
                    col_t1, col_t2 = st.columns([3, 1])
                    with col_t1:
                        st.write(f"**N° Crédito:** {reg.get('id', 'N/A')}")
                        st.write(f"**Cuotas:** {reg.get('cuotas', 0)} quincenales")
                        st.write(f"**Saldo Pendiente:** ${saldo_reg:,.0f} COP")
                        st.write(f"**Estado del Crédito:** {reg.get('estado', 'N/A')}")

                    with col_t2:
                        if st.button("🧾 Ver Ticket", key=f"btn_tck_{reg['id']}"):
                            st.session_state[f"show_ticket_{reg['id']}"] = True

                    if st.session_state.get(f"show_ticket_{reg['id']}", False):
                        tck_id = reg.get('id', '')
                        tck_fecha = reg.get('fecha', '')
                        tck_comercio = reg.get('comercio', '')
                        tck_monto = monto_reg
                        tck_cuotas = reg.get('cuotas', 0)
                        tck_vlr_cuota = vlr_cuota_reg
                        tck_total = total_reg

                        qr_data = f"BANKCALI|CREDITO:{tck_id}|CEDULA:{cli.get('cedula','')}|TOTAL:{tck_total:,.0f}"
                        qr_img = qrcode.make(qr_data)
                        buf = io.BytesIO()
                        qr_img.save(buf, format="PNG")
                        qr_b64 = base64.b64encode(buf.getvalue()).decode()

                        st.markdown(f"""
                        <div style="border: 2px dashed #d3ad69; border-radius: 10px; padding: 15px; background-color: #fffdf5; max-width: 350px; margin: 10px auto; font-family: monospace; color: #111;">
                            <div style="text-align: center;">
                                <h3 style="margin: 0; color: #0d233a;">{tck_comercio}</h3>
                                <p style="font-size: 11px; margin: 2px 0;">Financiado por <b>BANKCALI</b><br>Puerto Rico, Caquetá</p>
                            </div>
                            <hr style="border-top: 1px dashed #666;">
                            <p style="font-size: 12px; margin: 0;">
                                <b>N° Crédito:</b> {tck_id}<br>
                                <b>Fecha:</b> {tck_fecha}<br>
                                <b>Cliente:</b> {cli.get('nombre', '')}<br>
                                <b>Cédula:</b> {cli.get('cedula', '')}
                            </p>
                            <hr style="border-top: 1px dashed #666;">
                            <p style="font-size: 12px; margin: 0;">
                                <b>Monto Compra:</b> ${tck_monto:,.0f} COP<br>
                                <b>N° Cuotas:</b> {tck_cuotas}<br>
                                <b>Valor Cuota:</b> ${tck_vlr_cuota:,.0f} COP<br>
                                <b>Total a Pagar:</b> ${tck_total:,.0f} COP
                            </p>
                            <hr style="border-top: 1px dashed #666;">
                            <div style="text-align: center;">
                                <img src="data:image/png;base64,{qr_b64}" style="width: 75px; height: 75px;" />
                                <p style="font-size: 10px; margin-top: 4px;">Comprobante Oficial BankCali</p>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

    # 📝 SOLICITUD DE CRÉDITO / AMPLIACIÓN DE CUPO
    with tab_sol:
        st.subheader("📝 Solicitud de Crédito / Ampliación de Cupo")
        st.markdown("Solicita un aumento de cupo o un nuevo crédito especial directamente.")

        with st.form("form_solicitud_cliente_portal"):
            tipo_sol = st.selectbox("Tipo de Solicitud *", ["Ampliación de Cupo Rotativo", "Nuevo Crédito Especial"])
            monto_sol = st.number_input("Monto Requerido ($ COP) *", min_value=50000, step=50000, value=200000)
            plazo_pref = st.selectbox("Plazo Preferido *", ["2 Quincenas", "4 Quincenas", "6 Quincenas", "8 Quincenas"])
            motivo_sol = st.text_area("Motivo de la solicitud o soporte de ingresos")

            btn_enviar_sol = st.form_submit_button("🚀 Enviar Solicitud a Evaluación")

            if btn_enviar_sol:
                st.success("✅ Tu solicitud de crédito/ampliación ha sido enviada con éxito al administrador.")

# RENDERIZADO DEL PORTAL CLIENTE
if "Portal de Cliente" in opcion:
    render_modulo_cliente()

# =============================================================================
# MÓDULO 1: SOLICITUD EN POS CON AMORTIZACIÓN Y TICKET IMPRIMIBLE
# =============================================================================
elif opcion == "1. Simular / Solicitar Crédito (POS)":
    st.header("🏪 Módulo de Punto de Venta (Comercio Aliado)")
    st.markdown(
        "Simulación, cronograma de amortización y generación de ticket de venta imprimible."
    )
    st.markdown("---")

    # Obtención de parámetros centralizados en Supabase
    tasa_db, aval_db, monto_min_db = obtener_parametros()

    try:
        df_comercios = conn.query(
            "SELECT nombre, comision, logo_base64 FROM comercios", ttl=0
        )
    except Exception:
        df_comercios = pd.DataFrame()

    if df_comercios.empty:
        st.warning(
            "⚠️ No hay comercios registrados aún. Registre uno en 'Gestión de Almacenes Aliados'."
        )
    else:
        col1, col2 = st.columns(2, gap="large")
        with col1:
            st.markdown("##### 👤 Datos del Cliente")

            if (
                st.session_state.rol == "Comercio Aliado"
                and st.session_state.comercio_asignado
                and st.session_state.comercio_asignado != "N/A - Administrador"
            ):
                st.info(
                    f"🏢 Operando bajo la tienda: **{st.session_state.comercio_asignado}**"
                )
                comercio_sel = st.session_state.comercio_asignado
            else:
                comercio_sel = st.selectbox(
                    "Seleccione el Comercio Aliado", df_comercios["nombre"].tolist()
                )

            match_comercio = df_comercios[df_comercios["nombre"] == comercio_sel]
            comercio_comercio = (
                safe_float(match_comercio["comision"].values[0], 5.0)
                if not match_comercio.empty
                else 5.0
            )
            logo_comercio = (
                match_comercio["logo_base64"].values[0]
                if not match_comercio.empty and "logo_base64" in match_comercio.columns
                else None
            )

            cedula = st.text_input("Número de Cédula del Cliente")

            cliente_info = None
            if cedula:
                cliente_info_df = conn.query(
                    "SELECT nombre, celular, cupo_disponible FROM clientes WHERE cedula = :ced",
                    params={"ced": cedula},
                    ttl=0,
                )
                if not cliente_info_df.empty:
                    cliente_info = cliente_info_df.iloc[0]

            if cliente_info is not None:
                nombre_cliente = st.text_input(
                    "Nombre Completo del Cliente", value=cliente_info["nombre"]
                )
                celular = st.text_input(
                    "Número de Celular", value=cliente_info["celular"]
                )
                cupo_dispon_cli = safe_float(cliente_info.get("cupo_disponible"), 0.0)
                st.success(
                    f"💡 **Cupo Disponible del Cliente:** ${cupo_dispon_cli:,.0f} COP"
                )
            else:
                nombre_cliente = st.text_input("Nombre Completo del Cliente")
                celular = st.text_input("Número de Celular")
                if cedula:
                    st.warning(
                        "⚠️ Cliente no registrado. Seleccione la opción '2. Registrar Nuevo Cliente'."
                    )

        with col2:
            st.markdown("##### 🛒 Detalles de la Compra")
            monto_compra = st.number_input(
                "Monto de la Compra ($ COP)",
                min_value=monto_min_db,
                max_value=5000000,
                step=10000,
                value=max(monto_min_db, 80000),
            )
            cuotas = st.selectbox("Número de Cuotas (Quincenales)", [2, 3, 4, 6, 8])

            (
                df_amort,
                total_pagar,
                valor_cuota,
                monto_aval,
                interes_total,
            ) = generar_tabla_amortizacion(
                monto_compra, cuotas, pct_aval=aval_db, tasa_interes=tasa_db
            )
            desembolso = monto_compra * (1 - (comercio_comercio / 100))

        st.markdown("---")
        st.subheader("📊 Resumen Financiero y Cronograma de Pagos")
        res1, res2, res3, res4 = st.columns(4)
        res1.metric("Cuota Quincenal", f"${valor_cuota:,.0f} COP")
        res2.metric("Total a Pagar", f"${total_pagar:,.0f} COP")
        res3.metric("Tasa Aplicada (Supabase)", f"{tasa_db * 100:.2f}% Mes")
        res4.metric("Desembolso Neto Tienda", f"${desembolso:,.0f} COP")

        with st.expander(
            "📅 Ver Tabla de Amortización Quincenal Completa", expanded=False
        ):
            st.dataframe(df_amort, use_container_width=True, hide_index=True)

        excede_cupo = False
        if cliente_info is not None and monto_compra > safe_float(cliente_info.get("cupo_disponible"), 0.0):
            st.error("❌ La compra excede el cupo disponible del cliente.")
            excede_cupo = True

        st.markdown("---")
        if (
            not excede_cupo
            and cliente_info is not None
            and st.button(
                "📱 Generar y Enviar Código OTP de Autorización",
                use_container_width=True,
            )
        ):
            if nombre_cliente and cedula and celular:
                otp = random.randint(1000, 9999)
                st.session_state["otp_actual"] = otp

                exito_sms, resultado = enviar_sms_twilio(celular, otp)
                if exito_sms:
                    st.success(f"📱 ¡SMS enviado con éxito vía Twilio al celular {celular}!")
                else:
                    st.warning(
                        f"⚠️ Alerta (Modo de prueba/respaldo): Código OTP asignado: **{otp}**"
                    )
            else:
                st.error("Por favor completa todos los datos del cliente.")

        if "otp_actual" in st.session_state and not excede_cupo:
            st.markdown("#### 🔑 Verificación de Seguridad")
            otp_ingresado = st.text_input(
                "Ingrese el Código OTP de 4 dígitos enviado al cliente"
            )

            if st.button("✅ Confirmar Venta y Otorgar Crédito", use_container_width=True):
                if str(otp_ingresado) == str(st.session_state["otp_actual"]):
                    id_credito = f"CR-{random.randint(10000, 99999)}"
                    fecha_hoy = datetime.now().strftime("%Y-%m-%d %H:%M")

                    with conn.session as s:
                        s.execute(
                            text(
                                "UPDATE clientes SET cupo_disponible = cupo_disponible - :monto WHERE cedula = :cedula"
                            ),
                            {"monto": monto_compra, "cedula": cedula},
                        )
                        s.execute(
                            text("""
                                INSERT INTO solicitudes (id, fecha, comercio, cedula_cliente, monto_compra, cuotas, valor_cuota, total_pagar, saldo_pendiente, estado) 
                                VALUES (:id, :fecha, :comercio, :cedula, :monto, :cuotas, :cuota, :total, :saldo, :est)
                            """),
                            {
                                "id": id_credito,
                                "fecha": fecha_hoy,
                                "comercio": comercio_sel,
                                "cedula": cedula,
                                "monto": monto_compra,
                                "cuotas": cuotas,
                                "cuota": valor_cuota,
                                "total": total_pagar,
                                "saldo": total_pagar,
                                "est": "ACTIVO",
                            },
                        )
                        s.commit()

                    msg_confirm_compra = (
                        f"BankCali: Su compra por ${monto_compra:,.0f} COP en {comercio_sel} fue aprobada. Credito Nro {id_credito}. Cuota: ${valor_cuota:,.0f} COP."
                    )
                    enviar_sms_twilio(celular, mensaje_custom=msg_confirm_compra)

                    st.balloons()
                    st.success(f"🎉 ¡Crédito Aprobado! ID Crédito: **{id_credito}**")

                    st.session_state["ultimo_ticket"] = {
                        "id": id_credito,
                        "fecha": fecha_hoy,
                        "comercio": comercio_sel,
                        "logo_comercio": logo_comercio,
                        "cliente": nombre_cliente,
                        "cedula": cedula,
                        "monto": monto_compra,
                        "cuotas": cuotas,
                        "valor_cuota": valor_cuota,
                        "total": total_pagar,
                        "df_amort": df_amort,
                    }
                    st.session_state.compra_completada = True
                    del st.session_state["otp_actual"]
                else:
                    st.error("❌ Código OTP incorrecto.")

        # RENDERIZADO DEL TICKET POS
        if st.session_state.compra_completada and "ultimo_ticket" in st.session_state:
            t = st.session_state["ultimo_ticket"]

            qr_data = f"BANKCALI|CREDITO:{t['id']}|CEDULA:{t['cedula']}|TOTAL:{t['total']:,.0f}"
            qr_img = qrcode.make(qr_data)
            buffer = io.BytesIO()
            qr_img.save(buffer, format="PNG")
            qr_b64_str = base64.b64encode(buffer.getvalue()).decode()
            qr_html = f'<img src="data:image/png;base64,{qr_b64_str}" style="width: 85px; height: 85px; margin-top: 8px;" />'

            logo_html = ""
            if t.get("logo_comercio"):
                src_img = (
                    t["logo_comercio"]
                    if str(t["logo_comercio"]).startswith("data:image")
                    else f"data:image/png;base64,{t['logo_comercio']}"
                )
                logo_html = f'<img src="{src_img}" style="max-height: 55px; max-width: 180px; margin-bottom: 6px;" /><br>'

            st.markdown(
                """
                <style>
                @page { size: auto; margin: 0mm; }
                @media print {
                    html, body { height: 100% !important; overflow: hidden !important; background: #ffffff !important; }
                    body * { visibility: hidden !important; }
                    .ticket-pos-box, .ticket-pos-box * { visibility: visible !important; }
                    .ticket-pos-box {
                        position: fixed !important;
                        left: 50% !important;
                        top: 20px !important;
                        transform: translateX(-50%) !important;
                        width: 320px !important;
                        margin: 0 !important;
                        padding: 15px !important;
                        border: 1px dashed #000 !important;
                        background: #ffffff !important;
                        color: #000000 !important;
                        box-shadow: none !important;
                    }
                }
                </style>
                """,
                unsafe_allow_html=True,
            )

            ticket_html = f"""
            <div class="ticket-pos-box" style="border: 2px dashed #d3ad69; border-radius: 10px; padding: 20px; background-color: #fffdf5; max-width: 380px; margin: 20px auto; font-family: monospace; color: #111;">
                <div style="text-align: center;">
                    {logo_html}
                    <h3 style="margin: 0; color: #0d233a;">{t['comercio']}</h3>
                    <p style="margin: 4px 0; font-size: 12px;">Financiado por <b>BANKCALI</b><br>Puerto Rico, Caquetá<br><b>COMPROBANTE DE COMPRA A CRÉDITO</b></p>
                </div>
                <hr style="border: none; border-top: 1px dashed #666;">
                <p style="font-size: 13px; line-height: 1.6; margin: 0;">
                    <b>N° Crédito:</b> {t['id']}<br>
                    <b>Fecha:</b> {t['fecha']}<br>
                    <b>Cliente:</b> {t['cliente']}<br>
                    <b>Cédula:</b> {t['cedula']}
                </p>
                <hr style="border: none; border-top: 1px dashed #666;">
                <p style="font-size: 13px; line-height: 1.6; margin: 0;">
                    <b>Monto Compra:</b> ${t['monto']:,.0f} COP<br>
                    <b>N° Cuotas:</b> {t['cuotas']} Quincenales<br>
                    <b>Valor Cuota:</b> ${t['valor_cuota']:,.0f} COP<br>
                    <b>Total a Pagar:</b> ${t['total']:,.0f} COP
                </p>
                <hr style="border: none; border-top: 1px dashed #666;">
                <div style="text-align: center;">
                    {qr_html}
                    <p style="font-size: 10px; margin-top: 4px; color: #555;">Escanear para verificar comprobante</p>
                    <p style="font-size: 11px; margin-top: 6px; color: #444;">Firma Digital Verificada vía OTP SMS<br>¡Gracias por su compra!</p>
                </div>
            </div>
            """
            st.markdown(ticket_html, unsafe_allow_html=True)

            js_btn = """
            <script>
            function imprimirTicket() { window.parent.print(); }
            </script>
            <button onclick="imprimirTicket()" style="background-color: #0f2537; color: white; border: none; padding: 12px 20px; border-radius: 8px; width: 100%; font-weight: bold; font-size: 15px; cursor: pointer;">
                🖨️ Imprimir Ticket / Guardar PDF
            </button>
            """
            st.components.v1.html(js_btn, height=65)

            if st.button("🔄 Registrar Nueva Compra / Limpiar Formulario", use_container_width=True):
                reiniciar_formulario_pos()
                st.rerun()

# =============================================================================
# MÓDULO 2: REGISTRAR NUEVO CLIENTE + SCORING DE CUPO COMUNITARIO
# =============================================================================
elif opcion == "2. Registrar Nuevo Cliente + Scoring de Cupo":
    st.header("📝 Evaluación, Firma de Acuerdo y Registro de Cliente")
    st.markdown(
        "Sistema automatizado de scoring crediticio comunitario con verificación por SMS (OTP) / WhatsApp y aceptación contractual."
    )

    tasa_db, aval_db, _ = obtener_parametros()

    if es_admin:
        st.info(
            f"💡 **Política Activa:** Tasa vigente del {tasa_db * 100:.2f}% mes, tarifa aval del {aval_db * 100:.1f}%. Scoring ponderado por margen disponible, residencia y aval local."
        )

    st.markdown("---")

    col_e1, col_e2 = st.columns(2, gap="large")
    with col_e1:
        st.markdown("##### 🪪 Información Personal")
        c_cedula = st.text_input("Número de Cédula *")
        c_nombre = st.text_input("Nombre Completo *")
        c_celular = st.text_input("Número de Celular *")
        c_correo = st.text_input(
            "Correo Electrónico *", placeholder="cliente@ejemplo.com"
        )
        c_direccion = st.text_input("Dirección de Residencia *")
        c_meses_residencia = st.number_input(
            "Meses Residiendo en el Municipio *", min_value=1, value=12, step=1
        )

    with col_e2:
        st.markdown("##### 💼 Perfil Económico y Arraigo Comunitario")
        c_ocupacion = st.selectbox("Actividad Económica *", [
            "Seleccione una actividad...",
            "Empleado Público / Oficial",
            "Empleado Privado (Formal)",
            "Comerciante / Dueño de Negocio",
            "Independiente / Prestador de Servicios",
            "Ganadero / Pecuario",
            "Agricultor / Productor Agrícola",
            "Pensionado / Jubilado",
            "Transportador / Conductor",
            "Otro / Oficios Varios",
        ])
        c_ingresos = st.number_input(
            "Ingresos Mensuales ($ COP) *",
            min_value=0,
            max_value=20000000,
            step=50000,
            value=1000000,
        )
        c_gastos = st.number_input(
            "Gastos Mensuales Estimados ($ COP) *",
            min_value=0,
            max_value=15000000,
            step=50000,
            value=400000,
        )
        c_aval_comercio = st.checkbox(
            "¿Cuenta con aval/referencia directa del comercio aliado?", value=True
        )

    cupo_sugerido, nivel_riesgo, mensaje_eval = evaluar_riesgo_y_cupo(
        ingresos=c_ingresos,
        gastos=c_gastos,
        meses_residencia=c_meses_residencia,
        tiene_aval_comercio=c_aval_comercio,
    )

    st.markdown("---")
    st.subheader("🎯 Resultado de la Evaluación de Riesgo Comunitario")

    col_res1, col_res2 = st.columns(2)
    col_res1.metric("Cupo Aprobado Asignado", f"${cupo_sugerido:,.0f} COP")
    if nivel_riesgo == "APROBADO":
        col_res2.success(f"🟢 **{nivel_riesgo}**\n\n{mensaje_eval}")
    else:
        col_res2.error(f"🔴 **{nivel_riesgo}**\n\n{mensaje_eval}")

    st.markdown("---")

    campos_completos = (
        c_cedula.strip() != ""
        and c_nombre.strip() != ""
        and c_celular.strip() != ""
        and c_correo.strip() != ""
        and c_direccion.strip() != ""
        and c_ocupacion != "Seleccione una actividad..."
    )

    if not campos_completos:
        st.warning("⚠️ Completa todos los campos obligatorios para proceder.")

    elif cupo_sugerido <= 0:
        st.error("❌ El scoring crediticio no aprobó cupo para el cliente.")

    else:
        st.subheader("📄 Acuerdo Comercial y Términos del Crédito Rotativo")

        st.markdown(
            textwrap.dedent(f"""
            <div class="terms-box">
                <h4>CONTRATO DE LÍNEA DE CRÉDITO ROTATIVO Y AUTORIZACIÓN DE FIRMA DIGITAL</h4>
                <p><strong>Partes:</strong> BankCali (Operador Financiero Puerto Rico, Caquetá) y el Cliente titular de la Cédula No. <strong>{c_cedula}</strong> ({c_nombre}).</p>
                <p><strong>1. OBJETO:</strong> BankCali otorga al CLIENTE una línea de Crédito Rotativo con un cupo aprobado de <strong>${cupo_sugerido:,.0f} COP</strong> para ser utilizado exclusivamente en comercios aliados autorizados del municipio de Puerto Rico, Caquetá.</p>
                <p><strong>2. USO Y AMORTIZACIÓN:</strong> El cliente podrá realizar compras diferidas en cuotas quincenales (2 a 8 cuotas). Cada cuota cancelada liberará cupo disponible.</p>
                <p><strong>3. TASAS Y COSTOS:</strong> Tasa de interés de plazo del {tasa_db * 100:.2f}% mensual (proporcional quincenal) y tarifa de Aval del {aval_db * 100:.1f}% sobre compra.</p>
                <p><strong>4. AUTORIZACIÓN Y NOTIFICACIÓN POR SMS/WHATSAPP:</strong> El CLIENTE autoriza el envío de notificaciones y la validación por código OTP enviado al número móvil <strong>{c_celular}</strong> como firma electrónica válida conforme a la Ley 527 de 1999.</p>
            </div>
            """),
            unsafe_allow_html=True,
        )

        acepta_terminos = st.checkbox(
            f"☑️ Confirmo que el cliente {c_nombre} ha leído y ACEPTA los Términos del Acuerdo Comercial."
        )

        st.markdown("---")
        st.subheader("📲 Verificación y Notificación por SMS / WhatsApp (Firma Digital)")

        if st.button(
            "📱 Enviar Código OTP de Solicitud de Crédito al Cliente",
            use_container_width=True,
            disabled=not acepta_terminos,
        ):
            otp_registro = random.randint(1000, 9999)
            st.session_state["otp_registro_actual"] = otp_registro

            msg_solicitud = (
                f"BankCali: Su codigo OTP para autorizar la apertura de Credito Rotativo por ${cupo_sugerido:,.0f} COP es: {otp_registro}. Al entregarlo acepta los terminos del contrato."
            )
            exito_sms, resultado = enviar_sms_twilio(
                c_celular, mensaje_custom=msg_solicitud
            )

            if exito_sms:
                st.success(
                    f"📱 ¡Notificación y OTP de solicitud enviada vía SMS al celular {c_celular}!"
                )
            else:
                st.info(
                    f"💡 Código OTP generado correctamente: **{otp_registro}**. Puede enviarlo por WhatsApp utilizando la opción de respaldo arriba."
                )

        if "otp_registro_actual" in st.session_state and acepta_terminos:
            st.markdown("#### 🔑 Confirmación de Autorización del Cliente")
            otp_ingresado_reg = st.text_input(
                "Ingrese el Código OTP de 4 dígitos suministrado por el cliente"
            )

            if st.button(
                "✅ Validar OTP, Activar Crédito y Registrar Cliente",
                use_container_width=True,
            ):
                if str(otp_ingresado_reg) == str(st.session_state["otp_registro_actual"]):
                    try:
                        with conn.session as s:
                            s.execute(
                                text("""
                                    INSERT INTO clientes (cedula, nombre, celular, correo_electronico, direccion, ocupacion, ingresos, gastos, cupo_aprobado, cupo_disponible) 
                                    VALUES (:ced, :nom, :cel, :correo, :dir, :ocu, :ing, :gas, :c_apr, :c_dis)
                                """),
                                {
                                    "ced": c_cedula,
                                    "nom": c_nombre,
                                    "cel": c_celular,
                                    "correo": c_correo,
                                    "dir": c_direccion,
                                    "ocu": c_ocupacion,
                                    "ing": c_ingresos,
                                    "gas": c_gastos,
                                    "c_apr": cupo_sugerido,
                                    "c_dis": cupo_sugerido,
                                },
                            )
                            s.commit()

                        msg_bienvenida = (
                            f"BankCali: Felicidades {c_nombre}, tu solicitud de Credito Rotativo ha sido APROBADA y ACTIVADA por ${cupo_sugerido:,.0f} COP. Gracias por confiar en nosotros."
                        )
                        enviar_sms_twilio(c_celular, mensaje_custom=msg_bienvenida)

                        st.balloons()
                        st.success(
                            f"🎉 ¡Crédito Rotativo Activado! Cliente **{c_nombre}** registrado con cupo de **${cupo_sugerido:,.0f} COP**."
                        )
                        del st.session_state["otp_registro_actual"]

                    except IntegrityError:
                        st.error("❌ Ya existe un cliente registrado con esa cédula.")
                    except Exception as e:
                        st.error(f"Error de base de datos: {e}")
                else:
                    st.error("❌ Código OTP incorrecto.")

# =============================================================================
# MÓDULO 3: REGISTRO DE PAGOS (SOLO ADMIN)
# =============================================================================
elif opcion == "3. Registrar Pagos / Abonar Cuotas" and es_admin:
    st.header("💵 Módulo de Recaudo y Abono a Cuotas")
    st.markdown("Registro de abonos, liberación de cupo y envío de recibo por SMS.")
    st.markdown("---")

    id_credito_buscar = st.text_input(
        "Ingrese Número de Crédito (Ej: CR-12345) o Cédula del Cliente"
    )
    if id_credito_buscar:
        df_sol = conn.query(
            """
                SELECT s.id, s.fecha, s.comercio, c.nombre, s.cedula_cliente, c.celular, s.valor_cuota, s.saldo_pendiente, s.estado 
                FROM solicitudes s
                JOIN clientes c ON s.cedula_cliente = c.cedula
                WHERE s.id = :termino OR s.cedula_cliente = :termino
            """,
            params={"termino": id_credito_buscar},
        )

        if df_sol.empty:
            st.warning("⚠️ No se encontraron créditos asociados.")
        else:
            st.dataframe(
                df_sol[[
                    "id",
                    "fecha",
                    "comercio",
                    "nombre",
                    "cedula_cliente",
                    "valor_cuota",
                    "saldo_pendiente",
                    "estado",
                ]],
                use_container_width=True,
                hide_index=True,
            )

            credito_sel = st.selectbox(
                "Seleccione el ID de Crédito a Abonar", df_sol["id"].tolist()
            )
            fila_credito = df_sol[df_sol["id"] == credito_sel].iloc[0]

            saldo_act = safe_float(fila_credito.get("saldo_pendiente"), 0.0)
            vlr_cuota = safe_float(fila_credito.get("valor_cuota"), 0.0)
            celular_cli = fila_credito.get("celular", "")

            st.markdown("---")
            col_p1, col_p2 = st.columns(2)
            col_p1.info(f"📌 **Saldo Pendiente Actual:** ${saldo_act:,.0f} COP")
            col_p2.info(f"📌 **Valor Cuota Sugerido:** ${vlr_cuota:,.0f} COP")

            if saldo_act <= 0:
                st.info(
                    "ℹ️ Este crédito se encuentra CANCELADO. No registra saldo pendiente por abonar."
                )
            else:
                min_p = 0.0 if saldo_act <= 0 else 1.0
                val_s = max(min_p, float(min(vlr_cuota, saldo_act)))

                monto_abono = st.number_input(
                    "Monto del Abono ($ COP)",
                    min_value=min_p,
                    max_value=max(min_p, float(saldo_act)),
                    value=val_s,
                    step=1000.0,
                )

                if st.button("💾 Registrar Pago Oficial", use_container_width=True):
                    fecha_pago = datetime.now().strftime("%Y-%m-%d %H:%M")
                    nuevo_saldo = saldo_act - monto_abono
                    nuevo_estado = "CANCELADO" if nuevo_saldo <= 0 else "ACTIVO"

                    with conn.session as s:
                        s.execute(
                            text(
                                "INSERT INTO pagos (fecha, id_credito, monto_pagado) VALUES (:f, :id_c, :m)"
                            ),
                            {"f": fecha_pago, "id_c": credito_sel, "m": monto_abono},
                        )
                        s.execute(
                            text(
                                "UPDATE solicitudes SET saldo_pendiente = :ns, estado = :ne WHERE id = :id_c"
                            ),
                            {"ns": nuevo_saldo, "ne": nuevo_estado, "id_c": credito_sel},
                        )
                        s.execute(
                            text(
                                "UPDATE clientes SET cupo_disponible = cupo_disponible + :m WHERE cedula = :ced"
                            ),
                            {"m": monto_abono, "ced": fila_credito["cedula_cliente"]},
                        )
                        s.commit()

                    msg_pago = (
                        f"BankCali: Recibimos tu abono de ${monto_abono:,.0f} COP al credito {credito_sel}. Nuevo saldo: ${nuevo_saldo:,.0f} COP. Tu cupo ha sido liberado."
                    )
                    enviar_sms_twilio(celular_cli, mensaje_custom=msg_pago)

                    st.success(
                        f"✅ Pago por ${monto_abono:,.0f} COP registrado con éxito. Nuevo saldo: **${nuevo_saldo:,.0f} COP**."
                    )

# =============================================================================
# MÓDULO 4: CONTROL DE CARTERA VENCIDA Y MORA (COBRANZAS)
# =============================================================================
elif opcion == "4. Control de Cartera y Mora (Cobranzas)" and es_admin:
    st.header("⚠️ Panel de Control de Cartera y Gestión de Mora")
    st.markdown(
        "Seguimiento de cuotas, semáforo de riesgo y recordatorios masivos e individuales por SMS."
    )
    st.markdown("---")

    df_cartera = conn.query(
        """
        SELECT s.id, s.fecha, s.comercio, c.nombre, c.cedula, c.celular, s.monto_compra, s.valor_cuota, s.saldo_pendiente, s.estado
        FROM solicitudes s
        JOIN clientes c ON s.cedula_cliente = c.cedula
        WHERE s.estado = 'ACTIVO'
    """,
        ttl=0,
    )

    if df_cartera.empty:
        st.success("🎉 ¡Excelente! No hay créditos activos o en cartera pendiente actualmente.")
    else:
        df_cartera["Fecha_DT"] = pd.to_datetime(df_cartera["fecha"])
        hoy = datetime.now()
        df_cartera["Dias_Transcurridos"] = (hoy - df_cartera["Fecha_DT"]).dt.days

        def clasificar_mora(dias):
            if dias <= 15:
                return "🟢 Al Día"
            elif 15 < dias <= 30:
                return "🟡 Vencimiento Cercano"
            else:
                return "🔴 En Mora (>30 días)"

        df_cartera["Estado_Mora"] = df_cartera["Dias_Transcurridos"].apply(clasificar_mora)

        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Total Créditos Activos", len(df_cartera))
        col_m2.metric(
            "Cartera en Riesgo / Mora",
            len(df_cartera[df_cartera["Estado_Mora"] != "🟢 Al Día"]),
        )
        col_m3.metric(
            "Saldo Total Pendiente",
            f"${df_cartera['saldo_pendiente'].sum():,.0f} COP",
        )

        st.markdown("---")
        st.subheader("📋 Lista de Créditos en Seguimiento")
        st.dataframe(
            df_cartera[[
                "id",
                "nombre",
                "celular",
                "comercio",
                "valor_cuota",
                "saldo_pendiente",
                "Dias_Transcurridos",
                "Estado_Mora",
            ]],
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("---")
        st.subheader("📲 Gestión de Cobranza e Notificaciones SMS")

        mora_sel = st.selectbox(
            "Seleccione un Crédito para enviar Recordatorio de Pago",
            df_cartera["id"].tolist(),
        )
        fila_mora = df_cartera[df_cartera["id"] == mora_sel].iloc[0]

        v_cuota_mora = safe_float(fila_mora.get("valor_cuota"), 0.0)
        msg_recordatorio = (
            f"BankCali: Hola {fila_mora.get('nombre', '')}, le recordamos que su cuota de ${v_cuota_mora:,.0f} COP para el credito {fila_mora.get('id', '')} se encuentra proxima/vencida. Evite mora."
        )
        st.text_area("Vista previa del SMS de Recordatorio", msg_recordatorio, height=100)

        if st.button("📩 Enviar Recordatorio por SMS / WhatsApp"):
            exito_cob, _ = enviar_sms_twilio(
                fila_mora["celular"], mensaje_custom=msg_recordatorio
            )
            if exito_cob:
                st.success(
                    f"✅ Recordatorio enviado con éxito al número {fila_mora['celular']}."
                )

# =============================================================================
# MÓDULO 5: GESTIÓN GENERAL DE CLIENTES (SOLO ADMIN)
# =============================================================================
elif opcion == "5. Gestión General de Clientes" and es_admin:
    st.header("👥 Directorio y Gestión de Clientes Registrados")
    st.markdown("Consulta general, actualización de cupos y estado de cuenta.")
    st.markdown("---")

    try:
        df_clientes = conn.query("SELECT * FROM clientes", ttl=0)
        if not df_clientes.empty:
            st.dataframe(df_clientes, use_container_width=True, hide_index=True)
            st.caption(f"Total de clientes en base de datos: **{len(df_clientes)}**")
        else:
            st.info("No hay clientes registrados en la plataforma.")
    except Exception as e:
        st.error(f"Error al cargar clientes: {e}")

# =============================================================================
# MÓDULO 6: GESTIÓN DE ALMACENES ALIADOS (SOLO ADMIN)
# =============================================================================
elif opcion == "6. Gestión de Almacenes Aliados" and es_admin:
    st.header("🏪 Administración de Comercios Aliados")
    st.markdown("Gestión integral de tiendas, comisiones, logos y estado de convenios.")
    st.markdown("---")

    tab_listar, tab_agregar, tab_editar, tab_eliminar = st.tabs([
        "📋 Comercios Registrados",
        "➕ Agregar Comercio",
        "✏️ Modificar Comercio",
        "🗑️ Eliminar Comercio",
    ])

    with tab_listar:
        st.subheader("Tiendas Actualmente Aliadas")
        col_r, _ = st.columns([1, 4])
        with col_r:
            if st.button("🔄 Actualizar Tabla", key="refresh_comercios"):
                st.rerun()

        try:
            df_comercios_list = conn.query(
                "SELECT nombre, comision, logo_base64 FROM comercios", ttl=0
            )
            if not df_comercios_list.empty:
                df_comercios_list["Logo Cargado"] = df_comercios_list[
                    "logo_base64"
                ].apply(
                    lambda x: "✅ Sí"
                    if pd.notnull(x) and str(x).strip() != ""
                    else "❌ No"
                )
                st.dataframe(
                    df_comercios_list[["nombre", "comision", "Logo Cargado"]].rename(
                        columns={"nombre": "Nombre del Comercio", "comision": "Comisión (%)"}
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
                st.caption(f"Total de comercios aliados: **{len(df_comercios_list)}**")
            else:
                st.info("No hay comercios aliados registrados.")
        except Exception as e:
            st.error(f"Error al cargar comercios: {e}")

    with tab_agregar:
        st.subheader("➕ Registrar Nuevo Comercio Aliado")
        with st.form("form_nuevo_comercio", clear_on_submit=True):
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                nom_com = st.text_input("Nombre de la Tienda *")
                com_pct = st.number_input(
                    "Comisión (%) *", min_value=1.0, max_value=20.0, value=5.0, step=0.5
                )
            with col_c2:
                logo_file = st.file_uploader(
                    "🖼️ Logo del Comercio (Opcional)", type=["png", "jpg", "jpeg"], key="upload_add_logo"
                )

            btn_add_com = st.form_submit_button("💾 Registrar Comercio")

            if btn_add_com:
                if nom_com.strip():
                    logo_b64 = None
                    if logo_file is not None:
                        bytes_data = logo_file.read()
                        encoded_string = base64.b64encode(bytes_data).decode()
                        mime_type = logo_file.type
                        logo_b64 = f"data:{mime_type};base64,{encoded_string}"

                    try:
                        with conn.session as s:
                            s.execute(
                                text("""
                                    INSERT INTO comercios (nombre, comision, logo_base64) 
                                    VALUES (:n, :c, :l)
                                """),
                                {"n": nom_com.strip(), "c": com_pct, "l": logo_b64},
                            )
                            s.commit()
                        st.success(f"✅ Comercio **{nom_com}** registrado exitosamente.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al guardar comercio: {e}")
                else:
                    st.warning("⚠️ Escribe el nombre del comercio.")

    with tab_editar:
        st.subheader("✏️ Modificar Comercio Aliado")
        try:
            df_com_mod = conn.query("SELECT * FROM comercios", ttl=0)
            if df_com_mod.empty:
                st.info("No hay comercios disponibles para modificar.")
            else:
                lista_nombres = df_com_mod["nombre"].tolist()
                com_seleccionado = st.selectbox("Seleccione el Comercio a Modificar", lista_nombres)

                datos_com = df_com_mod[df_com_mod["nombre"] == com_seleccionado].iloc[0]

                with st.form("form_editar_comercio"):
                    col_m1, col_m2 = st.columns(2)
                    with col_m1:
                        e_nom_com = st.text_input("Nombre de la Tienda *", value=datos_com["nombre"])
                        e_com_pct = st.number_input(
                            "Comisión (%) *",
                            min_value=1.0,
                            max_value=20.0,
                            value=safe_float(datos_com.get("comision"), 5.0),
                            step=0.5,
                        )
                    with col_m2:
                        st.caption("🖼️ Logo Actual:")
                        if pd.notnull(datos_com.get("logo_base64")) and str(datos_com["logo_base64"]).strip() != "":
                            st.markdown(f'<img src="{datos_com["logo_base64"]}" style="max-height: 60px; margin-bottom: 10px;" />', unsafe_allow_html=True)
                        else:
                            st.info("Sin logo registrado.")

                        logo_file_edit = st.file_uploader(
                            "Actualizar Logo (Opcional - Deja vacío para conservar el actual)",
                            type=["png", "jpg", "jpeg"],
                            key="upload_edit_logo",
                        )

                    btn_edit_com = st.form_submit_button("💾 Actualizar Comercio")

                    if btn_edit_com:
                        if e_nom_com.strip():
                            logo_b64_updated = datos_com.get("logo_base64")
                            if logo_file_edit is not None:
                                bytes_data = logo_file_edit.read()
                                encoded_string = base64.b64encode(bytes_data).decode()
                                mime_type = logo_file_edit.type
                                logo_b64_updated = f"data:{mime_type};base64,{encoded_string}"

                            try:
                                with conn.session as s:
                                    s.execute(
                                        text("""
                                            UPDATE comercios 
                                            SET nombre = :new_n, comision = :c, logo_base64 = :l
                                            WHERE nombre = :old_n
                                        """),
                                        {
                                            "new_n": e_nom_com.strip(),
                                            "c": e_com_pct,
                                            "l": logo_b64_updated,
                                            "old_n": com_seleccionado,
                                        },
                                    )
                                    s.commit()
                                st.success(f"✅ Comercio **{e_nom_com}** actualizado correctamente.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error al actualizar el comercio: {e}")
                        else:
                            st.warning("⚠️ El nombre del comercio no puede estar vacío.")
        except Exception as e:
            st.error(f"Error al cargar datos para modificar: {e}")

    with tab_eliminar:
        st.subheader("🗑️ Eliminar Comercio Aliado")
        try:
            df_com_del = conn.query("SELECT nombre FROM comercios", ttl=0)
            if df_com_del.empty:
                st.info("No hay comercios registrados para eliminar.")
            else:
                com_a_eliminar = st.selectbox(
                    "Seleccione el Comercio que desea eliminar:", df_com_del["nombre"].tolist()
                )
                st.warning(
                    f"⚠️ **Atención:** Al eliminar el comercio **{com_a_eliminar}** ya no estará disponible para seleccionar en el punto de venta (POS)."
                )

                if st.button("🔥 Confirmar Eliminación de Comercio", use_container_width=True):
                    try:
                        with conn.session as s:
                            s.execute(
                                text("DELETE FROM comercios WHERE nombre = :n"),
                                {"n": com_a_eliminar},
                            )
                            s.commit()
                        st.success(f"✅ Comercio **{com_a_eliminar}** eliminado con éxito.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al eliminar comercio: {e}")
        except Exception as e:
            st.error(f"Error al consultar comercios a eliminar: {e}")

# =============================================================================
# MÓDULO 7: PANEL GENERAL DE ADMINISTRACIÓN (SOLO ADMIN)
# =============================================================================
elif opcion == "7. Panel General de Administración" and es_admin:
    st.header("📈 Dashboard de Métricas y Rendimiento Financiero")
    st.markdown("Visión estratégica del negocio en Puerto Rico (Caquetá).")
    st.markdown("---")

    try:
        df_solicitudes = conn.query(
            "SELECT id, fecha, comercio, cedula_cliente, monto_compra, cuotas, valor_cuota, total_pagar, saldo_pendiente, estado FROM solicitudes",
            ttl=0,
        )
        df_clientes_tot = conn.query("SELECT cupo_aprobado FROM clientes", ttl=0)

        total_colocado = (
            safe_float(df_solicitudes["monto_compra"].sum()) if not df_solicitudes.empty else 0.0
        )
        total_saldo = (
            safe_float(df_solicitudes["saldo_pendiente"].sum()) if not df_solicitudes.empty else 0.0
        )
        total_cupos = (
            safe_float(df_clientes_tot["cupo_aprobado"].sum()) if not df_clientes_tot.empty else 0.0
        )

        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric("Capital Colocado Total", f"${total_colocado:,.0f} COP")
        kpi2.metric("Saldo en Cartera Activa", f"${total_saldo:,.0f} COP")
        kpi3.metric("Cupos Aprobados Globales", f"${total_cupos:,.0f} COP")

        st.markdown("---")
        st.subheader("📊 Análisis Visual de Rendimiento y Riesgo")

        if not df_solicitudes.empty:
            if HAS_PLOTLY:
                col_graf1, col_graf2 = st.columns(2)

                with col_graf1:
                    st.markdown("##### 🛡️ Estado de Créditos (Riesgo / Morosidad)")
                    df_estado = (
                        df_solicitudes.groupby("estado")
                        .size()
                        .reset_index(name="cantidad")
                    )
                    fig_estado = px.pie(
                        df_estado,
                        values="cantidad",
                        names="estado",
                        hole=0.4,
                        color_discrete_sequence=px.colors.qualitative.Set2,
                    )
                    fig_estado.update_traces(
                        textposition="inside", textinfo="percent+label"
                    )
                    fig_estado.update_layout(
                        margin=dict(t=20, b=20, l=10, r=10), showlegend=True
                    )
                    st.plotly_chart(fig_estado, use_container_width=True)

                with col_graf2:
                    st.markdown("##### 🏪 Capital Colocado por Comercio Aliado")
                    df_comercio = (
                        df_solicitudes.groupby("comercio")["monto_compra"]
                        .sum()
                        .reset_index()
                    )
                    fig_comercio = px.bar(
                        df_comercio,
                        x="monto_compra",
                        y="comercio",
                        orientation="h",
                        text_auto=".2s",
                        labels={"monto_compra": "Monto ($ COP)", "comercio": "Comercio"},
                        color="monto_compra",
                        color_continuous_scale="Blues",
                    )
                    fig_comercio.update_layout(
                        xaxis_title="Monto Colocado ($ COP)",
                        yaxis_title="",
                        margin=dict(t=20, b=20, l=10, r=10),
                        coloraxis_showscale=False,
                    )
                    st.plotly_chart(fig_comercio, use_container_width=True)

                st.markdown("##### 💰 Estado de Cobro y Capital Recuperado")

                capital_total = safe_float(df_solicitudes["monto_compra"].sum())
                saldo_pendiente = safe_float(df_solicitudes["saldo_pendiente"].sum())
                capital_recuperado = max(0.0, capital_total - saldo_pendiente)

                df_balance = pd.DataFrame({
                    "Concepto": [
                        "Capital Recuperado / Cobrado",
                        "Saldo Pendiente por Cobrar",
                    ],
                    "Monto ($ COP)": [capital_recuperado, saldo_pendiente],
                })

                fig_balance = px.bar(
                    df_balance,
                    x="Concepto",
                    y="Monto ($ COP)",
                    color="Concepto",
                    text_auto=",.0f",
                    color_discrete_map={
                        "Capital Recuperado / Cobrado": "#2ecc71",
                        "Saldo Pendiente por Cobrar": "#e74c3c",
                    },
                )
                fig_balance.update_layout(
                    showlegend=False, margin=dict(t=20, b=20, l=10, r=10)
                )
                st.plotly_chart(fig_balance, use_container_width=True)
            else:
                col_g1, col_g2 = st.columns(2)

                with col_g1:
                    st.markdown("##### 🛡️ Resumen por Estado de Crédito")
                    df_est_native = df_solicitudes["estado"].value_counts().reset_index()
                    df_est_native.columns = ["Estado", "Cantidad de Créditos"]
                    st.dataframe(df_est_native, use_container_width=True, hide_index=True)

                with col_g2:
                    st.markdown("##### 🏪 Capital por Comercio Aliado")
                    df_com_native = (
                        df_solicitudes.groupby("comercio")["monto_compra"]
                        .sum()
                        .reset_index()
                    )
                    st.bar_chart(
                        df_com_native.set_index("comercio"), use_container_width=True
                    )

                st.markdown("##### 💰 Capital Recuperado vs. Pendiente por Cobrar")
                cap_tot = safe_float(df_solicitudes["monto_compra"].sum())
                sal_pend = safe_float(df_solicitudes["saldo_pendiente"].sum())
                cap_rec = max(0.0, cap_tot - sal_pend)

                df_bal_native = pd.DataFrame(
                    {"Monto ($ COP)": [cap_rec, sal_pend]},
                    index=["Capital Recuperado / Cobrado", "Saldo Pendiente por Cobrar"],
                )
                st.bar_chart(df_bal_native, use_container_width=True)

        else:
            st.info("No hay créditos registrados aún para generar gráficos.")

    except Exception as e:
        st.error(f"Error calculando indicadores o generando gráficas: {e}")

# =============================================================================
# MÓDULO 8: GESTIÓN DE USUARIOS Y PARÁMETROS (EXCLUSIVO ADMINISTRADOR)
# =============================================================================
elif opcion == "8. Gestión de Usuarios y Parámetros":

    if not es_admin:
        st.error(
            "⛔ **Acceso Restringido:** Este módulo contiene parámetros del sistema y solo está disponible para usuarios con rol de **Administrador / Fundador**."
        )
    else:
        st.header("👥 Administración de Usuarios y Parámetros del Sistema")
        st.caption("Módulo Exclusivo Administrativo • Control de Cuentas y Reglas Centralizadas")
        st.markdown("---")

        tab_listar, tab_agregar, tab_editar, tab_param, tab_eliminar = st.tabs([
            "📋 Usuarios Registrados",
            "➕ Agregar Usuario",
            "✏️ Modificar Usuario",
            "⚙️ Parámetros en Supabase",
            "🗑️ Eliminar Usuario",
        ])

        with tab_listar:
            st.subheader("Lista de Cuentas Autorizadas")

            col_r, _ = st.columns([1, 4])
            with col_r:
                if st.button("🔄 Actualizar Tabla"):
                    st.rerun()

            try:
                df_usuarios = conn.query(
                    "SELECT documento, nombre, rol, comercio_asignado FROM usuarios",
                    ttl=0,
                )

                if not df_usuarios.empty:
                    df_usuarios = df_usuarios.rename(
                        columns={
                            "documento": "Documento / Cédula",
                            "nombre": "Nombre Completo",
                            "rol": "Rol de Acceso",
                            "comercio_asignado": "Comercio Asignado",
                        }
                    )
                    st.dataframe(df_usuarios, use_container_width=True, hide_index=True)
                    st.caption(f"Total de cuentas en el sistema: **{len(df_usuarios)}**")
                else:
                    st.info("No hay usuarios registrados en la base de datos.")
            except Exception as e:
                st.error(f"⚠️ Error al consultar usuarios: {e}")

        with tab_agregar:
            st.subheader("Crear Cuenta de Usuario")

            try:
                df_com_opt = conn.query("SELECT nombre FROM comercios", ttl=0)
                lista_comercios = (
                    ["N/A - Administrador"] + df_com_opt["nombre"].tolist()
                    if not df_com_opt.empty
                    else ["N/A - Administrador"]
                )
            except Exception:
                lista_comercios = ["N/A - Administrador"]

            with st.form("form_nuevo_usuario_m8", clear_on_submit=True):
                col_u1, col_u2 = st.columns(2)

                with col_u1:
                    u_doc = st.text_input("Documento de Identidad *")
                    u_nom = st.text_input("Nombre Completo *")
                    u_com = st.selectbox("Asignar a Comercio Aliado", lista_comercios)

                with col_u2:
                    u_rol = st.selectbox(
                        "Rol del Usuario *",
                        ["Cliente", "Comercio Aliado", "Administrador", "FUNDADOR (Administrador)"],
                    )
                    u_pin = st.text_input(
                        "PIN de Acceso (Numérico) *",
                        type="password",
                        max_chars=6,
                        help="Máximo 6 números",
                    )

                btn_crear_u = st.form_submit_button("💾 Guardar Usuario")

                if btn_crear_u:
                    if not u_doc.strip() or not u_nom.strip() or not u_pin.strip():
                        st.warning("⚠️ Completa los campos obligatorios.")
                    else:
                        try:
                            with conn.session as s:
                                s.execute(
                                    text("""
                                        INSERT INTO usuarios (documento, nombre, rol, pin, comercio_asignado)
                                        VALUES (:doc, :nom, :rol, :pin, :com)
                                    """),
                                    {
                                        "doc": u_doc.strip(),
                                        "nom": u_nom.strip(),
                                        "rol": u_rol,
                                        "pin": u_pin.strip(),
                                        "com": u_com,
                                    },
                                )
                                s.commit()
                            st.success(f"✅ Usuario **{u_nom}** creado exitosamente.")
                            st.rerun()
                        except IntegrityError:
                            st.error("❌ Ya existe un usuario registrado con ese documento.")
                        except Exception as e:
                            st.error(f"Error al guardar usuario: {e}")

        with tab_editar:
            st.subheader("✏️ Modificar Datos de Usuario")

            try:
                df_edit_u = conn.query("SELECT documento, nombre FROM usuarios", ttl=0)
                if df_edit_u.empty:
                    st.info("No hay usuarios disponibles para editar.")
                else:
                    opciones_u = [f"{row['documento']} - {row['nombre']}" for _, row in df_edit_u.iterrows()]
                    u_seleccionado = st.selectbox("Seleccione el Usuario a Modificar", opciones_u)
                    doc_edit = u_seleccionado.split(" - ")[0]

                    df_curr = conn.query(
                        "SELECT * FROM usuarios WHERE documento = :doc",
                        params={"doc": doc_edit},
                        ttl=0,
                    )

                    if not df_curr.empty:
                        curr_data = df_curr.iloc[0].to_dict()

                        df_com_opt = conn.query("SELECT nombre FROM comercios", ttl=0)
                        lista_comercios = (
                            ["N/A - Administrador"] + df_com_opt["nombre"].tolist()
                            if not df_com_opt.empty
                            else ["N/A - Administrador"]
                        )

                        idx_com = (
                            lista_comercios.index(curr_data["comercio_asignado"])
                            if curr_data.get("comercio_asignado") in lista_comercios
                            else 0
                        )

                        roles_disponibles = ["Cliente", "Comercio Aliado", "Administrador", "FUNDADOR (Administrador)"]
                        idx_rol = (
                            roles_disponibles.index(curr_data["rol"])
                            if curr_data.get("rol") in roles_disponibles
                            else 0
                        )

                        with st.form("form_editar_usuario_m8"):
                            col_e1, col_e2 = st.columns(2)

                            with col_e1:
                                e_nom = st.text_input("Nombre Completo *", value=curr_data.get("nombre", ""))
                                e_com = st.selectbox("Asignar a Comercio Aliado", lista_comercios, index=idx_com)

                            with col_e2:
                                e_rol = st.selectbox("Rol del Usuario *", roles_disponibles, index=idx_rol)
                                e_pin = st.text_input(
                                    "PIN de Acceso (Numérico) *",
                                    type="password",
                                    value=curr_data.get("pin", ""),
                                    max_chars=6,
                                )

                            btn_actualizar = st.form_submit_button("💾 Actualizar Usuario")

                            if btn_actualizar:
                                if not e_nom.strip() or not e_pin.strip():
                                    st.warning("⚠️ Completa todos los campos obligatorios.")
                                else:
                                    try:
                                        with conn.session as s:
                                            s.execute(
                                                text("""
                                                    UPDATE usuarios 
                                                    SET nombre = :nom, rol = :rol, pin = :pin, comercio_asignado = :com
                                                    WHERE documento = :doc
                                                """),
                                                {
                                                    "nom": e_nom.strip(),
                                                    "rol": e_rol,
                                                    "pin": e_pin.strip(),
                                                    "com": e_com,
                                                    "doc": doc_edit,
                                                },
                                            )
                                            s.commit()
                                        st.success(f"✅ Usuario **{e_nom}** actualizado correctamente.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error al actualizar usuario: {e}")
            except Exception as e:
                st.error(f"Error al cargar información para edición: {e}")

        with tab_param:
            st.subheader("⚙️ Configuración Global de Tasas y Parámetros")
            st.caption("Cualquier cambio realizado aquí se aplicará inmediatamente a la Web y a la Aplicación Móvil.")

            tasa_db, aval_db, monto_min_db = obtener_parametros()

            col_p1, col_p2 = st.columns(2)
            with col_p1:
                n_tasa = st.number_input(
                    "Tasa de Interés Mensual Base (%)",
                    value=round(tasa_db * 100, 2),
                    step=0.1,
                    format="%.2f",
                )
                n_aval = st.number_input(
                    "Tarifa de Aval / Garantía (%)",
                    value=round(aval_db * 100, 2),
                    step=0.5,
                    format="%.1f",
                )
                n_monto = st.number_input(
                    "Monto Mínimo de Compra POS ($ COP)",
                    value=monto_min_db,
                    step=10000,
                )

            with col_p2:
                st.text_input("Municipio Base de Operaciones", value="Puerto Rico")
                st.text_input("Departamento", value="Caquetá")
                st.number_input("Días de Corte Quincenal", value=15, step=1)

            if st.button("💾 Guardar Parámetros en Supabase", use_container_width=True):
                try:
                    with conn.session as s:
                        s.execute(
                            text("""
                                UPDATE parametros 
                                SET tasa_interes = :t, pct_aval = :a, monto_minimo = :m 
                                WHERE id = 1
                            """),
                            {"t": n_tasa, "a": n_aval, "m": n_monto},
                        )
                        s.commit()
                    st.success("✅ Parámetros del sistema actualizados correctamente en Supabase.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al actualizar parámetros: {e}")

        with tab_eliminar:
            st.subheader("🗑️ Eliminar Usuario")
            doc_elim = st.text_input(
                "Documento del usuario que deseas eliminar de la plataforma:"
            )

            if st.button("🔥 Confirmar Eliminación"):
                if doc_elim.strip():
                    try:
                        with conn.session as s:
                            s.execute(
                                text("DELETE FROM usuarios WHERE documento = :doc"),
                                {"doc": doc_elim.strip()},
                            )
                            s.commit()
                        st.success("✅ Usuario eliminado exitosamente.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al eliminar usuario: {e}")
                else:
                    st.warning("Por favor ingresa un número de documento válido.")
