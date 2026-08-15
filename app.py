import streamlit as st
from sqlalchemy import text

# Importar módulos independientes desde la carpeta modulos
from modulos.clientes import render_gestion_clientes
from modulos.cobranzas import render_control_cartera
from modulos.comercios import render_gestion_comercios
from modulos.database import conn
from modulos.dashboard import render_dashboard
from modulos.pagos import render_registro_pagos
from modulos.simulador import render_aprobacion_creditos, render_simulador
from modulos.usuarios import render_gestion_usuarios

# Configuración general de la aplicación
st.set_page_config(
    page_title="BankCali - Sistema de Créditos", page_icon="💳", layout="wide"
)

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
  st.title("🔐 Sistema de Gestión de Créditos - BankCali")
  st.markdown("Ingrese sus credenciales para acceder a la plataforma.")

  col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
  with col_l2:
    with st.form("login_form"):
      user_input = st.text_input("Usuario")
      pass_input = st.text_input("Contraseña", type="password")
      btn_login = st.form_submit_button("Ingresar", use_container_width=True)

      if btn_login:
        df_user = conn.query(
            "SELECT * FROM usuarios WHERE usuario = :u AND password = :p",
            params={"u": user_input.strip(), "p": pass_input.strip()},
            ttl=0,
        )

        if not df_user.empty:
          usr_data = df_user.iloc[0]
          st.session_state["autenticado"] = True
          st.session_state["usuario"] = usr_data["usuario"]
          st.session_state["rol"] = usr_data["rol"]
          st.session_state["comercio"] = usr_data.get("comercio_asociado", "")
          st.success("¡Autenticación exitosa!")
          st.rerun()
        else:
          st.error("❌ Credenciales incorrectas.")
  st.stop()

# -----------------------------------------------------------------------------
# MENÚ LATERAL Y NAVEGACIÓN
# -----------------------------------------------------------------------------
es_admin = st.session_state["rol"] == "ADMINISTRADOR"

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
