import streamlit as st
import pandas as pd
import random
import requests
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# Configuración de página
st.set_page_config(page_title="Crédito Puerto Rico", layout="wide")

# --- PIN DE ADMINISTRADOR ---
PIN_ADMIN = "123456789"  # Puedes cambiar este PIN por el que tú prefieras

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

# --- CONEXIÓN A BASE DE DATOS SUPABASE (NUBE) ---
conn = st.connection("supabase", type="sql")

# --- TÍTULO PRINCIPAL ---
st.title("💳 Plataforma de Crédito Rotativo - Puerto Rico (Caquetá)")
# (Si en el futuro quieres intentar poner la imagen de nuevo, quita el '#' de la siguiente línea)
# st.image("logo.png", use_container_width=True)

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
            "6. Panel General de Administración",
            "7. Gestión de Usuarios"
        ])
    elif pin_ingresado != "":
        st.sidebar.error("❌ PIN Incorrecto")

st.sidebar.markdown("---")
opcion = st.sidebar.selectbox("Menú de Navegación", menu_opciones)

# --- MÓDULO 1: SOLICITUD EN PUNTO DE VENTA (POS) ---
if opcion == "1. Simular / Solicitar Crédito (POS)":
    st.header("🏪 Módulo de Punto de Venta (Comercio Aliado)")
    
    df_comercios = conn.query("SELECT nombre, comision FROM comercios")
    
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
                cliente_info_df = conn.query("SELECT nombre, celular, cupo_disponible FROM clientes WHERE cedula = :ced", params={"ced": cedula})
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
        if cliente_info is not None and monto_compra > float(cliente_info['cupo_disponible']):
            st.error("❌ La compra excede el cupo disponible del cliente.")
            excede_cupo = True

        if not excede_cupo and cliente_info is not None and st.button("Generar Código OTP"):
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
                    
                    with conn.session as s:
                        # 1. Descontar cupo
                        s.execute(text("UPDATE clientes SET cupo_disponible = cupo_disponible - :monto WHERE cedula = :cedula"), {"monto": monto_compra, "cedula": cedula})
                        # 2. Registrar solicitud
                        s.execute(text("""
                            INSERT INTO solicitudes (id, fecha, comercio, cedula_cliente, monto_compra, cuotas, valor_cuota, total_pagar, saldo_pendiente, estado) 
                            VALUES (:id, :fecha, :comercio, :cedula, :monto, :cuotas, :cuota, :total, :saldo, :est)
                        """), {"id": id_credito, "fecha": fecha_hoy, "comercio": comercio_sel, "cedula": cedula, "monto": monto_compra, "cuotas": cuotas, "cuota": valor_cuota, "total": total_pagar, "saldo": total_pagar, "est": "ACTIVO"})
                        s.commit()
                    
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
                with conn.session as s:
                    s.execute(text("""
                        INSERT INTO clientes (cedula, nombre, celular, ocupacion, ingresos, gastos, cupo_aprobado, cupo_disponible) 
                        VALUES (:ced, :nom, :cel, :ocu, :ing, :gas, :c_apr, :c_dis)
                    """), {"ced": c_cedula, "nom": c_nombre, "cel": c_celular, "ocu": c_ocupacion, "ing": c_ingresos, "gas": c_gastos, "c_apr": cupo_sugerido, "c_dis": cupo_sugerido})
                    s.commit()
                st.balloons()
                st.success(f"🎉 Cliente **{c_nombre}** registrado exitosamente con un cupo de **${cupo_sugerido:,.0f} Pesos**.")
            except IntegrityError:
                st.error("❌ Ya existe un cliente registrado con ese número de cédula.")
            except Exception as e:
                st.error(f"Error de base de datos: {e}")
        else:
            st.error("Por favor completa los campos básicos (Cédula, Nombre, Celular).")

