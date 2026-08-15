import base64
import streamlit as st
from sqlalchemy import text

try:
  from modulos.database import conn
except ImportError:
  from database import conn


def render_gestion_comercios(es_admin):
  if not es_admin:
    st.warning("⚠️ No tienes permisos para acceder a este módulo.")
    return

  st.header("🏪 Gestión de Comercios Aliados")
  st.markdown(
      "Registro de tiendas, porcentaje de comisión y carga de logos en Base64."
  )
  st.markdown("---")

  col_com1, col_com2 = st.columns(2)
  with col_com1:
    st.subheader("➕ Registrar Nuevo Comercio")
    nom_comercio = st.text_input("Nombre del Comercio")
    comision_comercio = st.number_input(
        "Comisión (%)", min_value=0.0, max_value=30.0, value=5.0, step=0.5
    )
    logo_file = st.file_uploader(
        "Logo del Comercio (Imagen)", type=["png", "jpg", "jpeg"]
    )

    logo_b64 = None
    if logo_file:
      bytes_data = logo_file.getvalue()
      ext = logo_file.name.split(".")[-1].lower()
      logo_b64 = (
          f"data:image/{ext};base64,{base64.b64encode(bytes_data).decode()}"
      )

    if st.button("💾 Guardar Comercio", use_container_width=True):
      if nom_comercio.strip():
        try:
          with conn.session as s:
            s.execute(
                text("""
                    INSERT INTO comercios (nombre, comision, logo_base64)
                    VALUES (:nom, :com, :logo)
                """),
                {
                    "nom": nom_comercio,
                    "com": comision_comercio,
                    "logo": logo_b64,
                },
            )
            s.commit()
          st.success(f"✅ Comercio '{nom_comercio}' registrado exitosamente.")
          st.rerun()
        except Exception as e:
          st.error(f"Error registrando comercio: {e}")
      else:
        st.warning("Escriba el nombre del comercio.")

  with col_com2:
    st.subheader("🏬 Comercios Registrados")
    df_com = conn.query("SELECT * FROM comercios", ttl=0)
    if not df_com.empty:
      st.dataframe(
          df_com[["nombre", "comision"]],
          use_container_width=True,
          hide_index=True,
      )
    else:
      st.info("No hay comercios registrados.")
