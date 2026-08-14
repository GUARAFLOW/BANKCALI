import streamlit as st
import pandas as pd
import sqlite3
import random
import requests
from datetime import datetime

# Configuración de página
st.set_page_config(page_title="Crédito Puerto Rico", layout="wide")

# --- PIN DE ADMINISTRADOR ---
PIN_ADMIN = "1234"  # Puedes cambiar este PIN por el que tú prefieras

# --- FUNCIÓN PARA ENVIAR SMS GRATIS (TEXTBELT) ---
def enviar_sms_gratis_textbelt(celular_cliente, codigo_otp):
    celular_limpio = ''.join(filter(str.isdigit, celular_cliente))
    if not celular_limpio.startswith("57"):
        celular_limpio = "57" + celular_limpio
        
    mensaje = f"Su codigo OTP para el credito en Puerto Rico es: {codigo_otp}"
    
    try:
        response = requests.post('https://textbelt.com/text', {
            'phone': f'+{celular_limpio}',
            'message': mensaje,
            'key': 'textbelt',
        }, timeout=8)
        
        resultado = response.json()
        return resultado.get('success', False)
    except Exception as e:
        print(f"Error enviando SMS: {e}")
        return False

# --- MOTOR DE EVALUACIÓN CREDITICIA (REGLA DE INGRESOS Y 20%) ---
def evaluar_riesgo_y_cupo(ingresos):
    if ingresos <= 1000000:
        cupo_final = 80000
    else:
        cupo_calculado = ingresos * 0.20
        cupo_final = round(cupo_calculado / 10000) * 10000
        
    return cupo_final, "APROBADO", f"✅ Cliente Aprobado para Crédito Rotativo con cupo de ${cupo_final:,.0f} COP."

# --- CONEXIÓN A BASE DE DATOS PERSISTENTE ---
conn = sqlite3.connect('creditos_puerto_rico.db', check_same_thread=False)
cursor = conn.cursor()

# Crear tablas si no existen
cursor.execute("CREATE TABLE IF NOT EXISTS comercios (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE, comision REAL)")
cursor.execute("CREATE TABLE IF NOT EXISTS clientes (cedula TEXT PRIMARY KEY, nombre TEXT, celular TEXT, ocupacion TEXT, ingresos REAL, gastos REAL, cupo_aprobado REAL, cupo_disponible REAL)")
cursor.execute("CREATE TABLE IF NOT EXISTS solicitudes (id TEXT PRIMARY KEY, fecha TEXT, comercio TEXT, cedula_cliente TEXT, monto_compra REAL, cuotas INTEGER, valor_cuota REAL, total_pagar REAL, saldo_pendiente REAL, estado TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS pagos (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, id_credito TEXT, monto_pagado REAL)")
conn.commit()

# --- TÍTULO PRINCIPAL ---
st.title("💳 CREDITOS ROTATIVOS BANKCALI")

# --- CONTROL DE PERMISOS / ROLES EN BARRA LATERAL ---
st.sidebar.title("🔐 Control de Acceso")
rol_usuario = st.sidebar.radio("Seleccione el Perfil de Usuario:", ["🏪 Comercio Aliado (Público)", "🔑 Administrador"])

# Opciones base para los Comercios Aliados
menu_opciones = [
    "1. Simular / Solicitar Crédito (POS)", 
    "2. Registrar Nuevo Cliente + Scoring de Cupo"
]

# Validación de PIN para Administrador
es_admin = False
if rol_usuario == "🔑 Administrador":
    pin_ingresado = st.sidebar.text_input("Ingrese PIN de Administrador", type="password")
    if pin_ingresado == PIN_ADMIN:
        es_admin = True
        st.sidebar.success("🔓 Acceso Administrador Concedido")
        # Agregar módulos administrativos al menú
        menu_opciones.extend([
            "3. Registrar Pagos / Abonar Cuotas",
            "4. Gestión General de Clientes", 
            "5. Gestión de Almacenes Aliados",
            "6. Panel General de Administración"
        ])
    elif pin_ingresado != "":
        st.sidebar.error("❌ PIN Incorrecto")

st.sidebar.markdown("---")
opcion = st.sidebar.selectbox("Menú de Navegación", menu_opciones)

