import streamlit as st
from sqlalchemy import text

try:
  from modulos.database import conn
except ImportError:
  from database import conn


def render_gestion_clientes(es_admin):
  if not es_admin:
    st.warning("⚠️ No tienes permisos para acceder a este módulo.")
    return

  st.header("👥 Gestión de Clientes Registrados")
  st.markdown(
      "Consulta, modificación de cupos aprobados y estado de clientes."
  )
  st.markdown("---")

  df_clientes = conn.query("SELECT * FROM clientes", ttl=0)

  if df_clientes.empty:
    st.warning("⚠️ No hay clientes registrados.")
  else:
    st.dataframe(df_clientes, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("⚙️ Ajuste Manual de Cupo Crédito")
    cedula_mod = st.selectbox(
        "Seleccione Cédula de Cliente", df_clientes["cedula"].tolist()
    )
    cliente_sel = df_clientes[df_clientes["cedula"] == cedula_mod].iloc[0]

    nuevo_cupo_apr = st.number_input(
        "Nuevo Cupo Aprobado ($ COP)",
        min_value=0,
        max_value=20000000,
        step=50000,
        value=int(cliente_sel["cupo_aprobado"]),
    )

    if st.button("💾 Actualizar Cupo", use_container_width=True):
      diferencia = nuevo_cupo_apr - float(cliente_sel["cupo_aprobado"])
      nuevo_disponible = max(
          0.0, float(cliente_sel["cupo_disponible"]) + diferencia
      )

      try:
        with conn.session as s:
          s.execute(
              text("""
                    UPDATE clientes 
                    SET cupo_aprobado = :apr, cupo_disponible = :dis 
                    WHERE cedula = :ced
                """),
              {
                  "apr": nuevo_cupo_apr,
                  "dis": nuevo_disponible,
                  "ced": cedula_mod,
              },
          )
          s.commit()
        st.success("✅ Cupo actualizado con éxito.")
        st.rerun()
      except Exception as e:
        st.error(f"Error al actualizar cupo: {e}")
