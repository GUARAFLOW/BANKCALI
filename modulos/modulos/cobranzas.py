import streamlit as st

try:
  from modulos.database import conn, enviar_sms_twilio
except ImportError:
  from database import conn, enviar_sms_twilio


def render_control_cartera(es_admin):
  if not es_admin:
    st.warning("⚠️ No tienes permisos para acceder a este módulo.")
    return

  st.header("📋 Control de Cartera y Gestión de Cobranzas")
  st.markdown("Monitoreo de saldos pendientes y envío de recordatorios SMS.")
  st.markdown("---")

  df_cartera = conn.query(
      """
        SELECT s.id, s.fecha, s.comercio, c.nombre, c.cedula, c.celular, s.total_pagar, s.saldo_pendiente, s.estado
        FROM solicitudes s
        JOIN clientes c ON s.cedula_cliente = c.cedula
        WHERE s.saldo_pendiente > 0
        ORDER BY s.fecha ASC
    """,
      ttl=0,
  )

  if df_cartera.empty:
    st.info("🎉 No hay créditos pendientes de pago en cartera.")
  else:
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Créditos Activos", len(df_cartera))
    m2.metric(
        "Monto Total Otorgado", f"${df_cartera['total_pagar'].sum():,.0f} COP"
    )
    m3.metric(
        "Saldo Pendiente Recaudo",
        f"${df_cartera['saldo_pendiente'].sum():,.0f} COP",
    )

    st.markdown("---")
    st.subheader("📑 Créditos Activos")
    st.dataframe(df_cartera, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("📲 Envío de Recordatorio Colectivo / Individual")
    credito_recordatorio = st.selectbox(
        "Seleccione Crédito para Enviar Recordatorio",
        df_cartera["id"].tolist(),
    )
    fila_rec = df_cartera[df_cartera["id"] == credito_recordatorio].iloc[0]

    if st.button("📩 Enviar Recordatorio por SMS", use_container_width=True):
      msg_rec = (
          f"BankCali: Estimado(a) {fila_rec['nombre']}, le recordamos su cuota"
          f" pendiente para el credito {fila_rec['id']}. Saldo actual:"
          f" ${fila_rec['saldo_pendiente']:,.0f} COP. Favor ponerse al dia."
      )
      exito, res = enviar_sms_twilio(
          fila_rec["celular"], mensaje_custom=msg_rec
      )
      if exito:
        st.success(
            f"📱 Recordatorio enviado con éxito al celular {fila_rec['celular']}"
        )
      else:
        st.error(f"Error al enviar SMS: {res}")
