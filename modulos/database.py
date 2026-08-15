import streamlit as st
from sqlalchemy import text
from twilio.rest import Client

# Inicialización de la conexión SQL (Supabase / Postgres)
conn = st.connection("supabase", type="sql")


def enviar_sms_twilio(numero_destino, mensaje_custom):
  """Función global para el envío de notificaciones SMS a clientes vía Twilio."""
  try:
    account_sid = st.secrets["TWILIO_ACCOUNT_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]
    twilio_number = st.secrets["TWILIO_PHONE_NUMBER"]

    client = Client(account_sid, auth_token)

    # Formatear número para Colombia (+57) si viene sin prefijo
    numero_limpio = str(numero_destino).strip().replace(" ", "")
    if not numero_limpio.startswith("+"):
      numero_limpio = f"+57{numero_limpio}"

    message = client.messages.create(
        body=mensaje_custom, from_=twilio_number, to=numero_limpio
    )
    return True, message.sid
  except Exception as e:
    return False, str(e)
