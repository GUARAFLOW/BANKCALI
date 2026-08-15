import streamlit as st
from sqlalchemy import text

try:
  from modulos.database import conn
except ImportError:
  from database import conn


def render_gestion_usuarios(es_admin):
  if not es_admin:
    st.warning("⚠️ No tienes permisos para acceder a este módulo.")
    return

  st.header("👤 Control de Usuarios y Roles")
  st.markdown("Gestión de credenciales, roles de acceso y comercios asignados.")
  st.markdown("---")

  df_comercios = conn.query("SELECT nombre FROM comercios", ttl=0)
  lista_comercios = (
      df_comercios["nombre"].tolist() if not df_comercios.empty else []
  )

  col_u1, col_u2 = st.columns(2)

  with col_u1:
    st.subheader("➕ Crear Nuevo Usuario")
    with st.form("form_nuevo_usuario"):
      nuevo_user = st.text_input("Nombre de Usuario (Login)")
      nuevo_pass = st.text_input("Contraseña", type="password")
      nuevo_rol = st.selectbox(
          "Rol de Sistema", ["ADMINISTRADOR", "COMERCIO_ALIADO"]
      )

      comercio_asig = None
      if nuevo_rol == "COMERCIO_ALIADO":
        comercio_asig = st.selectbox(
            "Comercio Asignado",
            lista_comercios
            if lista_comercios
            else ["Sin comercios creados"],
        )

      btn_crear_u = st.form_submit_button("💾 Guardar Usuario")

      if btn_crear_u and nuevo_user and nuevo_pass:
        try:
          with conn.session as s:
            s.execute(
                text("""
                    INSERT INTO usuarios (usuario, password, rol, comercio_asociado)
                    VALUES (:usr, :pwd, :rol, :com)
                """),
                {
                    "usr": nuevo_user.strip(),
                    "pwd": nuevo_pass.strip(),
                    "rol": nuevo_rol,
                    "com": comercio_asig,
                },
            )
            s.commit()
          st.success(f"✅ Usuario '{nuevo_user}' creado exitosamente.")
          st.rerun()
        except Exception as e:
          st.error(f"Error creando usuario: {e}")

  with col_u2:
    st.subheader("👥 Usuarios del Sistema")
    df_users = conn.query(
        "SELECT id, usuario, rol, comercio_asociado FROM usuarios", ttl=0
    )
    if not df_users.empty:
      st.dataframe(df_users, use_container_width=True, hide_index=True)
    else:
      st.info("No hay usuarios registrados.")
