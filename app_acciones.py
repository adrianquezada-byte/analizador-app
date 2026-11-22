import streamlit as st
import yfinance as yf
from openai import OpenAI

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
                # 1. Obtener datos
                stock = yf.Ticker(ticker)
                info = stock.info
                
                # Validar que el ticker exista
                if 'currentPrice' not in info and 'regularMarketPrice' not in info:
                    st.error(f"No se encontraron datos para {ticker}. Verifica el ticker.")
                    st.stop()

                datos_clave = {
                    "precio_actual": info.get("currentPrice", info.get("regularMarketPrice")),
                    "capitalización": info.get("marketCap"),
                    "PER": info.get("trailingPE"),
                    "PER_forward": info.get("forwardPE"),
                    "máximo_52_semanas": info.get("fiftyTwoWeekHigh"),
                    "mínimo_52_semanas": info.get("fiftyTwoWeekLow"),
                    "margen_beneficio": info.get("profitMargins"),
                    "ingresos_totales": info.get("totalRevenue"),
                    "recomendación_analistas": info.get("recommendationKey"),
                    "precio_objetivo": info.get("targetMeanPrice"),
                }

                # Mostrar datos en la interfaz
                st.subheader(f"Datos clave de {ticker}")
                col1, col2, col3 = st.columns(3)
                col1.metric("Precio Actual", f"${datos_clave['precio_actual']}")
                col2.metric("PER (Trailing)", datos_clave['PER'])
                col3.metric("Precio Objetivo (Analistas)", f"${datos_clave['precio_objetivo']}")

                # 2. Llamar a OpenRouter (Modelo Gratuito)
                with st.spinner("Analizando con IA (esto puede tardar unos segundos)..."):
                    
                    # Configuramos el cliente apuntando a OpenRouter
                    client = OpenAI(
                        base_url="https://openrouter.ai/api/v1",
                        api_key=api_key,
                    )
                    
                    respuesta = client.chat.completions.create(
                        model="openrouter/free", # Modelo gratuito
                        messages=[
                            {"role": "system", "content": "Eres un analista financiero. Basándote en los datos proporcionados, analiza la acción en 3 puntos: puntos fuertes, riesgos y adecuación para inversores con tolerancia al riesgo media. No des recomendaciones directas de compra o venta. Sé breve y claro."},
                            {"role": "user", "content": f"Datos de {ticker}:\n{datos_clave}"}
                        ]
                    )
                    
                    st.subheader("🤖 Análisis de la IA")
                    st.write(respuesta.choices[0].message.content)

            except Exception as e:
                st.error(f"Ocurrió un error: {e}")
                st.info("Si el error menciona 'Rate limit' o '429', significa que el modelo gratuito está saturado. Intenta de nuevo en unos segundos o cambia el modelo en el código a 'google/gemma-7b-it:free'.")