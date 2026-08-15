import streamlit as st
from sqlalchemy import text

try:
  from modulos.database import conn, enviar_sms_twilio
except ImportError:
  from database import conn, enviar_sms_twilio


def render_registro_pagos():
  st.header("💳 Registro de Pagos y Liberación de Cupo")
  st.markdown(
      "Abona a las cuotas de un crédito activo para liberar cupo disponible al"
      " cliente."
  )
  st.markdown("---")

  # Consultar créditos con saldo pendiente
  df_creditos = conn.query(
      """
        SELECT s.id, s.fecha, s.cedula_cliente, c.nombre, c.celular, s.comercio, s.monto_compra, s.cuota_mensual, s.saldo_pendiente, c.cupo_aprobado, c.cupo_disponible
        FROM solicitudes s
        JOIN clientes c ON s.cedula_cliente = c.cedula
        WHERE s.saldo_pendiente > 0 AND s.estado IN ('ACTIVO', 'PENDIENTE')
        ORDER BY s.fecha DESC
    """,
      ttl=0,
  )

  if df_creditos.empty:
    st.info("🎉 No hay créditos activos con saldos pendientes por pagar.")
    return

  credito_sel = st.selectbox(
      "Seleccione el ID del Crédito a Procesar Pago",
      df_creditos["id"].tolist(),
  )

  fila_credito = df_creditos[df_creditos["id"] == credito_sel].iloc[0]
  saldo_act = float(fila_credito["saldo_pendiente"])
  vlr_cuota = float(fila_credito["cuota_mensual"])
  celular_cli = fila_credito["celular"]

  st.markdown(
      f"### 👤 Cliente: {fila_credito['nombre']} (C.C."
      f" {fila_credito['cedula_cliente']})"
  )
  st.markdown(
      f"**Comercio:** {fila_credito['comercio']} | **Monto Original:**"
      f" ${fila_credito['monto_compra']:,.0f} COP"
  )

  col_p1, col_p2 = st.columns(2)
  with col_p1:
    st.info(
        f"💰 **Saldo Pendiente:** ${saldo_act:,.0f} COP\n\n"
        f"📌 **Valor Cuota Mensual:** ${vlr_cuota:,.0f} COP"
    )
  with col_p2:
    monto_pago = st.number_input(
        "Monto a Abonar ($ COP)",
        min_value=1000,
        max_value=int(saldo_act) if saldo_act > 0 else 1000,
        step=5000,
        value=int(min(vlr_cuota, saldo_act)) if saldo_act > 0 else 1000,
    )

  if st.button("💵 Registrar Pago y Liberar Cupo", use_container_width=True):
    if monto_pago > 0:
      nuevo_saldo = max(0.0, saldo_act - monto_pago)
      nuevo_estado = "CANCELADO" if nuevo_saldo == 0 else "ACTIVO"

      try:
        with conn.session as s:
          s.execute(
              text("""
                  UPDATE solicitudes 
                  SET saldo_pendiente = :nuevo_saldo, estado = :nuevo_estado 
                  WHERE id = :id
              """),
              {
                  "nuevo_saldo": nuevo_saldo,
                  "nuevo_estado": nuevo_estado,
                  "id": credito_sel,
              },
          )
          s.execute(
              text("""
                  UPDATE clientes 
                  SET cupo_disponible = LEAST(cupo_aprobado, cupo_disponible + :monto) 
                  WHERE cedula = :ced
              """),
              {"monto": monto_pago, "ced": fila_credito["cedula_cliente"]},
          )
          s.commit()

        msg_pago = (
            f"BankCali: Recibimos su abono de ${monto_pago:,.0f} COP para el"
            f" credito {credito_sel}. Saldo pendiente: ${nuevo_saldo:,.0f}"
            " COP. Cupo restablecido."
        )
        enviar_sms_twilio(celular_cli, mensaje_custom=msg_pago)

        st.success(
            f"✅ Pago registrado exitosamente. Nuevo saldo:"
            f" **${nuevo_saldo:,.0f} COP**"
        )
        st.rerun()
      except Exception as e:
        st.error(f"Error al registrar el pago: {e}")
