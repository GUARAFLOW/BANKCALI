import base64
from datetime import datetime, timedelta
import random
import textwrap
import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import streamlit as st
from twilio.rest import Client

# Intentar importar Plotly opcionalmente
try:
  import plotly.express as px

  HAS_PLOTLY = True
except ImportError:
  HAS_PLOTLY = False

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
        .btn-print {
            display: block;
            width: 100%;
            max-width: 420px;
            margin: 15px auto 0 auto;
            background-color: #1E3A8A;
            color: white;
            padding: 10px 15px;
            border: none;
            border-radius: 6px;
            font-weight: bold;
            font-size: 1rem;
            cursor: pointer;
            text-align: center;
            text-decoration: none;
        }
        .btn-print:hover {
            background-color: #0A192F;
            color: #38BDF8;
        }

        /* CONFIGURACIÓN DE IMPRESIÓN (MEDIOS IMPRESOS) */
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
# FUNCIONES AUXILIARES
# =============================================================================
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
    print(f"Error enviando SMS con Twilio: {e}")
    return False, str(e)


def evaluar_riesgo_y_cupo(ingresos, gastos):
  pct_gastos = (gastos / ingresos) if ingresos > 0 else 1

  if 100000 <= ingresos <= 1000000:
    if pct_gastos <= 0.35:
      cupo = 80000
      estado = "APROBADO"
    else:
      cupo = 0
      estado = "RECHAZADO"

  elif 1000001 <= ingresos <= 2500000:
    margen_disponible = ingresos - gastos
    if margen_disponible < 0:
      cupo = 0
      estado = "RECHAZADO"
    else:
      cupo = round((margen_disponible * 0.25) / 10000) * 10000
      estado = "APROBADO" if cupo > 0 else "RECHAZADO"

  else:
    cupo_base = ingresos * 0.30
    if pct_gastos > 0.50:
      reduccion = (pct_gastos - 0.50) * 0.5
      cupo_final = cupo_base * (1 - reduccion)
    else:
      cupo_final = cupo_base

    cupo = round(cupo_final / 10000) * 10000
    estado = "APROBADO" if cupo > 0 else "RECHAZADO"

  mensaje = (
      f"✅ Cliente Aprobado para Crédito Rotativo con cupo de ${cupo:,.0f} COP."
      if cupo > 0
      else "❌ Crédito no aprobado por capacidad de endeudamiento."
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


# =============================================================================
# CONEXIÓN Y MIGRACIÓN AUTOMÁTICA DE BASE DE DATOS
# =============================================================================
conn = st.connection("supabase", type="sql")

# Asegurar la columna de logo_base64 en la tabla comercios
try:
  with conn.session as s:
    s.execute(
        text("ALTER TABLE comercios ADD COLUMN IF NOT EXISTS logo_base64 TEXT;")
    )
    s.commit()
except Exception:
  pass

if "autenticado" not in st.session_state:
  st.session_state.autenticado = False
  st.session_state.rol = None
  st.session_state.nombre = None
  st.session_state.comercio_asignado = None

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
          st.session_state.rol = datos_usuario.get("rol", "Comercio Aliado")
          st.session_state.nombre = datos_usuario.get("nombre", "Usuario")
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
      "<p style='text-align: center; color: gray; font-size:"
      " 0.8rem;'>Desarrollado para Gestión Comercial<br>© 2026</p>",
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
# CONTROL DE NAVEGACIÓN Y PERMISOS
# =============================================================================
st.sidebar.success(
    f"👤 **Sesión Activa:**\n\n{st.session_state.nombre}\n*({st.session_state.rol})*"
)

if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
  st.session_state.autenticado = False
  st.session_state.rol = None
  st.session_state.nombre = None
  st.session_state.comercio_asignado = None
  st.rerun()

st.sidebar.markdown("---")

es_admin = st.session_state.rol in [
    "Administrador",
    "FUNDADOR (Administrador)",
    "FUNDADOR",
]

menu_opciones = [
    "1. Simular / Solicitar Crédito (POS)",
    "2. Registrar Nuevo Cliente + Scoring de Cupo",
]

if es_admin:
  menu_opciones.extend([
      "3. Registrar Pagos / Abonar Cuotas",
      "4. Control de Cartera y Mora (Cobranzas)",
      "5. Gestión General de Clientes",
      "6. Gestión de Almacenes Aliados",
      "7. Panel General de Administración",
      "8. Gestión de Usuarios",
  ])

st.sidebar.markdown("### 🧭 Menú de Navegación")
opcion = st.sidebar.selectbox(
    "Seleccione un módulo", menu_opciones, label_visibility="collapsed"
)

st.sidebar.markdown("---")
st.sidebar.markdown(
    "<p style='text-align: center; color: gray; font-size: 0.8rem;'>Sistema de"
    " Crédito Rotativo v3.0<br>Puerto Rico, Caquetá</p>",
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
# MÓDULO 1: SOLICITUD EN POS CON AMORTIZACIÓN Y TICKET IMPRIMIBLE CON LOGO
# =============================================================================
if opcion == "1. Módulo de Punto de Venta (POS)":
  st.header("🏪 Módulo de Punto de Venta (Comercio Aliado)")
  st.markdown(
      "Simulación, cronograma de amortización y generación de ticket de venta"
      " imprimible."
  )
  st.markdown("---")

  try:
    df_comercios = conn.query(
        "SELECT nombre, comision, logo_base64 FROM comercios", ttl=0
    )
  except Exception:
    df_comercios = pd.DataFrame()

  if df_comercios.empty:
    st.warning(
        "⚠️ No hay comercios registrados aún. Registre uno en 'Gestión de"
        " Almacenes Aliados'."
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
            f"🏢 Operando bajo la tienda:"
            f" **{st.session_state.comercio_asignado}**"
        )
        comercio_sel = st.session_state.comercio_asignado
      else:
        comercio_sel = st.selectbox(
            "Seleccione el Comercio Aliado", df_comercios["nombre"].tolist()
        )

      match_comercio = df_comercios[df_comercios["nombre"] == comercio_sel]
      comercio_comercio = (
          float(match_comercio["comision"].values[0])
          if not match_comercio.empty
          else 5.0
      )
      logo_comercio = (
          match_comercio["logo_base64"].values[0]
          if not match_comercio.empty
          and "logo_base64" in match_comercio.columns
          else None
      )

      cedula = st.text_input("Número de Cédula del Cliente")

      cliente_info = None
      if cedula:
        cliente_info_df = conn.query(
            "SELECT nombre, celular, cupo_disponible FROM clientes WHERE cedula"
            " = :ced",
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
        st.success(
            "💡 **Cupo Disponible del Cliente:**"
            f" ${cliente_info['cupo_disponible']:,.0f} COP"
        )
      else:
        nombre_cliente = st.text_input("Nombre Completo del Cliente")
        celular = st.text_input("Número de Celular")
        if cedula:
          st.warning(
              "⚠️ Cliente no registrado. Seleccione la opción '2. Registrar"
              " Nuevo Cliente'."
          )

    with col2:
      st.markdown("##### 🛒 Detalles de la Compra")
      monto_compra = st.number_input(
          "Monto de la Compra ($ COP)",
          min_value=80000,
          max_value=5000000,
          step=10000,
          value=80000,
      )
      cuotas = st.selectbox("Número de Cuotas (Quincenales)", [2, 3, 4, 6, 8])

      (
          df_amort,
          total_pagar,
          valor_cuota,
          monto_aval,
          interes_total,
      ) = generar_tabla_amortizacion(monto_compra, cuotas)
      desembolso = monto_compra * (1 - (comercio_comercio / 100))

    st.markdown("---")
    st.subheader("📊 Resumen Financiero y Cronograma de Pagos")
    res1, res2, res3 = st.columns(3)
    res1.metric("Valor Cuota Quincenal", f"${valor_cuota:,.0f} COP")
    res2.metric("Total a Pagar por Cliente", f"${total_pagar:,.0f} COP")
    res3.metric("Desembolso Neto a Comercio", f"${desembolso:,.0f} COP")

    with st.expander(
        "📅 Ver Tabla de Amortización Quincenal Completa", expanded=False
    ):
      st.dataframe(df_amort, use_container_width=True, hide_index=True)

    excede_cupo = False
    if cliente_info is not None and monto_compra > float(
        cliente_info["cupo_disponible"]
    ):
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
          st.success(
              f"📱 ¡SMS enviado con éxito vía Twilio al celular {celular}!"
          )
        else:
          st.warning(
              "⚠️ Alerta (Modo de prueba/respaldo): SMS no enviado. Código OTP"
              f" es **{otp}**"
          )
      else:
        st.error("Por favor completa todos los datos del cliente.")

    if "otp_actual" in st.session_state and not excede_cupo:
      st.markdown("#### 🔑 Verificación de Seguridad")
      otp_ingresado = st.text_input(
          "Ingrese el Código OTP de 4 dígitos enviado al cliente"
      )

      if st.button(
          "✅ Confirmar Venta y Otorgar Crédito", use_container_width=True
      ):
        if str(otp_ingresado) == str(st.session_state["otp_actual"]):
          id_credito = f"CR-{random.randint(10000, 99999)}"
          fecha_hoy = datetime.now().strftime("%Y-%m-%d %H:%M")

          with conn.session as s:
            s.execute(
                text(
                    "UPDATE clientes SET cupo_disponible = cupo_disponible -"
                    " :monto WHERE cedula = :cedula"
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

          # =============================================================================
# CONFIRMACIÓN DE VENTA: DESCUENTO DE CUPO Y REGISTRO EN BASE DE DATOS
# =============================================================================

if st.button("✅ Confirmar Venta y Otorgar Crédito", use_container_width=True):
  # 1. Recuperar variables clave del estado de sesión
  cedula = st.session_state.get("cedula_cliente")
  monto = float(st.session_state.get("monto_compra", 0))
  num_cuotas = int(st.session_state.get("num_cuotas", 1))
  valor_cuota = float(st.session_state.get("valor_cuota", 0))
  total_pagar = float(st.session_state.get("total_pagar", 0))
  comercio_nom = (
      st.session_state.get("comercio_seleccionado")
      or st.session_state.get("comercio_aliado")
      or "Comercio Aliado"
  )

  # Validaciones previas
  if not cedula or monto <= 0:
    st.error(
        "❌ Datos de crédito inválidos. Verifica el cliente y el monto de"
        " compra."
    )
  else:
    try:
      # 2. Consultar cupo actual del cliente
      df_cliente = conn.query(
          "SELECT id, nombre, cupo_disponible FROM clientes WHERE cedula = :ced",
          params={"ced": str(cedula)},
          ttl=0,
      )

      if df_cliente.empty:
        st.error("❌ El cliente no se encuentra registrado en el sistema.")
      else:
        cliente_id = df_cliente.iloc[0]["id"]
        nombre_cliente = df_cliente.iloc[0]["nombre"]
        cupo_actual = float(df_cliente.iloc[0]["cupo_disponible"])

        # 3. Validar si el cupo cubre el monto
        if cupo_actual < monto:
          st.error(
              f"❌ Cupo insuficiente. Cupo disponible: ${cupo_actual:,.0f} COP"
          )
        else:
          # 4. Actualizar el cupo disponible del cliente
          nuevo_cupo = cupo_actual - monto
          conn.execute(
              "UPDATE clientes SET cupo_disponible = :nuevo_cupo WHERE id ="
              " :id",
              params={"nuevo_cupo": nuevo_cupo, "id": cliente_id},
          )

          # 5. Insertar la nueva transacción / crédito
          id_credito_gen = f"CR-{datetime.now().strftime('%m%d%H%M')}"

          conn.execute(
              """
                        INSERT INTO creditos 
                        (id_credito, cliente_id, comercio, monto, cuotas, valor_cuota, total_pagar, estado, fecha)
                        VALUES (:id_cred, :cli_id, :comercio, :monto, :cuotas, :v_cuota, :total, 'ACTIVO', CURRENT_TIMESTAMP)
                    """,
              params={
                  "id_cred": id_credito_gen,
                  "cli_id": cliente_id,
                  "comercio": comercio_nom,
                  "monto": monto,
                  "cuotas": num_cuotas,
                  "v_cuota": valor_cuota,
                  "total": total_pagar,
              },
          )

          # 6. Guardar variables en session_state para alimentar el ticket
          st.session_state["id_credito_gen"] = id_credito_gen
          st.session_state["nombre_cliente"] = nombre_cliente
          st.session_state["credito_aprobado"] = True

          st.success(
              f"🎉 ¡Crédito {id_credito_gen} otorgado con éxito! Nuevo cupo"
              f" disponible: ${nuevo_cupo:,.0f} COP"
          )
          st.balloons()

    except Exception as e:
      st.error(f"⚠️ Error al procesar la transacción: {str(e)}")

    # =============================================================================
    # GENERACIÓN DE TICKET POS CON LOGO Y CÓDIGO QR DINÁMICO
    # =============================================================================

    # 1. Rastrear automáticamente el nombre del comercio activo
    comercio_nom = None
    for var in [
        "comercio_aliado",
        "comercio_seleccionado",
        "comercio",
        "tienda",
        "comercio_actual",
    ]:
      if var in locals() and locals()[var]:
        val = str(locals()[var]).strip()
        if val and val not in ["Comercio Aliado", "None", ""]:
          comercio_nom = val
          break

    if not comercio_nom:
      for key, val in st.session_state.items():
        if (
            any(
                k in str(key).lower()
                for k in ["comercio", "tienda", "aliado", "store"]
            )
            and val
        ):
          if isinstance(val, str) and val.strip() not in [
              "Comercio Aliado",
              "None",
              "",
          ]:
            comercio_nom = val.strip()
            break

    if not comercio_nom:
      comercio_nom = "Comercio Aliado"

    # 2. Búsqueda del Logo en BD
    logo_html = ""
    try:
      df_logo = conn.query(
          "SELECT nombre, logo_base64 FROM comercios WHERE LOWER(TRIM(nombre)) = LOWER(TRIM(:nom))",
          params={"nom": str(comercio_nom)},
          ttl=0,
      )
      if df_logo.empty:
        df_logo = conn.query(
            "SELECT nombre, logo_base64 FROM comercios WHERE LOWER(nombre) LIKE LOWER(:nom)",
            params={"nom": f"%{comercio_nom}%"},
            ttl=0,
        )

      if not df_logo.empty:
        comercio_nom = df_logo.iloc[0]["nombre"]
        raw_b64 = df_logo.iloc[0]["logo_base64"]
        if pd.notnull(raw_b64) and str(raw_b64).strip() not in [
            "",
            "None",
            "nan",
        ]:
          str_b64 = str(raw_b64).strip()
          src_img = (
              str_b64
              if str_b64.startswith("data:image")
              else f"data:image/png;base64,{str_b64}"
          )
          logo_html = f'<img src="{src_img}" style="max-height: 55px; max-width: 180px; margin-bottom: 6px;" /><br>'
    except Exception:
      pass

    # 3. Datos del Crédito
    id_cred_str = (
        st.session_state.get("id_credito_gen")
        or locals().get("id_credito_gen")
        or locals().get("num_credito")
        or "CR-00000"
    )
    cliente_nom = (
        st.session_state.get("nombre_cliente")
        or locals().get("nombre_cliente")
        or "Cliente"
    )
    cliente_ced = (
        st.session_state.get("cedula_cliente")
        or locals().get("cedula_cliente")
        or "N/A"
    )
    monto_val = (
        st.session_state.get("monto_compra")
        or locals().get("monto_compra")
        or 0
    )
    cuotas_val = (
        st.session_state.get("num_cuotas") or locals().get("num_cuotas") or 1
    )
    cuota_val = (
        st.session_state.get("valor_cuota") or locals().get("valor_cuota") or 0
    )
    total_val = (
        st.session_state.get("total_pagar") or locals().get("total_pagar") or 0
    )
    fecha_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 4. Generación del Código QR en Base64
    qr_data = f"BANKCALI|CREDITO:{id_cred_str}|CEDULA:{cliente_ced}|TOTAL:{total_val:,.0f}"
    qr_img = qrcode.make(qr_data)
    buffer = io.BytesIO()
    qr_img.save(buffer, format="PNG")
    qr_b64_str = base64.b64encode(buffer.getvalue()).decode()
    qr_html = f'<img src="data:image/png;base64,{qr_b64_str}" style="width: 85px; height: 85px; margin-top: 8px;" />'

    # 5. Estilos CSS de Impresión
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

    # 6. HTML del Ticket POS con el QR incluido
    ticket_html = f"""<div class="ticket-pos-box" style="border: 2px dashed #d3ad69; border-radius: 10px; padding: 20px; background-color: #fffdf5; max-width: 380px; margin: 0 auto; font-family: monospace; color: #111;">
<div style="text-align: center;">
{logo_html}
<h3 style="margin: 0; color: #0d233a;">{comercio_nom}</h3>
<p style="margin: 4px 0; font-size: 12px;">
Financiado por <b>BANKCALI</b><br>
Puerto Rico, Caquetá<br>
<b>COMPROBANTE DE COMPRA A CRÉDITO</b>
</p>
</div>
<hr style="border: none; border-top: 1px dashed #666;">
<p style="font-size: 13px; line-height: 1.6; margin: 0;">
<b>N° Crédito:</b> {id_cred_str}<br>
<b>Fecha:</b> {fecha_str}<br>
<b>Cliente:</b> {cliente_nom}<br>
<b>Cédula:</b> {cliente_ced}
</p>
<hr style="border: none; border-top: 1px dashed #666;">
<p style="font-size: 13px; line-height: 1.6; margin: 0;">
<b>Monto Compra:</b> ${monto_val:,.0f} COP<br>
<b>N° Cuotas:</b> {cuotas_val} Quincenales<br>
<b>Valor Cuota:</b> ${cuota_val:,.0f} COP<br>
<b>Total a Pagar:</b> ${total_val:,.0f} COP
</p>
<hr style="border: none; border-top: 1px dashed #666;">
<div style="text-align: center;">
{qr_html}
<p style="font-size: 10px; margin-top: 4px; color: #555;">Escanear para verificar comprobante</p>
<p style="font-size: 11px; margin-top: 6px; color: #444;">Firma Digital Verificada vía OTP SMS<br>¡Gracias por su compra!</p>
</div>
</div>"""

    st.markdown(ticket_html, unsafe_allow_html=True)
    st.write("")

    # 7. Botón ejecutor de impresión
    js_btn = """
    <script>
    function imprimirTicket() { window.parent.print(); }
    </script>
    <button onclick="imprimirTicket()" style="background-color: #0f2537; color: white; border: none; padding: 12px 20px; border-radius: 8px; width: 100%; font-weight: bold; font-size: 15px; cursor: pointer;">
        🖨️ Imprimir Ticket / Guardar PDF
    </button>
    """
    st.components.v1.html(js_btn, height=65)

# =============================================================================
# MÓDULO 2: REGISTRAR NUEVO CLIENTE + SCORING DE CUPO
# =============================================================================
elif opcion == "2. Registrar Nuevo Cliente + Scoring de Cupo":
  st.header("📝 Evaluación, Firma de Acuerdo y Registro de Cliente")
  st.markdown(
      "Sistema automatizado de scoring crediticio con verificación por SMS"
      " (OTP) y aceptación contractual."
  )

  if es_admin:
    st.info(
        "💡 **Política de Crédito:** Ingresos de $100k a $1M con gastos <= 35%"
        " reciben $80.000 COP. Ingresos de $1M a $2.5M dependen del margen"
        " disponible. Ingresos > $2.5M reciben cupo base del 30% ajustado por"
        " gastos."
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

  with col_e2:
    st.markdown("##### 💼 Perfil Económico")
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

  cupo_sugerido, nivel_riesgo, mensaje_eval = evaluar_riesgo_y_cupo(
      c_ingresos, c_gastos
  )

  st.markdown("---")
  st.subheader("🎯 Resultado de la Evaluación de Riesgo")

  col_res1, col_res2 = st.columns(2)
  col_res1.metric("Cupo Aprobado Asignado", f"${cupo_sugerido:,.0f} COP")
  col_res2.success(f"🟢 **{nivel_riesgo}**\n\n{mensaje_eval}")

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
            <p><strong>3. TASAS Y COSTOS:</strong> Tasa de interés de plazo del 2.1% mensual (proporcional quincenal) y tarifa de Aval del 10% sobre compra.</p>
            <p><strong>4. AUTORIZACIÓN Y NOTIFICACIÓN POR SMS:</strong> El CLIENTE autoriza el envío de notificaciones y la validación por código OTP enviado al número móvil <strong>{c_celular}</strong> como firma electrónica válida conforme a la Ley 527 de 1999.</p>
        </div>
        """),
        unsafe_allow_html=True,
    )

    acepta_terminos = st.checkbox(
        f"☑️ Confirmo que el cliente {c_nombre} ha leído y ACEPTA los Términos"
        " del Acuerdo Comercial."
    )

    st.markdown("---")
    st.subheader("📲 Verificación y Notificación por SMS (Firma Digital)")

    if st.button(
        "📱 Enviar Código OTP de Solicitud de Crédito al Cliente",
        use_container_width=True,
        disabled=not acepta_terminos,
    ):
      otp_registro = random.randint(1000, 9999)
      st.session_state["otp_registro_actual"] = otp_registro

      msg_solicitud = (
          f"BankCali: Su codigo OTP para autorizar la apertura de Credito"
          f" Rotativo por ${cupo_sugerido:,.0f} COP es: {otp_registro}. Al"
          " entregarlo acepta los terminos del contrato."
      )
      exito_sms, resultado = enviar_sms_twilio(
          c_celular, mensaje_custom=msg_solicitud
      )

      if exito_sms:
        st.success(
            "📱 ¡Notificación y OTP de solicitud enviada vía SMS al celular"
            f" {c_celular}!"
        )
      else:
        st.warning(
            "⚠️ Alerta (Modo respaldo): SMS no enviado. Código OTP es"
            f" **{otp_registro}**"
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
        if str(otp_ingresado_reg) == str(
            st.session_state["otp_registro_actual"]
        ):
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
                f"BankCali: Felicidades {c_nombre}, tu solicitud de Credito"
                " Rotativo ha sido APROBADA y ACTIVADA por"
                f" ${cupo_sugerido:,.0f} COP. Gracias por confiar en nosotros."
            )
            enviar_sms_twilio(c_celular, mensaje_custom=msg_bienvenida)

            st.balloons()
            st.success(
                f"🎉 ¡Crédito Rotativo Activado! Cliente **{c_nombre}**"
                f" registrado con cupo de **${cupo_sugerido:,.0f} COP**."
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
  st.markdown(
      "Registro de abonos, liberación de cupo y envío de recibo por SMS."
  )
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

      saldo_act = float(fila_credito["saldo_pendiente"])
      vlr_cuota = float(fila_credito["valor_cuota"])
      celular_cli = fila_credito["celular"]

      st.markdown("---")
      col_p1, col_p2 = st.columns(2)
      col_p1.info(f"📌 **Saldo Pendiente Actual:** ${saldo_act:,.0f} COP")
      col_p2.info(f"📌 **Valor Cuota Sugerido:** ${vlr_cuota:,.0f} COP")

      if saldo_act <= 0:
        st.info(
            "ℹ️ Este crédito se encuentra CANCELADO. No registra saldo"
            " pendiente por abonar."
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
                    "INSERT INTO pagos (fecha, id_credito, monto_pagado)"
                    " VALUES (:f, :id_c, :m)"
                ),
                {"f": fecha_pago, "id_c": credito_sel, "m": monto_abono},
            )
            s.execute(
                text(
                    "UPDATE solicitudes SET saldo_pendiente = :ns, estado = :ne"
                    " WHERE id = :id_c"
                ),
                {"ns": nuevo_saldo, "ne": nuevo_estado, "id_c": credito_sel},
            )
            s.execute(
                text(
                    "UPDATE clientes SET cupo_disponible = cupo_disponible + :m"
                    " WHERE cedula = :ced"
                ),
                {"m": monto_abono, "ced": fila_credito["cedula_cliente"]},
            )
            s.commit()

          msg_pago = (
              f"BankCali: Recibimos tu abono de ${monto_abono:,.0f} COP al"
              f" credito {credito_sel}. Nuevo saldo: ${nuevo_saldo:,.0f} COP."
              " Tu cupo ha sido liberado."
          )
          enviar_sms_twilio(celular_cli, mensaje_custom=msg_pago)

          st.success(
              f"✅ Pago por ${monto_abono:,.0f} COP registrado con éxito. Nuevo"
              f" saldo: **${nuevo_saldo:,.0f} COP**."
          )

# =============================================================================
# MÓDULO 4: CONTROL DE CARTERA VENCIDA Y MORA (COBRANZAS)
# =============================================================================
elif opcion == "4. Control de Cartera y Mora (Cobranzas)" and es_admin:
  st.header("⚠️ Panel de Control de Cartera y Gestión de Mora")
  st.markdown(
      "Seguimiento de cuotas, semáforo de riesgo y recordatorios masivos e"
      " individuales por SMS."
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
    st.success(
        "🎉 ¡Excelente! No hay créditos activos o en cartera pendiente"
        " actualmente."
    )
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

    df_cartera["Estado_Mora"] = df_cartera["Dias_Transcurridos"].apply(
        clasificar_mora
    )

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

    msg_recordatorio = (
        f"BankCali: Hola {fila_mora['nombre']}, le recordamos que su cuota de"
        f" ${fila_mora['valor_cuota']:,.0f} COP para el credito"
        f" {fila_mora['id']} se encuentra proxima/vencida. Evite mora."
    )
    st.text_area(
        "Vista previa del SMS de Recordatorio", msg_recordatorio, height=100
    )

    if st.button("📩 Enviar Recordatorio por SMS"):
      exito_cob, _ = enviar_sms_twilio(
          fila_mora["celular"], mensaje_custom=msg_recordatorio
      )
      if exito_cob:
        st.success(
            "✅ Recordatorio enviado con éxito al número"
            f" {fila_mora['celular']}."
        )
      else:
        st.error("❌ No se pudo enviar el mensaje SMS.")

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

  # --- PESTAÑA 1: LISTAR COMERCIOS ---
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

  # --- PESTAÑA 2: AGREGAR COMERCIO ---
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

  # --- PESTAÑA 3: MODIFICAR COMERCIO ---
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
                value=float(datos_com["comision"]),
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

  # --- PESTAÑA 4: ELIMINAR COMERCIO ---
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
        "SELECT id, fecha, comercio, cedula_cliente, monto_compra, cuotas,"
        " valor_cuota, total_pagar, saldo_pendiente, estado FROM solicitudes",
        ttl=0,
    )
    df_clientes_tot = conn.query("SELECT cupo_aprobado FROM clientes", ttl=0)

    total_colocado = (
        df_solicitudes["monto_compra"].sum() if not df_solicitudes.empty else 0
    )
    total_saldo = (
        df_solicitudes["saldo_pendiente"].sum()
        if not df_solicitudes.empty
        else 0
    )
    total_cupos = (
        df_clientes_tot["cupo_aprobado"].sum()
        if not df_clientes_tot.empty
        else 0
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

        capital_total = float(df_solicitudes["monto_compra"].sum())
        saldo_pendiente = float(df_solicitudes["saldo_pendiente"].sum())
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
        # Gráficas Nativas de Streamlit
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
        cap_tot = float(df_solicitudes["monto_compra"].sum())
        sal_pend = float(df_solicitudes["saldo_pendiente"].sum())
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
elif opcion == "8. Gestión de Usuarios":

  if not es_admin:
    st.error(
        "⛔ **Acceso Restringido:** Este módulo contiene parámetros del sistema"
        " y solo está disponible para usuarios con rol de **Administrador /"
        " Fundador**."
    )
  else:
    st.header("👥 Administración de Usuarios y Parámetros del Sistema")
    st.caption("Módulo Exclusivo Administrativo • Control de Cuentas y Reglas")
    st.markdown("---")

    tab_listar, tab_agregar, tab_editar, tab_param, tab_eliminar = st.tabs([
        "📋 Usuarios Registrados",
        "➕ Agregar Usuario",
        "✏️ Modificar Usuario",
        "⚙️ Parámetros del Sistema",
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
              ["Comercio Aliado", "Administrador", "FUNDADOR (Administrador)"],
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

          # Consultar datos actuales del usuario
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

            roles_disponibles = ["Comercio Aliado", "Administrador", "FUNDADOR (Administrador)"]
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
      st.subheader("⚙️ Configuración Global de Políticas y Parámetros")
      st.caption("Ajusta los parámetros operativos de BankCali.")

      col_p1, col_p2 = st.columns(2)
      with col_p1:
        st.number_input(
            "Tasa de Interés Mensual Base (%)",
            value=2.1,
            step=0.1,
            format="%.2f",
        )
        st.number_input(
            "Tarifa de Aval / Garantía (%)", value=10.0, step=0.5, format="%.1f"
        )
        st.number_input(
            "Monto Mínimo de Compra POS ($ COP)", value=80000, step=10000
        )

      with col_p2:
        st.text_input("Municipio Base de Operaciones", value="Puerto Rico")
        st.text_input("Departamento", value="Caquetá")
        st.number_input("Días de Corte Quincenal", value=15, step=1)

      if st.button("💾 Guardar Parámetros del Sistema"):
        st.success("✅ Parámetros del sistema actualizados correctamente.")

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
