import streamlit as st
import pandas as pd
import random
import requests
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# Configuración de página
st.set_page_config(
    page_title="Crédito Puerto Rico | Plataforma Financiera",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- ESTILOS CSS ---
st.markdown("""
    <style>
        .corporate-banner { padding: 30px; background: linear-gradient(135deg, #0A192F 0%, #1E3A8A 100%); color: white; border-radius: 12px; margin-bottom: 25px; text-align: center; }
    </style>
""", unsafe_allow_html=True)

# --- FUNCIÓN DE SCORING ACTUALIZADA ---
def evaluar_riesgo_y_cupo(ingresos, gastos):
    pct_gastos = (gastos / ingresos) if ingresos > 0 else 1
    
    # RANGO 1: 100,000 a 1,000,000
    if 100000 <= ingresos <= 1000000:
        if pct_gastos <= 0.35:
            cupo = 80000
            estado = "APROBADO"
        else:
            cupo = 0
            estado = "RECHAZADO"
            
    # RANGO 2: 1,000,001 a 2,500,000
    elif 1000001 <= ingresos <= 2500000:
        margen_disponible = ingresos - gastos
        if margen_disponible < 0:
            cupo = 0
            estado = "RECHAZADO"
        else:
            cupo = round((margen_disponible * 0.25) / 10000) * 10000
            estado = "APROBADO" if cupo > 0 else "RECHAZADO"
            
    # RANGO 3: > 2,500,001
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

# --- CONEXIÓN ---
conn = st.connection("supabase", type="sql")

# --- LOGIN ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if not st.session_state.autenticado:
    st.sidebar.title("Login")
    doc = st.sidebar.text_input("Documento")
    pin = st.sidebar.text_input("PIN", type="password")
    if st.sidebar.button("Entrar"):
        usuario = conn.query("SELECT nombre, rol FROM usuarios WHERE documento = :doc AND pin = :pin", params={"doc": doc, "pin": pin})
        if not usuario.empty:
            st.session_state.update({"autenticado": True, "nombre": usuario.iloc[0]['nombre'], "rol": usuario.iloc[0]['rol']})
            st.rerun()
    st.stop()

# --- SESIÓN ACTIVA ---
es_admin = (st.session_state.rol == "Administrador")
st.sidebar.success(f"Sesión: {st.session_state.nombre}")
if st.sidebar.button("Cerrar Sesión"):
    st.session_state.autenticado = False
    st.rerun()

menu_opciones = ["1. Simular / Solicitar Crédito (POS)", "2. Registrar Nuevo Cliente + Scoring"]
if es_admin:
    menu_opciones.extend(["3. Registrar Pagos", "4. Gestión Clientes", "5. Almacenes", "6. Panel Admin", "7. Usuarios"])

opcion = st.sidebar.selectbox("Módulo", menu_opciones)

# --- VISTAS ---
if opcion == "2. Registrar Nuevo Cliente + Scoring":
    st.header("📝 Evaluación y Registro")
    
    # MENSAJE SOLO PARA ADMIN
    if es_admin:
        st.info("💡 **Política de Crédito:** Scoring automatizado basado en ingresos y capacidad de gasto (gastos vs ingresos).")
    
    col1, col2 = st.columns(2)
    with col1:
        c_cedula = st.text_input("Cédula *")
        c_nombre = st.text_input("Nombre *")
    with col2:
        c_ingresos = st.number_input("Ingresos Mensuales", value=1000000)
        c_gastos = st.number_input("Gastos Mensuales", value=400000)
    
    # LLAMADO A LA FUNCIÓN CON GASTOS
    cupo_sugerido, nivel_riesgo, mensaje_eval = evaluar_riesgo_y_cupo(c_ingresos, c_gastos)
    
    st.metric("Cupo Asignado", f"${cupo_sugerido:,.0f} COP")
    st.write(mensaje_eval)

    if st.button("Registrar Cliente"):
        with conn.session as s:
            s.execute(text("INSERT INTO clientes (cedula, nombre, ingresos, gastos, cupo_aprobado, cupo_disponible) VALUES (:ced, :nom, :ing, :gas, :cup, :cup)"), 
                      {"ced": c_cedula, "nom": c_nombre, "ing": c_ingresos, "gas": c_gastos, "cup": cupo_sugerido})
            s.commit()
        st.success("Cliente guardado")
