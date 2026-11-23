import streamlit as st
import yfinance as yf
from openai import OpenAI
from curl_cffi import requests as curl_requests

# Configurar la página
st.set_page_config(page_title="Análisis de Acciones", page_icon="📈")
st.title("📈 Analizador de Acciones con IA")

# Barra lateral
with st.sidebar:
    st.header("Configuración")
    api_key = st.text_input("OpenRouter API Key", type="password")
    ticker = st.text_input("Ticker de la acción", value="AAPL").upper()
    analizar_btn = st.button("Analizar Acción 🚀")

if analizar_btn:
    if not api_key:
        st.error("Por favor, ingresa tu API Key de OpenRouter en la barra lateral.")
    else:
        with st.spinner(f"Obteniendo datos de {ticker}..."):
            try:
                # 1. Obtener datos
                session = curl_requests.Session(impersonate="chrome")
                stock = yf.Ticker(ticker, session=session)
                
                hist = stock.history(period="1d")
                if hist.empty:
                    st.error(f"No se encontraron datos para {ticker}.")
                    st.stop()

                precio_actual = hist['Close'].iloc[-1]

                try:
                    info = stock.info
                except Exception:
                    info = {}

                # Plan B para PER y Precio Objetivo si vienen vacíos
                per = info.get("trailingPE", "N/A")
                precio_obj = info.get("targetMeanPrice", "N/A")
                
                # Si el PER es N/A, intentamos calcularlo con los datos históricos
                if per == "N/A" or per is None:
                    # Obtenemos el beneficio por acción (EPS) si está disponible
                    eps = info.get("trailingEps")
                    if eps and eps != 0:
                        per = round(precio_actual / eps, 2)
                
                # Si el Precio Objetivo es N/A, usamos el máximo de 52 semanas como referencia (Plan B)
                if precio_obj == "N/A" or precio_obj is None:
                    precio_obj = info.get("fiftyTwoWeekHigh", "N/A")

                datos_clave = {
                    "precio_actual": round(precio_actual, 2),
                    "capitalización": info.get("marketCap", "N/A"),
                    "PER": per,
                    "PER_forward": info.get("forwardPE", "N/A"),
                    "máximo_52_semanas": info.get("fiftyTwoWeekHigh", "N/A"),
                    "mínimo_52_semanas": info.get("fiftyTwoWeekLow", "N/A"),
                    "margen_beneficio": info.get("profitMargins", "N/A"),
                    "ingresos_totales": info.get("totalRevenue", "N/A"),
                    "recomendación_analistas": info.get("recommendationKey", "N/A"),
                    "precio_objetivo": precio_obj,
                }

                # Mostrar datos
                st.subheader(f"Datos clave de {ticker}")
                col1, col2, col3 = st.columns(3)
                col1.metric("Precio Actual", f"${datos_clave['precio_actual']}")
                col2.metric("PER (Trailing)", str(datos_clave['PER']))
                col3.metric("Precio Objetivo (Estimado)", f"${datos_clave['precio_objetivo']}")

                # 2. Llamar a OpenRouter con el modelo ACTUALIZADO
                with st.spinner("Analizando con IA..."):
                    client = OpenAI(
                        base_url="https://openrouter.ai/api/v1",
                        api_key=api_key,
                    )
                    
                    # El modelo actualizado que pide el error 404
                    respuesta = client.chat.completions.create(
                        model="meta-llama/llama-3.1-8b-instruct", 
                        messages=[
                            {"role": "system", "content": "Eres un analista financiero. Basándote en los datos proporcionados, analiza la acción en 3 puntos: puntos fuertes, riesgos y adecuación para inversores con tolerancia al riesgo media. No des recomendaciones directas de compra o venta. Sé breve y claro."},
                            {"role": "user", "content": f"Datos de {ticker}:\n{datos_clave}"}
                        ]
                    )
                    
                    st.subheader("🤖 Análisis de la IA")
                    st.write(respuesta.choices[0].message.content)

            except Exception as e:
                st.error(f"Ocurrió un error inesperado: {e}")
