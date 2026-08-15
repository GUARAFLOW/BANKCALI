import streamlit as st
import pandas as pd
import random
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
            padding: 30px 20px;
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
    </style>
""", unsafe_allow_html=True)

# --- PIN DE ADMINISTRADOR ---
PIN_ADMIN = "123456789"

# --- FUNCIÓN MEJORADA PARA ENVIAR SMS CON TWILIO ---
def enviar_sms_twilio(celular_cliente, codigo_otp=None, mensaje_custom=None):
    celular_limpio = ''.join(filter(str.isdigit, str(celular_cliente)))
    if not celular_limpio.startswith("57"):
        celular_limpio = "57" + celular_limpio
    
    numero_destino = f"+{celular_limpio}"
    
    if mensaje_custom:
        mensaje_body = mensaje_custom
    else:
        mensaje_body = f"Su codigo OTP para el credito en Puerto Rico es: {codigo_otp}"
    
    try:
        account_sid = st.secrets["twilio"]["ACCOUNT_SID"]
        auth_token = st.secrets["twilio"]["AUTH_TOKEN"]
        twilio_number = st.secrets["twilio"]["PHONE_NUMBER"]
        
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=mensaje_body,
            from_=twilio_number,
            to=numero_destino
        )
        return True, message.sid
    except Exception as e:
        print(f"Error enviando SMS con Twilio: {e}")
        return False, str(e)

# --- NUEVO MOTOR DE EVALUACIÓN CREDITICIA (INGRESOS Y GASTOS) ---
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

    mensaje = f"✅ Cliente Aprobado para Crédito Rotativo con cupo de ${cupo:,.0f} COP." if cupo > 0 else "❌ Crédito no aprobado por capacidad de endeudamiento."
    return cupo, estado, mensaje

# --- CONEXIÓN A BASE DE DATOS SUPABASE (NUBE) ---
conn = st.connection("supabase", type="sql")

# --- 1. INICIALIZAR SESIÓN ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
    st.session_state.rol = None
    st.session_state.nombre = None
    st.session_state.comercio_asignado = None

# --- 2. PANEL DE LOGIN (BARRA LATERAL) ---
st.sidebar.markdown("""
    <div style="text-align: center; padding: 12px; background: #1E3A8A; border-radius: 8px; color: white; margin-bottom: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">
        <h3 style="color: white; margin: 0; font-size: 1.3rem;">Datos de Acceso</h3>
        <p style="font-size: 0.75rem; margin: 0; opacity: 0.85;">Plataforma BankCali</p>
    </div>
""", unsafe_allow_html=True)

if not st.session_state.autenticado:
    st.sidebar.markdown("Por favor, ingresa tus credenciales autorizadas:")
    doc_login = st.sidebar.text_input("Documento de Usuario")
    pin_login = st.sidebar.text_input("PIN de Acceso", type="password")
    
    if st.sidebar.button("Iniciar Sesión", use_container_width=True):
        if doc_login and pin_login:
            try:
                usuario_db = conn.query("SELECT * FROM usuarios WHERE documento = :doc AND pin = :pin", params={"doc": doc_login, "pin": pin_login}, ttl=0)
                
                if not usuario_db.empty:
                    datos_usuario = usuario_db.iloc[0].to_dict()
                    st.session_state.autenticado = True
                    st.session_state.rol = datos_usuario.get('rol', 'Comercio Aliado')
                    st.session_state.nombre = datos_usuario.get('nombre', 'Usuario')
                    st.session_state.comercio_asignado = datos_usuario.get('comercio_asignado', None)
                    st.rerun()
                else:
                    st.sidebar.error("❌ Documento o PIN incorrectos.")
            except Exception as e:
                st.sidebar.error(f"Error al conectar con la base de datos: {e}")
        else:
            st.sidebar.warning("⚠️ Completa ambos campos.")
            
    st.sidebar.warning("🔒 **Sistema Protegido**. Inicia sesión para habilitar las operaciones.")
    st.sidebar.markdown("---")
    st.sidebar.markdown("<p style='text-align: center; color: gray; font-size: 0.8rem;'>Desarrollado para Gestión Comercial<br>© 2026</p>", unsafe_allow_html=True)
    
    st.markdown("""
        <div style="text-align: center; padding: 20px;">
            <h1 style="color: #1E3A8A; font-size: 2.5rem; margin-bottom: 10px;">BankCali</h1>
            <p style="color: #555; font-size: 1.2rem; margin-bottom: 30px;">Plataforma Financiera de Crédito Rotativo • Puerto Rico (Caquetá)</p>
        </div>
    """, unsafe_allow_html=True)
    
    col_centro1, col_centro2, col_centro3 = st.columns([1, 3, 1])
    with col_centro2:
        try:
            st.image("LOGOBANKCALI.jpeg", use_container_width=True)
        except Exception:
            st.error("No se pudo cargar el logo de BankCali. Verifica que el archivo LOGOBANKCALI.jpeg esté en la carpeta.")
            
    st.stop()

# --- 3. SI EL INICIO DE SESIÓN FUE EXITOSO ---
st.sidebar.success(f"👤 **Sesión Activa:**\n\n{st.session_state.nombre}\n*({st.session_state.rol})*")

if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
    st.session_state.autenticado = False
    st.session_state.rol = None
    st.session_state.nombre = None
    st.session_state.comercio_asignado = None
    st.rerun()

st.sidebar.markdown("---")

menu_opciones = [
    "1. Simular / Solicitar Crédito (POS)", 
    "2. Registrar Nuevo Cliente + Scoring de Cupo"
]

es_admin = (st.session_state.rol == "Administrador")

if es_admin:
    menu_opciones.extend([
        "3. Registrar Pagos / Abonar Cuotas",
        "4. Gestión General de Clientes", 
        "5. Gestión de Almacenes Aliados",
        "6. Panel General de Administración",
        "7. Gestión de Usuarios"
    ])

st.sidebar.markdown("### 🧭 Menú de Navegación")
opcion = st.sidebar.selectbox("Seleccione un módulo", menu_opciones, label_visibility="collapsed")

st.sidebar.markdown("---")
st.sidebar.markdown("<p style='text-align: center; color: gray; font-size: 0.8rem;'>Sistema de Crédito Rotativo v2.5<br>Puerto Rico, Caquetá</p>", unsafe_allow_html=True)

# --- ENCABEZADO CORPORATIVO PARA LAS VISTAS INTERNAS ---
st.markdown("""
    <div class="corporate-banner">
        <h2 style="margin: 0; font-weight: 700; letter-spacing: 0.5px;">BankCali - Plataforma Financiera de Crédito Rotativo</h2>
        <p style="margin: 5px 0 0 0; font-size: 1.1rem; opacity: 0.95;">Puerto Rico (Caquetá) • Impulsando el comercio local</p>
    </div>