# --- MÓDULO 3: REGISTRO DE PAGOS (SOLO ADMIN) ---
elif opcion == "3. Registrar Pagos / Abonar Cuotas" and es_admin:
    st.header("💵 Módulo de Recaudo / Abonar Cuotas")
    
    id_credito_buscar = st.text_input("Ingrese Número de Crédito o Cédula del Cliente")
    if id_credito_buscar:
        df_sol = conn.query("""
            SELECT s.id, s.fecha, s.comercio, c.nombre, s.cedula_cliente, s.valor_cuota, s.saldo_pendiente, s.estado 
            FROM solicitudes s
            JOIN clientes c ON s.cedula_cliente = c.cedula
            WHERE s.id = :termino OR s.cedula_cliente = :termino
        """, params={"termino": id_credito_buscar})
        
        if df_sol.empty:
            st.warning("No se encontraron créditos activos con esa búsqueda.")
        else:
            st.dataframe(df_sol, use_container_width=True)
            
            credito_sel = st.selectbox("Seleccione el Crédito a Abonar", df_sol['id'].tolist())
            fila_credito = df_sol[df_sol['id'] == credito_sel].iloc[0]
            
            saldo_act = float(fila_credito['saldo_pendiente'])
            vlr_cuota = float(fila_credito['valor_cuota'])
            
            monto_abono = st.number_input("Monto a Abonar ($ COP)", min_value=1000.0, max_value=saldo_act, value=float(min(vlr_cuota, saldo_act)))
            
            if st.button("Registrar Pago"):
                fecha_pago = datetime.now().strftime("%Y-%m-%d %H:%M")
                nuevo_saldo = saldo_act - monto_abono
                nuevo_estado = "CANCELADO" if nuevo_saldo <= 0 else "ACTIVO"
                
                with conn.session as s:
                    s.execute(text("INSERT INTO pagos (fecha, id_credito, monto_pagado) VALUES (:f, :id_c, :m)"), {"f": fecha_pago, "id_c": credito_sel, "m": monto_abono})
                    s.execute(text("UPDATE solicitudes SET saldo_pendiente = :ns, estado = :ne WHERE id = :id_c"), {"ns": nuevo_saldo, "ne": nuevo_estado, "id_c": credito_sel})
                    s.execute(text("UPDATE clientes SET cupo_disponible = cupo_disponible + :m WHERE cedula = :ced"), {"m": monto_abono, "ced": fila_credito['cedula_cliente']})
                    s.commit()
                
                st.success(f"✅ Pago de ${monto_abono:,.0f} Pesos registrado con éxito. Nuevo Saldo: ${nuevo_saldo:,.0f} Pesos")

# --- MÓDULO 4: GESTIÓN DE CLIENTES (SOLO ADMIN) ---
elif opcion == "4. Gestión General de Clientes" and es_admin:
    st.header("👥 Lista e Historial General de Clientes")
    df_cli = conn.query("SELECT cedula, nombre, celular, ocupacion, ingresos, gastos, cupo_aprobado, cupo_disponible FROM clientes")
    st.dataframe(df_cli, use_container_width=True)

# --- MÓDULO 5: GESTIÓN DE ALMACENES (SOLO ADMIN) ---
elif opcion == "5. Gestión de Almacenes Aliados" and es_admin:
    st.header("🏢 Administración de Comercios Aliados")
    st.markdown("Crea y gestiona el directorio de almacenes autorizados para otorgar créditos.")
    
    st.markdown("##### 📝 Formulario de Registro Comercial")
    col_a1, col_a2 = st.columns(2)
    with col_a1:
        nom_com = st.text_input("Nombre Comercial del Almacén *")
        nit_com = st.text_input("NIT / Cédula del Establecimiento *")
        prop_com = st.text_input("Nombre del Propietario / Rep. Legal")
    with col_a2:
        tel_com = st.text_input("Teléfono / Celular de Contacto")
        dir_com = st.text_input("Dirección Física")
        com_com = st.number_input("Porcentaje de Comisión (%) *", min_value=0.0, max_value=20.0, step=0.5, value=5.0)
        
    if st.button("Registrar Almacén Oficial"):
        if nom_com and nit_com:
            try:
                # Guardado con los nuevos datos de confianza
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
    st.subheader("📋 Directorio Oficial de Almacenes Afiliados")
    
    # Consulta con ttl=0 para que siempre muestre los datos actualizados en tiempo real
    df_com_all = conn.query("SELECT id, nit, nombre, propietario, telefono, direccion, comision FROM comercios", ttl=0)
    
    if not df_com_all.empty:
        st.dataframe(df_com_all, use_container_width=True, hide_index=True)
        
        # --- SECCIÓN DE BORRADO DE COMERCIOS ---
        st.markdown("---")
        st.subheader("🗑️ Eliminar un Comercio")
        
        # Creamos una lista bonita para el desplegable combinando Nombre y NIT
        opciones_borrar = dict(zip(df_com_all['id'], df_com_all['nombre'] + " (NIT: " + df_com_all['nit'].astype(str) + ")"))
        
        # Selector de comercio
        id_a_borrar = st.selectbox("Selecciona el comercio que deseas eliminar:", options=list(opciones_borrar.keys()), format_func=lambda x: opciones_borrar[x])
        
        # Botón de confirmación
        if st.button("❌ Borrar Comercio Definitivamente"):
            try:
                with conn.session as s:
                    # Ejecutamos el comando SQL para borrar por su ID único
                    s.execute(text("DELETE FROM comercios WHERE id = :id"), {"id": id_a_borrar})
                    s.commit()
                st.success("✅ Comercio eliminado correctamente del sistema.")
                st.rerun() # Recarga la pantalla al instante
            except Exception as e:
                st.error(f"Error al eliminar: {e}")

    else:
        st.info("Aún no hay comercios registrados con el nuevo formato.")

# --- MÓDULO 6: PANEL DE ADMINISTRACIÓN (SOLO ADMIN) ---
elif opcion == "6. Panel General de Administración" and es_admin:
    st.header("📈 Métricas Generales del Negocio")
    
    df_sol_all = conn.query("SELECT * FROM solicitudes")
    df_pag_all = conn.query("SELECT * FROM pagos")
    
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
        
        # --- MÓDULO 7: GESTIÓN DE USUARIOS (SOLO ADMIN) ---
