import streamlit as st
import pandas as pd
import random
import requests
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from twilio.rest import Client

# Configuración de página
st.set_page_config(
    page_title="Crédito Puerto Rico | Plataforma Financiera",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- ESTILOS CSS PERSONALIZADOS ---
st.markdown("""
    <style>
        .main { background-color: #f8f9fa; }
        h1, h2, h3 { color: #1E3A8A; }
        div.corporate-banner {
            padding: 30px 20px;
            background: linear-gradient(135deg, #0A192F 0%, #112240 50%, #1E3A8A 100%) !important;
            color: white !important;
            border-radius: 12px;
            margin-bottom: 25px;
            text-align: center;
            box-shadow: 0 6px 20px rgba(0,0,0,0.2);
            border: 1px solid #38BDF8;
        }
        div.corporate-banner h2, div.corporate-banner p { color: white !important; }
    </style>
""", unsafe_allow_html=True)

# --- CONFIGURACIÓN DE TWILIO ---
TWILIO_SID = 'TU_ACCOUNT_SID_AQUI'
TWILIO_TOKEN = 'TU_AUTH_TOKEN_AQUI'
TWILIO_PHONE = '+1234567890'

def enviar_sms_twilio(celular_cliente, codigo_otp):
    celular_limpio = ''.join(filter(str.isdigit, celular_cliente))
    if not celular_limpio.startswith("57"):
        celular_limpio = "57" + celular_limpio
    
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(
            body=f"BankCali OTP: Su codigo de validacion es {codigo_otp}",
            from_=TWILIO_PHONE,
            to=f"+{celular_limpio}"
        )
        return True
    except Exception as e:
        st.error(f"Error de Twilio: {e}")
        return False

# --- MOTOR DE SCORING ACTUALIZADO ---
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

    mensaje = f"✅ Cupo aprobado: ${cupo:,.0f} COP." if cupo > 0 else "❌ Crédito no aprobado por capacidad de endeudamiento."
    return cupo, estado, mensaje

# --- CONEXIÓN A BASE DE DATOS ---
conn = st.connection("supabase", type="sql")

# --- SESIÓN Y LOGIN ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
    st.session_state.rol = None
    st.session_state.nombre = None

if not st.session_state.autenticado:
    st.sidebar.title("Datos de Acceso")
    doc_login = st.sidebar.text_input("Documento de Usuario")
    pin_login = st.sidebar.text_input("PIN de Acceso", type="password")
    
    if st.sidebar.button("Iniciar Sesión", use_container_width=True):
        if doc_login and pin_login:
            usuario_db = conn.query("SELECT nombre, rol FROM usuarios WHERE documento = :doc AND pin = :pin", params={"doc": doc_login, "pin": pin_login}, ttl=0)
            if not usuario_db.empty:
                st.session_state.autenticado = True
                st.session_state.rol = usuario_db.iloc[0]['rol']
                st.session_state.nombre = usuario_db.iloc[0]['nombre']
                st.rerun()
            else:
                st.sidebar.error("❌ Documento o PIN incorrectos.")
        else:
            st.sidebar.warning("⚠️ Completa ambos campos.")
    st.stop()

# --- MENÚ PRINCIPAL ---
st.sidebar.success(f"👤 **Sesión:** {st.session_state.nombre}\n*({st.session_state.rol})*")
if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
    st.session_state.autenticado = False
    st.rerun()

menu_opciones = ["1. Simular / Solicitar Crédito (POS)", "2. Registrar Nuevo Cliente + Scoring"]
es_admin = (st.session_state.rol == "Administrador")

if es_admin:
    menu_opciones.extend([
        "3. Registrar Pagos / Abonar Cuotas",
        "4. Gestión General de Clientes", 
        "5. Gestión de Almacenes Aliados",
        "6. Panel General de Administración",
        "7. Gestión de Usuarios"
    ])

opcion = st.sidebar.selectbox("Seleccione un módulo", menu_opciones)

st.markdown("""
    <div class="corporate-banner">
        <h2 style="margin: 0; font-weight: 700;">BankCali - Plataforma Financiera</h2>
        <p style="margin: 5px 0 0 0; font-size: 1.1rem;">Puerto Rico (Caquetá)</p>
    </div>
""", unsafe_allow_html=True)

# --- MÓDULO 1 ---
if opcion == "1. Simular / Solicitar Crédito (POS)":
    st.header("🏪 Módulo de Punto de Venta (POS)")
    df_comercios = conn.query("SELECT nombre, comision FROM comercios", ttl=0)
    
    if df_comercios.empty:
        st.warning("⚠️ No hay comercios registrados.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            comercio_sel = st.selectbox("Comercio Aliado", df_comercios['nombre'].tolist())
            comision_val = float(df_comercios[df_comercios['nombre'] == comercio_sel]['comision'].values[0])
            cedula = st.text_input("Cédula del Cliente")
            
            cliente_info = None
            if cedula:
                res_cli = conn.query("SELECT * FROM clientes WHERE cedula = :ced", params={"ced": cedula}, ttl=0)
                if not res_cli.empty: cliente_info = res_cli.iloc[0]
            
            if cliente_info is not None:
                nombre_cliente = st.text_input("Nombre", value=cliente_info['nombre'])
                celular = st.text_input("Celular", value=cliente_info['celular'])
                st.success(f"Cupo disponible: ${cliente_info['cupo_disponible']:,.0f}")
            else:
                nombre_cliente = st.text_input("Nombre")
                celular = st.text_input("Celular")

        with col2:
            monto_compra = st.number_input("Monto de Compra", min_value=80000, step=10000, value=80000)
            cuotas = st.selectbox("Cuotas Quincenales", [2, 3, 4, 6, 8])
            
            total_pagar = (monto_compra * 1.10) * (1 + (0.021 / 2) * cuotas)
            valor_cuota = total_pagar / cuotas
            st.metric("Cuota Quincenal", f"${valor_cuota:,.0f} COP")

        if cliente_info is not None and monto_compra <= float(cliente_info['cupo_disponible']):
            if st.button("📱 Enviar Código OTP por SMS"):
                otp = random.randint(1000, 9999)
                st.session_state.otp_actual = otp
                if enviar_sms_twilio(celular, otp):
                    st.success("¡Código OTP enviado vía Twilio!")

        if "otp_actual" in st.session_state:
            otp_ingresado = st.text_input("Ingrese OTP")
            if st.button("✅ Confirmar Venta"):
                if str(otp_ingresado) == str(st.session_state.otp_actual):
                    id_cred = f"CR-{random.randint(10000, 99999)}"
                    with conn.session as s:
                        s.execute(text("UPDATE clientes SET cupo_disponible = cupo_disponible - :m WHERE cedula = :c"), {"m": monto_compra, "c": cedula})
                        s.execute(text("INSERT INTO solicitudes (id, fecha, comercio, cedula_cliente, monto_compra, cuotas, valor_cuota, total_pagar, saldo_pendiente, estado) VALUES (:id, :f, :com, :ced, :mc, :cuo, :vc, :tp, :sp, 'ACTIVO')"),
                                  {"id": id_cred, "f": datetime.now().strftime("%Y-%m-%d %H:%M"), "com": comercio_sel, "ced": cedula, "mc": monto_compra, "cuo": cuotas, "vc": valor_cuota, "tp": total_pagar, "sp": total_pagar})
                        s.commit()
                    st.success(f"¡Crédito aprobado! ID: {id_cred}")
                    del st.session_state.otp_actual

# --- MÓDULO 2 ---
elif opcion == "2. Registrar Nuevo Cliente + Scoring":
    st.header("📝 Evaluación y Registro de Cliente")
    if es_admin:
        st.info("💡 **Política de Crédito:** Rango 1 ($100k-$1M y gastos $\le$ 35% da $80k); Rango 2 ($1M-$2.5M margen del 25%); Rango 3 (> $2.5M base 30% con ajuste de gastos).")
    
    col1, col2 = st.columns(2)
    with col1:
        c_cedula = st.text_input("Cédula *")
        c_nombre = st.text_input("Nombre Completo *")
        c_celular = st.text_input("Celular *")
        c_direccion = st.text_input("Dirección *")
    with col2:
        c_ocupacion = st.selectbox("Actividad", ["Empleado", "Independiente", "Comerciante", "Ganadero", "Agricultor", "Otro"])
        c_ingresos = st.number_input("Ingresos Mensuales", value=1000000, step=50000)
        c_gastos = st.number_input("Gastos Mensuales", value=400000, step=50000)

    cupo, estado, mensaje = evaluar_riesgo_y_cupo(c_ingresos, c_gastos)
    st.metric("Cupo Sugerido", f"${cupo:,.0f} COP")
    st.write(mensaje)

    if st.button("Guardar Cliente"):
        try:
            with conn.session as s:
                s.execute(text("INSERT INTO clientes (cedula, nombre, celular, direccion, ocupacion, ingresos, gastos, cupo_aprobado, cupo_disponible) VALUES (:ced, :nom, :cel, :dir, :ocu, :ing, :gas, :cap, :cap)"),
                          {"ced": c_cedula, "nom": c_nombre, "cel": c_celular, "dir": c_direccion, "ocu": c_ocupacion, "ing": c_ingresos, "gas": c_gastos, "cap": cupo})
                s.commit()
            st.success("Cliente guardado exitosamente.")
        except IntegrityError:
            st.error("La cédula ya se encuentra registrada.")

# --- MÓDULO 3 ---
elif opcion == "3. Registrar Pagos / Abonar Cuotas" and es_admin:
    st.header("💵 Módulo de Recaudo")
    ter = st.text_input("Número de Crédito o Cédula")
    if ter:
        df_sol = conn.query("SELECT s.id, s.cedula_cliente, c.nombre, s.valor_cuota, s.saldo_pendiente FROM solicitudes s JOIN clientes c ON s.cedula_cliente = c.cedula WHERE s.id = :t OR s.cedula_cliente = :t", params={"t": ter})
        if not df_sol.empty:
            st.dataframe(df_sol, hide_index=True)
            c_sel = st.selectbox("Seleccione ID Crédito", df_sol['id'].tolist())
            fila = df_sol[df_sol['id'] == c_sel].iloc[0]
            abono = st.number_input("Monto del Abono", max_value=float(fila['saldo_pendiente']), value=float(fila['valor_cuota']))
            if st.button("Registrar Pago"):
                ns = float(fila['saldo_pendiente']) - abono
                ne = "CANCELADO" if ns <= 0 else "ACTIVO"
                with conn.session as s:
                    s.execute(text("INSERT INTO pagos (fecha, id_credito, monto_pagado) VALUES (:f, :id, :m)"), {"f": datetime.now().strftime("%Y-%m-%d"), "id": c_sel, "m": abono})
                    s.execute(text("UPDATE solicitudes SET saldo_pendiente = :ns, estado = :ne WHERE id = :id"), {"ns": ns, "ne": ne, "id": c_sel})
                    s.execute(text("UPDATE clientes SET cupo_disponible = cupo_disponible + :m WHERE cedula = :ced"), {"m": abono, "ced": fila['cedula_cliente']})
                    s.commit()
                st.success("Pago registrado con éxito.")

# --- MÓDULO 4 ---
elif opcion == "4. Gestión General de Clientes" and es_admin:
    st.header("👥 Directorio de Clientes")
    df_cli = conn.query("SELECT * FROM clientes")
    st.dataframe(df_cli, use_container_width=True, hide_index=True)

# --- MÓDULO 5 ---
elif opcion == "5. Gestión de Almacenes Aliados" and es_admin:
    st.header("🏢 Gestión de Comercios")
    c1, c2 = st.columns(2)
    with c1:
        n_com = st.text_input("Nombre Comercio")
        nit_com = st.text_input("NIT")
    with c2:
        tel_com = st.text_input("Teléfono")
        com_val = st.number_input("Comisión (%)", value=5.0)
    if st.button("Registrar Comercio"):
        with conn.session as s:
            s.execute(text("INSERT INTO comercios (nombre, nit, telefono, comision) VALUES (:n, :nit, :t, :c)"), {"n": n_com, "nit": nit_com, "t": tel_com, "c": com_val})
            s.commit()
        st.success("Comercio registrado.")
    df_coms = conn.query("SELECT * FROM comercios")
    st.dataframe(df_coms, use_container_width=True, hide_index=True)

# --- MÓDULO 6 ---
elif opcion == "6. Panel General de Administración" and es_admin:
    st.header("📈 Panel Ejecutivo")
    df_s = conn.query("SELECT * FROM solicitudes")
    if not df_s.empty:
        c1, c2 = st.columns(2)
        c1.metric("Total Colocado", f"${df_s['monto_compra'].sum():,.0f}")
        c2.metric("Saldo Cartera", f"${df_s['saldo_pendiente'].sum():,.0f}")
        st.dataframe(df_s, use_container_width=True, hide_index=True)

# --- MÓDULO 7 ---
elif opcion == "7. Gestión de Usuarios" and es_admin:
    st.header("👥 Gestión de Usuarios y Accesos")
    doc_u = st.text_input("Documento Nuevo Usuario")
    nom_u = st.text_input("Nombre Nuevo Usuario")
    rol_u = st.selectbox("Rol", ["Comercio Aliado", "Administrador"])
    pin_u = st.text_input("PIN", type="password")
    if st.button("Crear Usuario"):
        with conn.session as s:
            s.execute(text("INSERT INTO usuarios (documento, nombre, rol, pin) VALUES (:d, :n, :r, :p)"), {"d": doc_u, "n": nom_u, "r": rol_u, "p": pin_u})
            s.commit()
        st.success("Usuario creado con éxito.")
    df_usrs = conn.query("SELECT documento, nombre, rol FROM usuarios")
    st.dataframe(df_usrs, use_container_width=True, hide_index=True)