""", unsafe_allow_html=True)

# --- MÓDULO 1: SOLICITUD EN PUNTO DE VENTA (POS) ---
if opcion == "1. Simular / Solicitar Crédito (POS)":
    st.header("🏪 Módulo de Punto de Venta (Comercio Aliado)")
    st.markdown("Realiza simulaciones de crédito rápidas y genera desembolsos seguros con verificación OTP.")
    st.markdown("---")
    
    try:
        df_comercios = conn.query("SELECT nombre, comision FROM comercios", ttl=0)
    except Exception:
        df_comercios = pd.DataFrame()
    
    if df_comercios.empty:
        st.warning("⚠️ No hay comercios registrados aún o la tabla está vacía. Ve al módulo de 'Gestión de Almacenes Aliados' para registrar uno.")
    else:
        col1, col2 = st.columns(2, gap="large")
        with col1:
            st.markdown("##### 👤 Datos del Cliente")
            
            if st.session_state.rol == "Comercio Aliado" and st.session_state.comercio_asignado and st.session_state.comercio_asignado != "N/A - Administrador":
                st.info(f"🏢 Operando bajo la tienda: **{st.session_state.comercio_asignado}**")
                comercio_sel = st.session_state.comercio_asignado
            else:
                comercio_sel = st.selectbox("Seleccione el Comercio Aliado", df_comercios['nombre'].tolist())
            
            match_comision = df_comercios[df_comercios['nombre'] == comercio_sel]['comision']
            comercio_comercio = float(match_comision.values[0]) if not match_comision.empty else 5.0
            
            cedula = st.text_input("Número de Cédula del Cliente")
            
            cliente_info = None
            if cedula:
                cliente_info_df = conn.query("SELECT nombre, celular, cupo_disponible FROM clientes WHERE cedula = :ced", params={"ced": cedula}, ttl=0)
                if not cliente_info_df.empty:
                    cliente_info = cliente_info_df.iloc[0]
                
            if cliente_info is not None:
                nombre_cliente = st.text_input("Nombre Completo del Cliente", value=cliente_info['nombre'])
                celular = st.text_input("Número de Celular", value=cliente_info['celular'])
                st.success(f"💡 **Cupo Disponible del Cliente:** ${cliente_info['cupo_disponible']:,.0f} Pesos")
            else:
                nombre_cliente = st.text_input("Nombre Completo del Cliente")
                celular = st.text_input("Número de Celular")
                if cedula:
                    st.warning("⚠️ Cliente no registrado. Seleccione la opción '2. Registrar Nuevo Cliente' en el menú lateral.")

        with col2:
            st.markdown("##### 🛒 Detalles de la Compra")
            monto_compra = st.number_input("Monto de la Compra ($ COP)", min_value=80000, max_value=5000000, step=10000, value=80000)
            cuotas = st.selectbox("Número de Cuotas (Quincenales)", [2, 3, 4, 6, 8])
            
            pct_aval = 0.10       
            tasa_interes = 0.021  
            
            monto_aval = monto_compra * pct_aval
            subtotal = monto_compra + monto_aval
            interes = subtotal * (tasa_interes / 2) * cuotas
            total_pagar = subtotal + interes
            valor_cuota = total_pagar / cuotas
            desembolso = monto_compra * (1 - (comercio_comercio / 100))

        st.markdown("---")
        st.subheader("📊 Resumen Financiero de la Operación")
        res1, res2, res3 = st.columns(3)
        res1.metric("Valor Cuota Quincenal", f"${valor_cuota:,.0f} COP")
        res2.metric("Total a Pagar por Cliente", f"${total_pagar:,.0f} COP")
        res3.metric("Desembolso al Comercio", f"${desembolso:,.0f} COP")

        excede_cupo = False
        if cliente_info is not None and monto_compra > float(cliente_info['cupo_disponible']):
            st.error("❌ La compra excede el cupo disponible del cliente.")
            excede_cupo = True

        st.markdown("---")
        if not excede_cupo and cliente_info is not None and st.button("📱 Generar y Enviar Código OTP de Autorización", use_container_width=True):
            if nombre_cliente and cedula and celular:
                otp = random.randint(1000, 9999)
                st.session_state["otp_actual"] = otp
                
                exito_sms, resultado = enviar_sms_twilio(celular, otp)
                
                if exito_sms:
                    st.success(f"📱 ¡SMS enviado con éxito vía Twilio al celular {celular}!")
                else:
                    st.warning(f"⚠️ Alerta (Modo de prueba/respaldo): No se envió el SMS. Código OTP generado es **{otp}**")
            else:
                st.error("Por favor completa los datos del cliente.")

        if "otp_actual" in st.session_state and not excede_cupo:
            st.markdown("#### 🔑 Verificación de Seguridad")
            otp_ingresado = st.text_input("Ingrese el Código OTP de 4 dígitos enviado al cliente")
            if st.button("✅ Confirmar Venta y Otorgar Crédito", use_container_width=True):
                if str(otp_ingresado) == str(st.session_state["otp_actual"]):
                    id_credito = f"CR-{random.randint(10000, 99999)}"
                    fecha_hoy = datetime.now().strftime("%Y-%m-%d %H:%M")
                    
                    with conn.session as s:
                        s.execute(text("UPDATE clientes SET cupo_disponible = cupo_disponible - :monto WHERE cedula = :cedula"), {"monto": monto_compra, "cedula": cedula})
                        s.execute(text("""
                            INSERT INTO solicitudes (id, fecha, comercio, cedula_cliente, monto_compra, cuotas, valor_cuota, total_pagar, saldo_pendiente, estado) 
                            VALUES (:id, :fecha, :comercio, :cedula, :monto, :cuotas, :cuota, :total, :saldo, :est)
                        """), {"id": id_credito, "fecha": fecha_hoy, "comercio": comercio_sel, "cedula": cedula, "monto": monto_compra, "cuotas": cuotas, "cuota": valor_cuota, "total": total_pagar, "saldo": total_pagar, "est": "ACTIVO"})
                        s.commit()
                    
                    # Notificación final al cliente sobre la compra realizada
                    msg_confirm_compra = f"BankCali: Su compra por ${monto_compra:,.0f} COP en {comercio_sel} fue aprobada. Credito Nro {id_credito}. Cuota: ${valor_cuota:,.0f} COP."
                    enviar_sms_twilio(celular, mensaje_custom=msg_confirm_compra)
                    
                    st.balloons()
                    st.success(f"🎉 ¡Crédito Aprobado e Inscrito con Éxito! Número de Crédito: **{id_credito}**")
                    del st.session_state["otp_actual"]
                else:
                    st.error("❌ Código OTP incorrecto. Verifique e intente nuevamente.")

# --- MÓDULO 2: REGISTRO + SCORING + VERIFICACIÓN OTP & CONTRATO ---
elif opcion == "2. Registrar Nuevo Cliente + Scoring de Cupo":
    st.header("📝 Evaluación, Firma de Acuerdo y Registro de Cliente")
    st.markdown("Sistema automatizado de scoring crediticio con verificación de identidad por SMS (OTP) y aceptación contractual.")
    
    if es_admin:
        st.info("💡 **Política de Crédito:** Ingresos de $100k a $1M con gastos <= 35% reciben $80.000 COP; si superan el 35% reciben $0. Ingresos de $1M a $2.5M dependen del margen disponible. Ingresos > $2.5M reciben un cupo base del 30% ajustado por gastos. Todos los campos marcados con (*) son obligatorios.")
    
    st.markdown("---")
    
    col_e1, col_e2 = st.columns(2, gap="large")
    with col_e1:
        st.markdown("##### 🪪 Información Personal")
        c_cedula = st.text_input("Número de Cédula *")
        c_nombre = st.text_input("Nombre Completo *")
        c_celular = st.text_input("Número de Celular *")
        c_correo = st.text_input("Correo Electrónico *", placeholder="cliente@ejemplo.com")
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
            "Otro / Oficios Varios"
        ])
        c_ingresos = st.number_input("Ingresos Mensuales ($ COP) *", min_value=0, max_value=20000000, step=50000, value=1000000)
        c_gastos = st.number_input("Gastos Mensuales Estimados ($ COP) *", min_value=0, max_value=15000000, step=50000, value=400000)

    cupo_sugerido, nivel_riesgo, mensaje_eval = evaluar_riesgo_y_cupo(c_ingresos, c_gastos)
    
    st.markdown("---")
    st.subheader("🎯 Resultado de la Evaluación de Riesgo")
    
    col_res1, col_res2 = st.columns(2)
    col_res1.metric("Cupo Aprobado Asignado", f"${cupo_sugerido:,.0f} COP")
    col_res2.success(f"🟢 **{nivel_riesgo}**\n\n{mensaje_eval}")
    
    st.markdown("---")
    
    campos_completos = (
        c_cedula.strip() != "" and 
        c_nombre.strip() != "" and 
        c_celular.strip() != "" and 
        c_correo.strip() != "" and
        c_direccion.strip() != "" and 
        c_ocupacion != "Seleccione una actividad..."
    )

    if not campos_completos:
        st.warning("⚠️ **Atención:** Para continuar con la solicitud, debes completar obligatoriamente todos los campos del formulario.")

    elif cupo_sugerido <= 0:
        st.error("❌ El scoring crediticio no aprobó cupo para el cliente. No es posible generar el contrato de crédito.")

    else:
        # --- SECCIÓN DE ACUERDO COMERCIAL Y TÉRMINOS LEGALES ---
        st.subheader("📄 Acuerdo Comercial y Términos del Crédito Rotativo")
        
        st.markdown(f"""
        <div class="terms-box">
            <h4>CONTRATO DE LÍNEA DE CRÉDITO ROTATIVO Y AUTORIZACIÓN DE FIRMA DIGITAL</h4>
            <p><strong>Partes:</strong> BankCali (Operador Financiero Puerto Rico, Caquetá) y el Cliente titular de la Cédula No. <strong>{c_cedula}</strong> ({c_nombre}).</p>
            <p><strong>1. OBJETO:</strong> Por medio del presente acuerdo, BankCali otorga al CLIENTE una línea de Crédito Rotativo con un cupo aprobado de <strong>${cupo_sugerido:,.0f} COP</strong> para ser utilizado exclusivamente en comercios aliados autorizados del municipio de Puerto Rico, Caquetá.</p>
            <p><strong>2. USO Y AMORTIZACIÓN:</strong> El cliente podrá realizar compras contra su cupo y diferir el pago en cuotas quincenales (2 a 8 cuotas). Cada cuota cancelada liberará cupo disponible para futuras compras.</p>
            <p><strong>3. TASAS Y COSTOS:</strong> Las operaciones devengarán una tasa de interés de plazo del 2.1% mensual (proporcional quincenal) y una tarifa por concepto de Aval e Inscripción del 10% sobre la compra.</p>
            <p><strong>4. AUTORIZACIÓN Y NOTIFICACIÓN POR SMS:</strong> El CLIENTE autoriza expresamente el envío de notificaciones de cobranza, mensajes transaccionales y códigos de seguridad vía SMS al número móvil <strong>{c_celular}</strong>. La validación mediante el código único OTP enviado por SMS constituye firma electrónica válida conforme a la Ley 527 de 1999.</p>
            <p><strong>5. PAGARÉ EN BLANCO Y CARTA DE INSTRUCCIONES:</strong> El cliente faculta a BankCali a diligenciar el pagaré adjunto en caso de mora en el pago de dos o más cuotas quincenales consecutivas.</p>
        </div>
        """, unsafe_allow_html=True)

        acepta_terminos = st.checkbox(f"☑️ Confirmo que el cliente {c_nombre} ha sido informado, ha leído y ACEPTA los Términos del Acuerdo Comercial y la Autorización de Datos.")

        st.markdown("---")
        st.subheader("📲 Verificación y Notificación por SMS (Firma Digital)")

        if st.button("📱 Enviar Código OTP de Solicitud de Crédito al Cliente", use_container_width=True, disabled=not acepta_terminos):
            otp_registro = random.randint(1000, 9999)
            st.session_state["otp_registro_actual"] = otp_registro
            
            msg_solicitud = f"BankCali: Su codigo OTP para autorizar la apertura de Credito Rotativo por ${cupo_sugerido:,.0f} COP es: {otp_registro}. Al entregarlo acepta los terminos del contrato."
            exito_sms, resultado = enviar_sms_twilio(c_celular, mensaje_custom=msg_solicitud)
            
            if exito_sms:
                st.success(f"📱 ¡Notificación y OTP de solicitud enviada con éxito vía SMS al celular {c_celular}!")
            else:
                st.warning(f"⚠️ Alerta (Modo de prueba/respaldo): SMS no enviado. El Código OTP de registro generado es **{otp_registro}**")

        if "otp_registro_actual" in st.session_state and acepta_terminos:
            st.markdown("#### 🔑 Confirmación de Autorización del Cliente")
            otp_ingresado_reg = st.text_input("Ingrese el Código OTP de 4 dígitos suministrado por el cliente")
            
            if st.button("✅ Validar OTP, Activar Crédito y Registrar Cliente", use_container_width=True):
                if str(otp_ingresado_reg) == str(st.session_state["otp_registro_actual"]):
                    try:
                        with conn.session as s:
                            s.execute(text("""
                                INSERT INTO clientes (cedula, nombre, celular, correo_electronico, direccion, ocupacion, ingresos, gastos, cupo_aprobado, cupo_disponible) 
                                VALUES (:ced, :nom, :cel, :correo, :dir, :ocu, :ing, :gas, :c_apr, :c_dis)
                            """), {
                                "ced": c_cedula, 
                                "nom": c_nombre, 
                                "cel": c_celular, 
                                "correo": c_correo,
                                "dir": c_direccion,
                                "ocu": c_ocupacion, 
                                "ing": c_ingresos, 
                                "gas": c_gastos, 
                                "c_apr": cupo_sugerido, 
                                "c_dis": cupo_sugerido
                            })
                            s.commit()
                        
                        # SMS AUTOMÁTICO DE NOTIFICACIÓN DE BIENVENIDA Y ACTIVACIÓN DE CRÉDITO
                        msg_bienvenida = f"BankCali: Felicidades {c_nombre}, tu solicitud de Credito Rotativo ha sido APROBADA y ACTIVADA con un cupo de ${cupo_sugerido:,.0f} COP. Gracias por confiar en nosotros."
                        enviar_sms_twilio(c_celular, mensaje_custom=msg_bienvenida)

                        st.balloons()
                        st.success(f"🎉 ¡Crédito Rotativo Activado! Cliente **{c_nombre}** registrado de forma exitosa con cupo de **${cupo_sugerido:,.0f} COP**. Se ha enviado un SMS de notificación confirmando la apertura.")
                        del st.session_state["otp_registro_actual"]
                        
                    except IntegrityError:
                        st.error("❌ Ya existe un cliente registrado con ese número de cédula en la base de datos.")
                    except Exception as e:
                        st.error(f"Error de base de datos: {e}")
                else:
                    st.error("❌ Código OTP incorrecto. Verifique con el cliente e intente nuevamente.")

# --- MÓDULO 3: REGISTRO DE PAGOS (SOLO ADMIN) ---
elif opcion == "3. Registrar Pagos / Abonar Cuotas" and es_admin:
    st.header("💵 Módulo de Recaudo y Abono a Cuotas")
    st.markdown("Gestión de cartera, registro de pagos parciales o totales y liberación automática de cupo.")
    st.markdown("---")
    
    id_credito_buscar = st.text_input("Ingrese Número de Crédito (Ej: CR-12345) o Cédula del Cliente")
    if id_credito_buscar:
        df_sol = conn.query("""
            SELECT s.id, s.fecha, s.comercio, c.nombre, s.cedula_cliente, c.celular, s.valor_cuota, s.saldo_pendiente, s.estado 
            FROM solicitudes s
            JOIN clientes c ON s.cedula_cliente = c.cedula
            WHERE s.id = :termino OR s.cedula_cliente = :termino
        """, params={"termino": id_credito_buscar})
        
        if df_sol.empty:
            st.warning("⚠️ No se encontraron créditos activos asociados a esa búsqueda.")
        else:
            st.dataframe(df_sol[['id', 'fecha', 'comercio', 'nombre', 'cedula_cliente', 'valor_cuota', 'saldo_pendiente', 'estado']], use_container_width=True, hide_index=True)
            
            credito_sel = st.selectbox("Seleccione el ID de Crédito a Abonar", df_sol['id'].tolist())
            fila_credito = df_sol[df_sol['id'] == credito_sel].iloc[0]
            
            saldo_act = float(fila_credito['saldo_pendiente'])
            vlr_cuota = float(fila_credito['valor_cuota'])
            celular_cli = fila_credito['celular']
            
            st.markdown("---")
            col_p1, col_p2 = st.columns(2)
            with col_p1:
                st.info(f"📌 **Saldo Pendiente Actual:** ${saldo_act:,.0f} COP")
            with col_p2:
                st.info(f"📌 **Valor Cuota Sugerido:** ${vlr_cuota:,.0f} COP")
                
            monto_abono = st.number_input("Monto del Abono a Registrar ($ COP)", min_value=1000.0, max_value=saldo_act, value=float(min(vlr_cuota, saldo_act)))
            
            if st.button("💾 Registrar Pago Oficial", use_container_width=True):
                fecha_pago = datetime.now().strftime("%Y-%m-%d %H:%M")
                nuevo_saldo = saldo_act - monto_abono
                nuevo_estado = "CANCELADO" if nuevo_saldo <= 0 else "ACTIVO"
                
                with conn.session as s:
                    s.execute(text("INSERT INTO pagos (fecha, id_credito, monto_pagado) VALUES (:f, :id_c, :m)"), {"f": fecha_pago, "id_c": credito_sel, "m": monto_abono})
                    s.execute(text("UPDATE solicitudes SET saldo_pendiente = :ns, estado = :ne WHERE id = :id_c"), {"ns": nuevo_saldo, "ne": nuevo_estado, "id_c": credito_sel})
                    s.execute(text("UPDATE clientes SET cupo_disponible = cupo_disponible + :m WHERE cedula = :ced"), {"m": monto_abono, "ced": fila_credito['cedula_cliente']})
                    s.commit()
                
                # Notificación SMS de Recibo de Pago
                msg_pago = f"BankCali: Hemos recibido tu abono de ${monto_abono:,.0f} COP al credito {credito_sel}. Nuevo saldo: ${nuevo_saldo:,.0f} COP. Tu cupo ha sido liberado."
                enviar_sms_twilio(celular_cli, mensaje_custom=msg_pago)
                
                st.success(f"✅ Pago por ${monto_abono:,.0f} COP registrado con éxito. Nuevo saldo del crédito: **${nuevo_saldo:,.0f} COP**. SMS de comprobante enviado al cliente.")

# --- MÓDULO 4: GESTIÓN DE CLIENTES (SOLO ADMIN) ---
elif opcion == "4. Gestión General de Clientes" and es_admin:
    st.header("👥 Directorio e Historial General de Clientes")
    st.markdown("Visualización completa de la base de datos de clientes registrados y sus cupos actuales.")
    st.markdown("---")
    try:
        df_cli = conn.query("SELECT cedula, nombre, celular, correo_electronico, direccion, ocupacion, ingresos, gastos, cupo_aprobado, cupo_disponible FROM clientes")
    except Exception:
        df_cli = conn.query("SELECT cedula, nombre, celular, ocupacion, ingresos, gastos, cupo_aprobado, cupo_disponible FROM clientes")
        
    if not df_cli.empty:
        st.dataframe(df_cli, use_container_width=True, hide_index=True)
    else:
        st.info("Aún no hay clientes registrados en el sistema.")

# --- MÓDULO 5: GESTIÓN DE ALMACENES (SOLO ADMIN) ---
elif opcion == "5. Gestión de Almacenes Aliados" and es_admin:
    st.header("🏢 Administración de Comercios Aliados")
    st.markdown("Directorio y control de establecimientos comerciales autorizados en la red.")
    st.markdown("---")
    
    st.markdown("##### 📝 Formulario de Afiliación Comercial")
    col_a1, col_a2 = st.columns(2, gap="large")
    with col_a1:
        nom_com = st.text_input("Nombre Comercial del Almacén *")
        nit_com = st.text_input("NIT / Cédula del Establecimiento *")
        prop_com = st.text_input("Nombre del Propietario / Rep. Legal")
    with col_a2:
        tel_com = st.text_input("Teléfono / Celular de Contacto")
        dir_com = st.text_input("Dirección Física")
        com_com = st.number_input("Porcentaje de Comisión (%) *", min_value=0.0, max_value=20.0, step=0.5, value=5.0)
        
    st.markdown("---")
    if st.button("🏢 Registrar Almacén Oficial", use_container_width=True):
        if nom_com and nit_com:
            try:
                with conn.session as s:
                    s.execute(text("""
                        INSERT INTO comercios (nombre, comision, nit, propietario, telefono, direccion) 
                        VALUES (:nombre, :comision, :nit, :propietario, :telefono, :direccion)
                    """), {
                        "nombre": nom_com, 
                        "comision": com_com,
                        "nit": nit_com,
                        "propietario": prop_com,
                        "telefono": tel_com,
                        "direccion": dir_com
                    })
                    s.commit()
                st.success(f"✅ Almacén '{nom_com}' (NIT: {nit_com}) registrado correctamente en el sistema central.")
            except IntegrityError:
                st.error("❌ Ese comercio ya se encuentra registrado en la base de datos.")
            except Exception as e:
                st.error(f"Error de conexión: {e}")
        else:
            st.warning("⚠️ Los campos 'Nombre Comercial' y 'NIT' son obligatorios.")
            
    st.markdown("---")
    st.subheader("📋 Directorio Oficial de Almacenes Aliados")
    
    df_com_all = conn.query("SELECT id, nit, nombre, propietario, telefono, direccion, comision FROM comercios", ttl=0)
    
    if not df_com_all.empty:
        st.dataframe(df_com_all, use_container_width=True, hide_index=True)
        
        st.markdown("---")
        st.subheader("🗑️ Gestión de Baja de Comercios")
        
        opciones_borrar = dict(zip(df_com_all['id'], df_com_all['nombre'] + " (NIT: " + df_com_all['nit'].astype(str) + ")"))
        id_a_borrar = st.selectbox("Selecciona el comercio que deseas retirar:", options=list(opciones_borrar.keys()), format_func=lambda x: opciones_borrar[x])
        
        if st.button("❌ Eliminar Comercio Definitivamente", type="primary"):
            try:
                with conn.session as s:
                    s.execute(text("DELETE FROM comercios WHERE id = :id"), {"id": id_a_borrar})
                    s.commit()
                st.success("✅ Comercio eliminado correctamente del sistema.")
                st.rerun()
            except Exception as e:
                st.error(f"Error al eliminar: {e}")
    else:
        st.info("Aún no hay comercios registrados en la base de datos.")

# --- MÓDULO 6: PANEL DE ADMINISTRACIÓN (SOLO ADMIN) ---
elif opcion == "6. Panel General de Administración" and es_admin:
    st.header("📈 Panel Ejecutivo y Métricas del Negocio")
    st.markdown("Resumen financiero consolidado de colocación, cartera y recaudo.")
    st.markdown("---")
    
    df_sol_all = conn.query("SELECT * FROM solicitudes")
    df_pag_all = conn.query("SELECT * FROM pagos")
    
    if df_sol_all.empty:
        st.info("No hay transacciones registradas todavía.")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Colocado (Ventas)", f"${df_sol_all['monto_compra'].sum():,.0f} COP")
        m2.metric("Total Cartera por Recaudar", f"${df_sol_all['saldo_pendiente'].sum():,.0f} COP")
        m3.metric("Total Recaudado en Pagos", f"${df_pag_all['monto_pagado'].sum():,.0f} COP" if not df_pag_all.empty else "$0 COP")
        
        st.markdown("---")
        st.subheader("📑 Historial Consolidado de Créditos")
        st.dataframe(df_sol_all, use_container_width=True, hide_index=True)
        
        st.markdown("---")
        st.subheader("💵 Historial de Abonos / Recaudos")
        st.dataframe(df_pag_all, use_container_width=True, hide_index=True)

# --- MÓDULO 7: GESTIÓN DE USUARIOS (SOLO ADMIN) ---
elif opcion == "7. Gestión de Usuarios" and es_admin:
    st.header("👥 Administración de Usuarios y Accesos")
    st.markdown("Control de credenciales, roles y permisos para administradores y comercios aliados.")
    st.markdown("---")

    try:
        df_usuarios = conn.query("SELECT * FROM usuarios", ttl=0)
    except Exception as e:
        st.error("Error al cargar usuarios. Asegúrate de haber ejecutado el ALTER TABLE en Supabase.")
        df_usuarios = None

    if df_usuarios is not None:
        df_comercios_nombres = conn.query("SELECT nombre FROM comercios", ttl=0)
        lista_comercios_opciones = ["N/A - Administrador"] + (df_comercios_nombres['nombre'].tolist() if not df_comercios_nombres.empty else [])
        
        tab1, tab2, tab3 = st.tabs(["➕ Agregar Usuario", "✏️ Modificar Usuario", "🗑️ Eliminar Usuario"])

        with tab1:
            st.subheader("Registrar Nuevo Acceso al Sistema")
            col1, col2 = st.columns(2, gap="large")
            with col1:
                nuevo_doc = st.text_input("Documento de Identidad / NIT")
                nuevo_nom = st.text_input("Nombre Completo o Razón Social")
                nuevo_com_asig = st.selectbox("Asignar a Comercio (Obligatorio para Aliados)", lista_comercios_opciones)
            with col2:
                nuevo_rol = st.selectbox("Rol del Usuario", ["Comercio Aliado", "Administrador"])
                nuevo_pin = st.text_input("PIN de Acceso (Contraseña)", type="password")

            st.markdown("---")
            if st.button("💾 Guardar Nuevo Usuario", use_container_width=True):
                if nuevo_doc and nuevo_nom and nuevo_pin:
                    try:
                        with conn.session as s:
                            s.execute(text("""
                                INSERT INTO usuarios (documento, nombre, rol, pin, comercio_asignado) 
                                VALUES (:doc, :nom, :rol, :pin, :comercio)
                            """), {
                                "doc": nuevo_doc, 
                                "nom": nuevo_nom, 
                                "rol": nuevo_rol, 
                                "pin": nuevo_pin,
                                "comercio": nuevo_com_asig if nuevo_rol == "Comercio Aliado" else "N/A - Administrador"
                            })
                            s.commit()
                        st.success("✅ Usuario creado con éxito.")
                        st.rerun()
                    except IntegrityError:
                        st.error("❌ Ya existe un usuario registrado con ese documento.")
                    except Exception as e:
                        st.error(f"Error al guardar: {e}")
                else:
                    st.warning("⚠️ Debes completar todos los campos obligatorios.")

        with tab2:
            st.subheader("Actualizar Datos o Credenciales de Usuario")
            if not df_usuarios.empty:
                opciones_mod = dict(zip(df_usuarios['id'], df_usuarios['nombre'] + " (" + df_usuarios['rol'] + ")"))
                id_mod = st.selectbox("Selecciona el usuario a modificar:", options=list(opciones_mod.keys()), format_func=lambda x: opciones_mod[x])
                
                usr_actual = df_usuarios[df_usuarios['id'] == id_mod].iloc[0].to_dict()
                
                col3, col4 = st.columns(2, gap="large")
                with col3:
                    mod_doc = st.text_input("Documento", value=usr_actual['documento'])
                    mod_nom = st.text_input("Nombre", value=usr_actual['nombre'])
                    
                    comercio_actual_bd = usr_actual.get('comercio_asignado', "N/A - Administrador")
                    if pd.isna(comercio_actual_bd) or comercio_actual_bd not in lista_comercios_opciones:
                        comercio_actual_bd = "N/A - Administrador"
                    idx_com = lista_comercios_opciones.index(comercio_actual_bd)
                    
                    mod_comercio = st.selectbox("Modificar Comercio Asignado", lista_comercios_opciones, index=idx_com)

                with col4:
                    roles = ["Comercio Aliado", "Administrador"]
                    idx_rol = roles.index(usr_actual['rol']) if usr_actual['rol'] in roles else 0
                    mod_rol = st.selectbox("Nuevo Rol", roles, index=idx_rol)
                    mod_pin = st.text_input("Cambiar PIN (Déjalo igual si no deseas cambiarlo)", value=usr_actual['pin'], type="password")

                st.markdown("---")
                if st.button("💾 Guardar Cambios de Usuario", use_container_width=True):
                    try:
                        with conn.session as s:
                            s.execute(text("""
                                UPDATE usuarios 
                                SET documento = :doc, nombre = :nom, rol = :rol, pin = :pin, comercio_asignado = :comercio 
                                WHERE id = :id
                            """), {
                                "doc": mod_doc,
                                "nom": mod_nom,
                                "rol": mod_rol,
                                "pin": mod_pin,
                                "comercio": mod_comercio if mod_rol == "Comercio Aliado" else "N/A - Administrador",
                                "id": id_mod
                            })
                            s.commit()
                        st.success("✅ Usuario actualizado correctamente.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al actualizar usuario: {e}")

        with tab3:
            st.subheader("Eliminar Usuario")
            if not df_usuarios.empty:
                opciones_del = dict(zip(df_usuarios['id'], df_usuarios['nombre'] + " (" + df_usuarios['rol'] + ")"))
                id_del = st.selectbox("Selecciona el usuario a eliminar:", options=list(opciones_del.keys()), format_func=lambda x: opciones_del[x])
                
                if st.button("🗑️ Eliminar Usuario Definitivamente", type="primary"):
                    try:
                        with conn.session as s:
                            s.execute(text("DELETE FROM usuarios WHERE id = :id"), {"id": id_del})
                            s.commit()
                        st.success("✅ Usuario eliminado correctamente.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al eliminar usuario: {e}")
