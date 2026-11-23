import streamlit as st
import yfinance as yf
from openai import OpenAI
from curl_cffi import requests as curl_requests

# Configurar la página
st.set_page_config(page_title="Análisis de Acciones", page_icon="📈")
st.title("📈 Analizador de Acciones con IA")

# Barra lateral para configuración
with st.sidebar:
    st.header("Configuración")
    api_key = st.text_input("OpenRouter API Key", type="password")
    ticker = st.text_input("Ticker de la acción", value="AAPL").upper()
    analizar_btn = st.button("Analizar Acción 🚀")

# Lógica principal
if analizar_btn:
    if not api_key:
        st.error("Por favor, ingresa tu API Key de OpenRouter en la barra lateral.")
    else:
        with st.spinner(f"Obteniendo datos de {ticker}..."):
            try:
                # 1. Obtener datos usando curl_cffi para simular un navegador
                session = curl_requests.Session(impersonate="chrome")
                stock = yf.Ticker(ticker, session=session)
                
                # Validar usando history() (más fiable que info en la nube)
                hist = stock.history(period="1d")
                if hist.empty:
                    st.error(f"No se encontraron datos para {ticker}. Verifica el ticker o intenta de nuevo en unos segundos.")
                    st.stop()

                # Obtener precio de cierre
                precio_actual = hist['Close'].iloc[-1]

                # Intentar obtener info
                try:
                    info = stock.info
                except Exception:
                    info = {}

                datos_clave = {
                    "precio_actual": round(precio_actual, 2),
                    "capitalización": info.get("marketCap", "N/A"),
                    "PER": info.get("trailingPE", "N/A"),
                    "PER_forward": info.get("forwardPE", "N/A"),
                    "máximo_52_semanas": info.get("fiftyTwoWeekHigh", "N/A"),
                    "mínimo_52_semanas": info.get("fiftyTwoWeekLow", "N/A"),
                    "margen_beneficio": info.get("profitMargins", "N/A"),
                    "ingresos_totales": info.get("totalRevenue", "N/A"),
                    "recomendación_analistas": info.get("recommendationKey", "N/A"),
                    "precio_objetivo": info.get("targetMeanPrice", "N/A"),
                }

                # Mostrar datos en la interfaz
                st.subheader(f"Datos clave de {ticker}")
                col1, col2, col3 = st.columns(3)
                col1.metric("Precio Actual", f"${datos_clave['precio_actual']}")
                col2.metric("PER (Trailing)", str(datos_clave['PER']))
                col3.metric("Precio Objetivo (Analistas)", f"${datos_clave['precio_objetivo']}")

                # 2. Llamar a OpenRouter
                with st.spinner("Analizando con IA (esto puede tardar unos segundos)..."):
                    
                    client = OpenAI(
                        base_url="https://openrouter.ai/api/v1",
                        api_key=api_key,
                    )
                    
                    respuesta = client.chat.completions.create(
                        model="meta-llama/llama-3-8b-instruct:free", 
                        messages=[
                            {"role": "system", "content": "Eres un analista financiero. Basándote en los datos proporcionados, analiza la acción en 3 puntos: puntos fuertes, riesgos y adecuación para inversores con tolerancia al riesgo media. No des recomendaciones directas de compra o venta. Sé breve y claro."},
                            {"role": "user", "content": f"Datos de {ticker}:\n{datos_clave}"}
                        ]
                    )
                    
                    st.subheader("🤖 Análisis de la IA")
                    st.write(respuesta.choices[0].message.content)

            except Exception as e:
                st.error(f"Ocurrió un error inesperado: {e}")
                st.info("A veces Yahoo Finance bloquea las peticiones. Intenta recargar la página o prueba con otro ticker.")