# --- MÓDULO 1: SOLICITUD EN PUNTO DE VENTA (POS) ---
if opcion == "1. Simular / Solicitar Crédito (POS)":
    st.header("🏪 Módulo de Punto de Venta (Comercio Aliado)")
    
    df_comercios = pd.read_sql_query("SELECT nombre, comision FROM comercios", conn)
    
    if df_comercios.empty:
        st.warning("⚠️ No hay comercios registrados aún. Comunícate con el Administrador para afiliar tu almacén.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            comercio_sel = st.selectbox("Seleccione el Comercio Aliado", df_comercios['nombre'].tolist())
            comision_comercio = df_comercios[df_comercios['nombre'] == comercio_sel]['comision'].values[0]
            
            cedula = st.text_input("Número de Cédula del Cliente")
            
            cliente_info = None
            if cedula:
                cursor.execute("SELECT nombre, celular, cupo_disponible FROM clientes WHERE cedula = ?", (cedula,))
                cliente_info = cursor.fetchone()
                
            if cliente_info:
                nombre_cliente = st.text_input("Nombre Completo del Cliente", value=cliente_info[0])
                celular = st.text_input("Número de Celular", value=cliente_info[1])
                st.success(f"💡 **Cupo Disponible del Cliente:** ${cliente_info[2]:,.0f} Pesos")
            else:
                nombre_cliente = st.text_input("Nombre Completo del Cliente")
                celular = st.text_input("Número de Celular")
                if cedula:
                    st.warning("⚠️ Cliente no registrado. Seleccione la opción '2. Registrar Nuevo Cliente' en el menú de la izquierda para otorgarle su cupo.")

        with col2:
            monto_compra = st.number_input("Monto de la Compra ($ COP)", min_value=80000, max_value=5000000, step=10000, value=80000)
            cuotas = st.selectbox("Número de Cuotas (Quincenales)", [2, 3, 4, 6, 8])
            
            pct_aval = 0.10       # 10% Fianza / Aval
            tasa_interes = 0.021  # 2.1% Mensual
            
            monto_aval = monto_compra * pct_aval
            subtotal = monto_compra + monto_aval
            interes = subtotal * (tasa_interes / 2) * cuotas
            total_pagar = subtotal + interes
            valor_cuota = total_pagar / cuotas
            desembolso = monto_compra * (1 - (comision_comercio / 100))

        st.subheader("📊 Resumen de la Operación")
        res1, res2, res3 = st.columns(3)
        res1.metric("Valor Cuota Quincenal", f"${valor_cuota:,.0f} Pesos")
        res2.metric("Total a Pagar por Cliente", f"${total_pagar:,.0f} Pesos")
        res3.metric("Desembolso al Comercio", f"${desembolso:,.0f} Pesos")

        excede_cupo = False
        if cliente_info and monto_compra > cliente_info[2]:
            st.error("❌ La compra excede el cupo disponible del cliente.")
            excede_cupo = True

        if not excede_cupo and cliente_info and st.button("Generar Código OTP"):
            if nombre_cliente and cedula and celular:
                otp = random.randint(1000, 9999)
                st.session_state["otp_actual"] = otp
                
                exito_sms = enviar_sms_gratis_textbelt(celular, otp)
                
                if exito_sms:
                    st.success(f"📱 ¡SMS enviado con éxito al celular {celular}!")
                else:
                    st.warning(f"⚠️ Notificación simulada por pantalla: Código OTP es **{otp}**")
            else:
                st.error("Por favor completa los datos del cliente.")

        if "otp_actual" in st.session_state and not excede_cupo:
            otp_ingresado = st.text_input("Ingrese el Código OTP de 4 dígitos enviado al celular del cliente")
            if st.button("Confirmar Venta y Otorgar Crédito"):
                if str(otp_ingresado) == str(st.session_state["otp_actual"]):
                    id_credito = f"CR-{random.randint(10000, 99999)}"
                    fecha_hoy = datetime.now().strftime("%Y-%m-%d %H:%M")
                    
                    cursor.execute("UPDATE clientes SET cupo_disponible = cupo_disponible - ? WHERE cedula = ?", 
                                   (monto_compra, cedula))
                    
                    cursor.execute("INSERT INTO solicitudes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                   (id_credito, fecha_hoy, comercio_sel, cedula, monto_compra, cuotas, valor_cuota, total_pagar, total_pagar, "ACTIVO"))
                    
                    conn.commit()
                    st.balloons()
                    st.success(f"🎉 ¡Crédito Aprobado! Número de Crédito: **{id_credito}**")
                    del st.session_state["otp_actual"]
                else:
                    st.error("Código OTP incorrecto.")

# --- MÓDULO 2: REGISTRO + SCORING (POS) ---
elif opcion == "2. Registrar Nuevo Cliente + Scoring de Cupo":
    st.header("📝 Evaluación y Registro de Cliente")
    st.caption("Política de Crédito: Ingresos <= $1.000.000 COP reciben $80.000 COP de cupo. Ingresos mayores a $1.000.000 COP reciben el 20% de sus ingresos.")
    
    col_e1, col_e2 = st.columns(2)
    with col_e1:
        c_cedula = st.text_input("Número de Cédula")
        c_nombre = st.text_input("Nombre Completo")
        c_celular = st.text_input("Número de Celular")
        
    with col_e2:
        c_ocupacion = st.selectbox("Actividad Económica", [
            "Empleado Público / Pensionado", 
            "Empleado Formal (Empresa)", 
            "Comerciante / Ganadero", 
            "Independiente / Agrícola"
        ])
        c_ingresos = st.number_input("Ingresos Mensuales ($ COP)", min_value=100000, max_value=20000000, step=50000, value=1000000)
        c_gastos = st.number_input("Gastos Mensuales Estimados ($ COP)", min_value=0, max_value=15000000, step=50000, value=400000)

    cupo_sugerido, nivel_riesgo, mensaje_eval = evaluar_riesgo_y_cupo(c_ingresos)
    
    st.markdown("---")
    st.subheader("🎯 Resultado de la Evaluación")
    
    col_res1, col_res2 = st.columns(2)
    col_res1.metric("Cupo Aprobado Asignado", f"${cupo_sugerido:,.0f} Pesos")
    col_res2.success(f"🟢 **{nivel_riesgo}**\n\n{mensaje_eval}")
    
    if st.button("Aprobar y Registrar Cliente"):
        if c_cedula and c_nombre and c_celular:
            try:
                cursor.execute("INSERT INTO clientes VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                               (c_cedula, c_nombre, c_celular, c_ocupacion, c_ingresos, c_gastos, cupo_sugerido, cupo_sugerido))
                conn.commit()
                st.balloons()
                st.success(f"🎉 Cliente **{c_nombre}** registrado exitosamente con un cupo de **${cupo_sugerido:,.0f} Pesos**.")
            except sqlite3.IntegrityError:
                st.error("❌ Ya existe un cliente registrado con ese número de cédula.")
        else:
            st.error("Por favor completa los campos básicos (Cédula, Nombre, Celular).")

# --- MÓDULO 3: REGISTRO DE PAGOS (SOLO ADMIN) ---
elif opcion == "3. Registrar Pagos / Abonar Cuotas" and es_admin:
    st.header("💵 Módulo de Recaudo / Abonar Cuotas")
    
    id_credito_buscar = st.text_input("Ingrese Número de Crédito o Cédula del Cliente")
    if id_credito_buscar:
        df_sol = pd.read_sql_query("""
            SELECT s.id, s.fecha, s.comercio, c.nombre, s.cedula_cliente, s.valor_cuota, s.saldo_pendiente, s.estado 
            FROM solicitudes s
            JOIN clientes c ON s.cedula_cliente = c.cedula
            WHERE s.id = ? OR s.cedula_cliente = ?
        """, conn, params=(id_credito_buscar, id_credito_buscar))
        
        if df_sol.empty:
            st.warning("No se encontraron créditos activos con esa búsqueda.")
        else:
            st.dataframe(df_sol, use_container_width=True)
            
            credito_sel = st.selectbox("Seleccione el Crédito a Abonar", df_sol['id'].tolist())
            fila_credito = df_sol[df_sol['id'] == credito_sel].iloc[0]
            
            saldo_act = fila_credito['saldo_pendiente']
            vlr_cuota = fila_credito['valor_cuota']
            
            monto_abono = st.number_input("Monto a Abonar ($ COP)", min_value=1000.0, max_value=float(saldo_act), value=float(min(vlr_cuota, saldo_act)))
            
            if st.button("Registrar Pago"):
                fecha_pago = datetime.now().strftime("%Y-%m-%d %H:%M")
                
                cursor.execute("INSERT INTO pagos (fecha, id_credito, monto_pagado) VALUES (?, ?, ?)", 
                               (fecha_pago, credito_sel, monto_abono))
                
                nuevo_saldo = saldo_act - monto_abono
                nuevo_estado = "CANCELADO" if nuevo_saldo <= 0 else "ACTIVO"
                
                cursor.execute("UPDATE solicitudes SET saldo_pendiente = ?, estado = ? WHERE id = ?", 
                               (nuevo_saldo, nuevo_estado, credito_sel))
                
                cursor.execute("UPDATE clientes SET cupo_disponible = cupo_disponible + ? WHERE cedula = ?", 
                               (monto_abono, fila_credito['cedula_cliente']))
                
                conn.commit()
                st.success(f"✅ Pago de ${monto_abono:,.0f} Pesos registrado con éxito. Nuevo Saldo: ${nuevo_saldo:,.0f} Pesos")

# --- MÓDULO 4: GESTIÓN DE CLIENTES (SOLO ADMIN) ---
elif opcion == "4. Gestión General de Clientes" and es_admin:
    st.header("👥 Lista e Historial General de Clientes")
    df_cli = pd.read_sql_query("SELECT cedula, nombre, celular, ocupacion, ingresos, gastos, cupo_aprobado, cupo_disponible FROM clientes", conn)
    st.dataframe(df_cli, use_container_width=True)

# --- MÓDULO 5: GESTIÓN DE ALMACENES (SOLO ADMIN) ---
elif opcion == "5. Gestión de Almacenes Aliados" and es_admin:
    st.header("🏢 Administración de Comercios Aliados")
    
    col_a1, col_a2 = st.columns(2)
    with col_a1:
        nom_com = st.text_input("Nombre del Almacén / Comercio")
    with col_a2:
        com_com = st.number_input("Porcentaje de Comisión (%)", min_value=0.0, max_value=20.0, step=0.5, value=5.0)
        
    if st.button("Registrar Almacén"):
        if nom_com:
            try:
                cursor.execute("INSERT INTO comercios (nombre, comision) VALUES (?, ?)", (nom_com, com_com))
                conn.commit()
                st.success(f"✅ Almacén '{nom_com}' guardado con {com_com}% de comisión.")
            except sqlite3.IntegrityError:
                st.error("Ese comercio ya está registrado.")
                
    st.subheader("📋 Almacenes Afiliados")
    df_com_all = pd.read_sql_query("SELECT * FROM comercios", conn)
    st.dataframe(df_com_all, use_container_width=True)

# --- MÓDULO 6: PANEL DE ADMINISTRACIÓN (SOLO ADMIN) ---
elif opcion == "6. Panel General de Administración" and es_admin:
    st.header("📈 Métricas Generales del Negocio")
    
    df_sol_all = pd.read_sql_query("SELECT * FROM solicitudes", conn)
    df_pag_all = pd.read_sql_query("SELECT * FROM pagos", conn)
    
    if df_sol_all.empty:
        st.info("No hay transacciones registradas.")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Colocado (Ventas)", f"${df_sol_all['monto_compra'].sum():,.0f} Pesos")
        m2.metric("Total Cartera por Recaudar", f"${df_sol_all['saldo_pendiente'].sum():,.0f} Pesos")
        m3.metric("Total Recaudado en Pagos", f"${df_pag_all['monto_pagado'].sum():,.0f} Pesos" if not df_pag_all.empty else "$0 Pesos")
        
        st.subheader("📑 Historial de Créditos")
        st.dataframe(df_sol_all, use_container_width=True)
        
        st.subheader("💵 Historial de Abonos / Recaudos")
        st.dataframe(df_pag_all, use_container_width=True)
