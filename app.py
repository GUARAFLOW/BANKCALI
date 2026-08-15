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

# =============================================================================
# CONEXIÓN Y MIGRACIÓN AUTOMÁTICA DE BASE DE DATOS Y USUARIOS
# =============================================================================
conn = st.connection("supabase", type="sql")

try:
  with conn.session as s:
    # 1. Asegurar la existencia de la tabla usuarios
    s.execute(
        text("""
            CREATE TABLE IF NOT EXISTS usuarios (
                documento TEXT PRIMARY KEY,
                pin TEXT NOT NULL,
                nombre TEXT NOT NULL,
                rol TEXT NOT NULL,
                comercio_asignado TEXT
            );
        """)
    )

    # 2. Asegurar la columna de logo en comercios
    s.execute(
        text("ALTER TABLE comercios ADD COLUMN IF NOT EXISTS logo_base64 TEXT;")
    )

    s.commit()

    # 3. Verificar si no existen usuarios y crear el administrador por defecto
    res_user = s.execute(text("SELECT COUNT(*) FROM usuarios")).fetchone()
    if res_user and res_user[0] == 0:
      s.execute(
          text("""
                INSERT INTO usuarios (documento, pin, nombre, rol, comercio_asignado)
                VALUES ('123456789', '1234', 'Administrador Inicial', 'Administrador', 'N/A - Administrador');
            """)
      )
      s.commit()
except Exception as e:
  print(f"Error en la migración/inicialización de base de datos: {e}")

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
      user_input = st.text_input("Usuario / Cédula")
      pass_input = st.text_input("Contraseña", type="password")
      btn_login = st.form_submit_button("Ingresar", use_container_width=True)

      if btn_login:
        try:
          with conn.session as session:
            # Trae los registros de la tabla usuarios
            rows = (
                session.execute(text("SELECT * FROM usuarios"))
                .mappings()
                .all()
            )

          if not rows:
            st.error("⚠️ La tabla 'usuarios' está vacía en la base de datos.")
          else:
            autenticado = False
            for row in rows:
              u_data = {str(k).lower(): str(v).strip() for k, v in row.items()}

              # Identifica la columna del usuario (cedula, usuario, username)
              val_usr = (
                  u_data.get("cedula")
                  or u_data.get("usuario")
                  or u_data.get("username")
                  or u_data.get("user")
                  or ""
              )

              # Identifica la columna de clave (password, contrasena, clave)
              val_pwd = (
                  u_data.get("password")
                  or u_data.get("contrasena")
                  or u_data.get("clave")
                  or u_data.get("pass")
                  or ""
              )

              if val_usr == user_input.strip() and val_pwd == pass_input.strip():
                st.session_state["autenticado"] = True
                st.session_state["usuario"] = u_data.get(
                    "nombre", user_input.strip()
                )
                st.session_state["rol"] = u_data.get(
                    "rol", "ADMINISTRADOR"
                ).upper()
                st.session_state["comercio"] = (
                    u_data.get("comercio_asociado", "") or ""
                )
                autenticado = True
                st.success("¡Autenticación exitosa!")
                st.rerun()
                break

            if not autenticado:
              st.error(
                  "❌ Credenciales incorrectas. Verifique el usuario/cédula y la"
                  " contraseña."
              )

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
