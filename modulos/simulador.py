import math
import streamlit as st
from sqlalchemy import text

try:
  from modulos.database import conn, enviar_sms_twilio
except ImportError:
  from database import conn, enviar_sms_twilio


def render_simulador(es_admin, usuario_comercio):
  st.header("🧮 Simulador y Solicitud de Crédito")
  st.markdown("Evalúa la capacidad de pago del cliente e inicia la solicitud.")
  st.markdown("---")

  # Formulario de simulación
  col1, col2 = st.columns(2)
  with col1:
    cedula = st.text_input("Número de Cédula del Cliente")
    monto = st.number_input(
        "Monto de la Compra ($ COP)",
        min_value=50000,
        max_value=10000000,
        step=50000,
        value=200000,
    )
    plazo = st.selectbox("Plazo en Meses", [1, 2, 3, 4, 6, 12], index=2)

  with col2:
    tasa_interes = st.number_input(
        "Tasa Interés Mensual (%)",
        min_value=0.0,
        max_value=5.0,
        value=2.2,
        step=0.1,
    )

    # Cálculo de cuota fija (método francés)
    i = tasa_interes / 100
    if i > 0:
      cuota = monto * (i * (1 + i) ** plazo) / (((1 + i) ** plazo) - 1)
    else:
      cuota = monto / plazo

    total_pagar = cuota * plazo

    st.info(f"""
        📌 **Resumen de la Simulación:**
        - **Valor Cuota Mensual:** ${cuota:,.0f} COP
        - **Total a Pagar:** ${total_pagar:,.0f} COP
        """)

  # Búsqueda o registro de cliente
  if cedula:
    res_cli = conn.query(
        text("SELECT * FROM clientes WHERE cedula = :ced"),
        params={"ced": cedula},
        ttl=0,
    )

    if res_cli.empty:
      st.warning(
          "⚠️ Cliente no encontrado en el sistema. Registre los datos"
          " iniciales:"
      )
      with st.form("form_nuevo_cliente"):
        nombre = st.text_input("Nombre Completo")
        celular = st.text_input("Número de Celular")
        cupo_solicitado = st.number_input(
            "Cupo Aprobado Inicial ($ COP)",
            min_value=100000,
            value=1000000,
            step=100000,
        )
        btn_guardar = st.form_submit_button("Registrar Cliente")

        if btn_guardar and nombre and celular:
          try:
            with conn.session as s:
              s.execute(
                  text("""
                          INSERT INTO clientes (cedula, nombre, celular, cupo_aprobado, cupo_disponible)
                          VALUES (:ced, :nom, :cel, :cupo, :cupo)
                      """),
                  {
                      "ced": cedula,
                      "nom": nombre,
                      "cel": celular,
                      "cupo": cupo_solicitado,
                  },
              )
              s.commit()
            st.success("✅ Cliente registrado con éxito.")
            st.rerun()
          except Exception as e:
            st.error(f"Error al registrar cliente: {e}")
    else:
      cliente = res_cli.iloc[0]
      st.success(
          f"👤 **Cliente:** {cliente['nombre']} | **Cupo Disponible:**"
          f" ${cliente['cupo_disponible']:,.0f} COP"
      )

      if monto > cliente["cupo_disponible"]:
        st.error(
            "❌ El monto solicitado supera el cupo disponible del cliente."
        )
      else:
        comercio_final = (
            usuario_comercio if not es_admin else "Administración / Directo"
        )

        if st.button(
            "🚀 Radicar Solicitud de Crédito", use_container_width=True
        ):
          try:
            with conn.session as s:
              s.execute(
                  text("""
                          INSERT INTO solicitudes (cedula_cliente, comercio, monto_compra, plazo_meses, cuota_mensual, total_pagar, saldo_pendiente, estado)
                          VALUES (:ced, :com, :monto, :plazo, :cuota, :total, :total, 'PENDIENTE')
                      """),
                  {
                      "ced": cedula,
                      "com": comercio_final,
                      "monto": monto,
                      "plazo": plazo,
                      "cuota": cuota,
                      "total": total_pagar,
                  },
              )
              s.commit()
            st.success(
                "🎉 ¡Solicitud radicada correctamente! Pasando a estado"
                " PENDIENTE de aprobación."
            )
          except Exception as e:
            st.error(f"Error al radicar solicitud: {e}")


def render_aprobacion_creditos():
  st.header("✅ Aprobación y Otorgamiento de Crédito")
  st.markdown("Revisión de solicitudes pendientes y desembolso.")
  st.markdown("---")

  df_pendientes = conn.query(
      """
        SELECT s.id, s.fecha, s.cedula_cliente, c.nombre, c.celular, s.comercio, s.monto_compra, s.plazo_meses, s.cuota_mensual, s.total_pagar, c.cupo_disponible
        FROM solicitudes s
        JOIN clientes c ON s.cedula_cliente = c.cedula
        WHERE s.estado = 'PENDIENTE'
        ORDER BY s.fecha DESC
    """,
      ttl=0,
  )

  if df_pendientes.empty:
    st.info("🎉 No hay solicitudes pendientes por aprobar en este momento.")
  else:
    st.dataframe(df_pendientes, use_container_width=True, hide_index=True)
    st.markdown("---")

    sol_id = st.selectbox(
        "Seleccione el ID de la Solicitud para procesar",
        df_pendientes["id"].tolist(),
    )
    fila_sol = df_pendientes[df_pendientes["id"] == sol_id].iloc[0]

    c1, c2 = st.columns(2)
    with c1:
      if st.button(
          "🟢 Aprobar y Desembolsar Crédito", use_container_width=True
      ):
        try:
          nuevo_cupo = max(
              0.0,
              float(fila_sol["cupo_disponible"])
              - float(fila_sol["monto_compra"]),
          )
          with conn.session as s:
            s.execute(
                text(
                    "UPDATE solicitudes SET estado = 'ACTIVO' WHERE id = :id"
                ),
                {"id": sol_id},
            )
            s.execute(
                text(
                    "UPDATE clientes SET cupo_disponible = :cupo WHERE cedula ="
                    " :ced"
                ),
                {"cupo": nuevo_cupo, "ced": fila_sol["cedula_cliente"]},
            )
            s.commit()

          msg = (
              f"BankCali: Su credito por ${fila_sol['monto_compra']:,.0f} COP"
              f" ha sido APROBADO en {fila_sol['comercio']}. Cuota:"
              f" ${fila_sol['cuota_mensual']:,.0f} COP."
          )
          enviar_sms_twilio(fila_sol["celular"], mensaje_custom=msg)

          st.success(f"✅ Crédito #{sol_id} APROBADO exitosamente.")
          st.rerun()
        except Exception as e:
          st.error(f"Error al aprobar crédito: {e}")

    with c2:
      if st.button("🔴 Rechazar Solicitud", use_container_width=True):
        try:
          with conn.session as s:
            s.execute(
                text(
                    "UPDATE solicitudes SET estado = 'RECHAZADO' WHERE id ="
                    " :id"
                ),
                {"id": sol_id},
            )
            s.commit()

          msg = (
              f"BankCali: Su solicitud de credito por"
              f" ${fila_sol['monto_compra']:,.0f} COP en {fila_sol['comercio']}"
              " ha sido RECHAZADA."
          )
          enviar_sms_twilio(fila_sol["celular"], mensaje_custom=msg)

          st.warning(f"❌ Crédito #{sol_id} RECHAZADO.")
          st.rerun()
        except Exception as e:
          st.error(f"Error al rechazar crédito: {e}")
