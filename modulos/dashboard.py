import streamlit as st

try:
  import plotly.express as px

  HAS_PLOTLY = True
except ImportError:
  HAS_PLOTLY = False

try:
  from modulos.database import conn
except ImportError:
  from database import conn


def render_dashboard(es_admin):
  if not es_admin:
    st.warning("⚠️ No tienes permisos para acceder a este módulo.")
    return

  st.header("📈 Panel General de Administración")
  st.markdown("Métricas generales de rendimiento y colocación de crédito.")
  st.markdown("---")

  df_sol = conn.query("SELECT * FROM solicitudes", ttl=0)
  df_cli = conn.query("SELECT * FROM clientes", ttl=0)

  if df_sol.empty:
    st.info("No hay datos de operaciones financieras grabadas aún.")
    return

  kpi1, kpi2, kpi3, kpi4 = st.columns(4)
  kpi1.metric("Total Clientes", len(df_cli))
  kpi2.metric("Total Solicitudes", len(df_sol))
  kpi3.metric("Monto Colocado", f"${df_sol['monto_compra'].sum():,.0f} COP")
  kpi4.metric(
      "Cartera Pendiente", f"${df_sol['saldo_pendiente'].sum():,.0f} COP"
  )

  st.markdown("---")

  if HAS_PLOTLY:
    col_g1, col_g2 = st.columns(2)
    with col_g1:
      fig_com = px.bar(
          df_sol,
          x="comercio",
          y="monto_compra",
          title="Ventas Colocadas por Comercio",
          color="comercio",
      )
      st.plotly_chart(fig_com, use_container_width=True)

    with col_g2:
      fig_est = px.pie(
          df_sol,
          names="estado",
          values="monto_compra",
          title="Distribución por Estado de Crédito",
      )
      st.plotly_chart(fig_est, use_container_width=True)
  else:
    st.subheader("Resumen por Comercio")
    st.dataframe(
        df_sol.groupby("comercio")["monto_compra"].sum().reset_index(),
        use_container_width=True,
    )
