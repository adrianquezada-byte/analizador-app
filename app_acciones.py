import streamlit as st
from tiingo import TiingoClient
from openai import OpenAI

# Configurar la página
st.set_page_config(page_title="Análisis de Acciones", page_icon="📈")
st.title("📈 Analizador de Acciones con IA")

# Barra lateral para configuración
with st.sidebar:
    st.header("Configuración")
    tiingo_key = st.text_input("Tiingo API Key", type="password")
    api_key = st.text_input("OpenRouter API Key", type="password")
    ticker = st.text_input("Ticker de la acción", value="AAPL").upper()
    analizar_btn = st.button("Analizar Acción 🚀")

# Lógica principal
if analizar_btn:
    if not tiingo_key or not api_key:
        st.error("Por favor, ingresa ambas API Keys en la barra lateral.")
    else:
        with st.spinner(f"Obteniendo datos de {ticker}..."):
            try:
                # 1. Obtener datos con Tiingo
                config = {'api_key': tiingo_key, 'session': True}
                client = TiingoClient(config)
                
                # Obtener precios diarios
                precios = client.get_ticker_price(ticker, frequency='daily')
                
                if not precios:
                    st.error(f"No se encontraron datos para {ticker}. Verifica el ticker o intenta de nuevo.")
                    st.stop()

                # El último dato disponible (precio de cierre más reciente)
                ultimo_dato = precios[-1]
                precio_actual = ultimo_dato['close']
                fecha_dato = ultimo_dato['date'][:10] # Formato YYYY-MM-DD

                # Obtener metadatos de la empresa
                try:
                    metadata = client.get_ticker_metadata(ticker)
                    nombre_empresa = metadata.get('name', ticker)
                except Exception:
                    nombre_empresa = ticker
                    metadata = {}

                # Construir diccionario de datos clave
                datos_clave = {
                    "nombre": nombre_empresa,
                    "precio_actual": round(precio_actual, 2),
                    "fecha_del_dato": fecha_dato,
                    # Tiingo a veces incluye estos campos en el metadata o en precios
                    "máximo_52_semanas": metadata.get("high52Week", "N/A"),
                    "mínimo_52_semanas": metadata.get("low52Week", "N/A"),
                }

                # Mostrar datos en la interfaz
                st.subheader(f"Datos clave de {ticker} ({nombre_empresa})")
                col1, col2, col3 = st.columns(3)
                col1.metric("Precio Actual", f"${datos_clave['precio_actual']}")
                col2.metric("Fecha del Dato", datos_clave['fecha_del_dato'])
                col3.metric("Máx. 52 Semanas", str(datos_clave['máximo_52_semanas']))

                # 2. Llamar a OpenRouter para el análisis
                with st.spinner("Analizando con IA (esto puede tardar unos segundos)..."):
                    
                    client_ia = OpenAI(
                        base_url="https://openrouter.ai/api/v1",
                        api_key=api_key,
                    )
                    
                    respuesta = client_ia.chat.completions.create(
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
                st.info("Verifica tu API Key de Tiingo y que el ticker sea válido (ej. AAPL).")