elif opcion == "7. Gestión de Usuarios" and es_admin:
    st.header("👥 Administración de Usuarios del Sistema")
    st.markdown("Crea, modifica o elimina los accesos al sistema.")

# Consultar usuarios actuales en tiempo real
    try:
        df_usuarios = conn.query("SELECT id, documento, nombre, rol, pin FROM usuarios", ttl=0)
    except Exception as e:
        st.error("Error al cargar usuarios. Asegúrate de haber creado la tabla en Supabase.")
        df_usuarios = None

    if df_usuarios is not None:
        # Dividimos la pantalla en 3 pestañas para que quede súper profesional
        tab1, tab2, tab3 = st.tabs(["➕ Agregar Usuario", "✏️ Modificar Usuario", "🗑️ Eliminar Usuario"])

        # --- PESTAÑA 1: AGREGAR ---
        with tab1:
            st.subheader("Registrar Nuevo Acceso")
            col1, col2 = st.columns(2)
            with col1:
                nuevo_doc = st.text_input("Documento de Identidad (Cédula/NIT)")
                nuevo_nom = st.text_input("Nombre Completo o Razón Social")
            with col2:
                nuevo_rol = st.selectbox("Rol del Usuario", ["Comercio Aliado", "Administrador"])
                nuevo_pin = st.text_input("PIN de Acceso (Contraseña)", type="password")

            if st.button("Guardar Nuevo Usuario"):
                if nuevo_doc and nuevo_nom and nuevo_pin:
                    try:
                        with conn.session as s:
                            s.execute(text("""
                                INSERT INTO usuarios (documento, nombre, rol, pin) 
                                VALUES (:doc, :nom, :rol, :pin)
                            """), {"doc": nuevo_doc, "nom": nuevo_nom, "rol": nuevo_rol, "pin": nuevo_pin})
                            s.commit()
                        st.success("✅ Usuario creado con éxito.")
                        st.rerun()
                    except IntegrityError:
                        st.error("❌ Ya existe un usuario registrado con ese documento.")
                else:
                    st.warning("⚠️ Debes completar todos los campos.")

        # --- PESTAÑA 2: MODIFICAR ---
        with tab2:
            st.subheader("Actualizar Datos de Usuario")
            if not df_usuarios.empty:
                opciones_mod = dict(zip(df_usuarios['id'], df_usuarios['nombre'] + " (" + df_usuarios['rol'] + ")"))
                id_mod = st.selectbox("Selecciona el usuario a modificar:", options=list(opciones_mod.keys()), format_func=lambda x: opciones_mod[x])
                
                usr_actual = df_usuarios[df_usuarios['id'] == id_mod].iloc[0]
                
                col3, col4 = st.columns(2)
                with col3:
                    mod_doc = st.text_input("Documento", value=usr_actual['documento'])
                    mod_nom = st.text_input("Nombre", value=usr_actual['nombre'])
                with col4:
                    roles = ["Comercio Aliado", "Administrador"]
                    idx_rol = roles.index(usr_actual['rol']) if usr_actual['rol'] in roles else 0
                    mod_rol = st.selectbox("Nuevo Rol", roles, index=idx_rol)
                    mod_pin = st.text_input("Cambiar PIN (Dejar igual si no cambia)", value=usr_actual['pin'], type="password")

                if st.button("💾 Guardar Cambios"):
                    with conn.session as s:
                        s.execute(text("""
                            UPDATE usuarios 
                            SET documento = :doc, nombre = :nom, rol = :rol, pin = :pin 
                            WHERE id = :id
                        """), {"doc": mod_doc, "nom": mod_nom, "rol": mod_rol, "pin": mod_pin, "id": id_mod})
                        s.commit()
                    st.success("✅ Datos actualizados correctamente.")
                    st.rerun()
            else:
                st.info("Aún no hay usuarios para modificar.")

        # --- PESTAÑA 3: ELIMINAR ---
        with tab3:
            st.subheader("Borrar Acceso del Sistema")
            if not df_usuarios.empty:
                opciones_del = dict(zip(df_usuarios['id'], df_usuarios['nombre'] + " - " + df_usuarios['documento'].astype(str)))
                id_del = st.selectbox("Selecciona el usuario que deseas eliminar:", options=list(opciones_del.keys()), format_func=lambda x: opciones_del[x])
                
                if st.button("❌ Borrar Usuario Definitivamente", type="primary"):
                    with conn.session as s:
                        s.execute(text("DELETE FROM usuarios WHERE id = :id"), {"id": id_del})
                        s.commit()
                    st.success("✅ Usuario eliminado permanentemente.")
                    st.rerun()
            else:
                st.info("Aún no hay usuarios para eliminar.")

        st.markdown("---")
        st.subheader("📋 Lista Actual de Usuarios")
        if not df_usuarios.empty:
            # Mostramos la tabla SIN el PIN por seguridad
            st.dataframe(df_usuarios[['documento', 'nombre', 'rol']], use_container_width=True, hide_index=True)
    

   
