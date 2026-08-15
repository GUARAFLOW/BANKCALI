import os
import sys
import streamlit as st
from sqlalchemy import text

# Importaciones limpias desde la carpeta modulos
from modulos.clientes import render_gestion_clientes
from modulos.cobranzas import render_control_cartera
from modulos.comercios import render_gestion_comercios
from modulos.database import conn
from modulos.dashboard import render_dashboard
from modulos.pagos import render_registro_pagos
from modulos.simulador import render_aprobacion_creditos, render_simulador
from modulos.usuarios import render_gestion_usuarios

# Configuración general de la página
st.set_page_config(
    page_title="BankCali - Sistema de Créditos", page_icon="💳", layout="wide"
)


# Búsqueda dinámica del archivo de logo
def obtener_ruta_logo():
  posibles_nombres = [
      "LOGOBANKCALI.jpeg",
      "logobankcali.jpeg",
      "logobankcali.jpeg.jpeg",
  ]
  for nombre in posibles_nombres:
    if os.path.exists(nombre):
      return nombre
  return None


ruta_logo = obtener_ruta_logo()

# Inicialización del estado de sesión
if "autenticado" not in st.session_state:
  st.session_state["autenticado"] = False
  st.session_state["usuario"] = ""
  st.session_state["rol"] = ""
  st.session_state["comercio"] = ""

# -----------------------------------------------------------------------------
# PANTALLA DE AUTENTICACIÓN / LOGIN
# -----------------------------------------------------------------------------
if not st.session_state["autenticado"]:
  col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
  with col_l2:
    if ruta_logo:
      st.image(ruta_logo, use_container_width=True)

    st.markdown(
        "<h2 style='text-align: center;'>🔐 Sistema de Créditos - BankCali</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align: center; color: gray;'>Ingrese sus credenciales"
        " para acceder a la plataforma.</p>",
        unsafe_allow_html=True,
    )

    with st.form("login_form"):
      user_input = st.text_input("Usuario")
      pass_input = st.text_input("Contraseña", type="password")
      btn_login = st.form_submit_button("Ingresar", use_container_width=True)

      if btn_login:
        try:
          with conn.session as session:
            # Inspección dinámica de columnas de la tabla usuarios
            sample = session.execute(
                text("SELECT * FROM usuarios LIMIT 1")
            ).mappings()
            columnas = list(sample.keys()) if sample.keys() else []

            # Detección inteligente del nombre de columna para usuario y contraseña
            col_usr = next(
                (
                    c
                    for c in columnas
                    if c.lower() in ["usuario", "username", "usr", "login"]
                ),
                columnas[1] if len(columnas) > 1 else "usuario",
            )
            col_pwd = next(
                (
                    c
                    for c in columnas
                    if c.lower()
                    in ["password", "contrasena", "clave", "pass"]
                ),
                columnas[2] if len(columnas) > 2 else "password",
            )

            sql_str = f'SELECT * FROM usuarios WHERE "{col_usr}" = :u AND "{col_pwd}" = :p'
            res = session.execute(
                text(sql_str), {"u": user_input.strip(), "p": pass_input.strip()}
            ).mappings().all()

          if len(res) > 0:
            usr_data = res[0]
            st.session_state["autenticado"] = True
            st.session_state["usuario"] = usr_data.get(
                col_usr, user_input.strip()
            )
            st.session_state["rol"] = usr_data.get("rol", "ADMINISTRADOR")
            st.session_state["comercio"] = (
                usr_data.get("comercio_asociado", "") or ""
            )
            st.success("¡Autenticación exitosa!")
            st.rerun()
          else:
            st.error("❌ Credenciales incorrectas.")
        except Exception as e:
          st.error(f"Error al verificar credenciales: {e}")
  st.stop()

# -----------------------------------------------------------------------------
# MENÚ LATERAL Y NAVEGACIÓN
# -----------------------------------------------------------------------------
es_admin = st.session_state["rol"] == "ADMINISTRADOR"

if ruta_logo:
  st.sidebar.image(ruta_logo, use_container_width=True)

st.sidebar.title("💳 BankCali")
st.sidebar.markdown(f"**Usuario:** {st.session_state['usuario']}")
st.sidebar.markdown(f"**Rol:** {st.session_state['rol']}")
if not es_admin and st.session_state["comercio"]:
  st.sidebar.markdown(f"**Comercio:** {st.session_state['comercio']}")
st.sidebar.markdown("---")

if es_admin:
  opciones_menu = [
      "🧮 Simulador y Solicitud",
      "✅ Aprobación de Créditos",
      "💳 Registro de Pagos",
      "📋 Control de Cartera",
      "👥 Gestión de Clientes",
      "🏪 Comercios Aliados",
      "📈 Panel Dashboard",
      "👤 Usuarios y Roles",
  ]
else:
  opciones_menu = ["🧮 Simulador y Solicitud", "💳 Registro de Pagos"]

opcion = st.sidebar.radio("Navegación", opciones_menu)

if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
  st.session_state["autenticado"] = False
  st.session_state["usuario"] = ""
  st.session_state["rol"] = ""
  st.session_state["comercio"] = ""
  st.rerun()

# -----------------------------------------------------------------------------
# RUTEO DE MÓDULOS
# -----------------------------------------------------------------------------
if opcion == "🧮 Simulador y Solicitud":
  render_simulador(es_admin, st.session_state["comercio"])
elif opcion == "✅ Aprobación de Créditos":
  render_aprobacion_creditos()
elif opcion == "💳 Registro de Pagos":
  render_registro_pagos()
elif opcion == "📋 Control de Cartera":
  render_control_cartera(es_admin)
elif opcion == "👥 Gestión de Clientes":
  render_gestion_clientes(es_admin)
elif opcion == "🏪 Comercios Aliados":
  render_gestion_comercios(es_admin)
elif opcion == "📈 Panel Dashboard":
  render_dashboard(es_admin)
elif opcion == "👤 Usuarios y Roles":
  render_gestion_usuarios(es_admin)
