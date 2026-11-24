import datetime as dt

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Analizador de Acciones con IA", page_icon="📈", layout="wide")

TIINGO = "https://api.tiingo.com"
OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
MODELO_IA = "openai/gpt-4o-mini"  # puedes cambiarlo por cualquier modelo de OpenRouter


# ---------- Utilidades ----------
def secret(nombre: str) -> str:
    try:
        return st.secrets.get(nombre, "")
    except Exception:
        return ""


def tiingo_get(path: str, token: str, params: dict | None = None):
    params = {**(params or {}), "token": token}
    r = requests.get(f"{TIINGO}{path}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def fmt_money(v):
    return f"${v:,.2f}" if isinstance(v, (int, float)) else "N/D"


def fmt_cap(v):
    if not isinstance(v, (int, float)):
        return "N/D"
    for limite, sufijo in ((1e12, "B"), (1e9, "MM"), (1e6, "M")):  # B = billón (10^12)
        if v >= limite:
            return f"${v / limite:,.2f} {sufijo}"
    return f"${v:,.0f}"


# ---------- Datos de Tiingo ----------
@st.cache_data(ttl=60, show_spinner=False)
def precio_intradia(ticker: str, token: str):
    data = tiingo_get(f"/iex/{ticker}", token)
    return data[0] if data else None


@st.cache_data(ttl=3600, show_spinner=False)
def historico_52s(ticker: str, token: str):
    inicio = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    data = tiingo_get(f"/tiingo/daily/{ticker}/prices", token, {"startDate": inicio})
    return pd.DataFrame(data)


@st.cache_data(ttl=3600, show_spinner=False)
def metadatos(ticker: str, token: str):
    return tiingo_get(f"/tiingo/daily/{ticker}", token)


@st.cache_data(ttl=3600, show_spinner=False)
def market_cap(ticker: str, token: str):
    """Requiere el plan de fundamentales de Tiingo; si no, devuelve None."""
    try:
        data = tiingo_get(f"/tiingo/fundamentals/{ticker}/daily", token)
        if data:
            return data[-1].get("marketCap")
    except Exception:
        pass
    return None


@st.cache_data(ttl=600, show_spinner=False)
def noticias_24h(ticker: str, token: str):
    """Noticias de Tiingo de las últimas 24h (puede requerir plan con noticias)."""
    desde = (dt.datetime.utcnow() - dt.timedelta(hours=24)).strftime("%Y-%m-%d")
    try:
        data = tiingo_get("/tiingo/news", token, {"tickers": ticker, "startDate": desde, "limit": 15})
        corte = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
        return [
            n for n in data
            if dt.datetime.fromisoformat(n["publishedDate"].replace("Z", "+00:00")) >= corte
        ]
    except Exception:
        return []


# ---------- IA (OpenRouter) ----------
def consultar_ia(api_key: str, prompt: str, modelo: str) -> str:
    r = requests.post(
        OPENROUTER,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": modelo, "messages": [{"role": "user", "content": prompt}]},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def resumen_noticias(api_key: str, ticker: str, nombre: str, noticias: list) -> str:
    if noticias:
        listado = "\n".join(
            f"- {n['title']} ({n.get('source', '')}, {n['publishedDate'][:16]}): {(n.get('description') or '')[:300]}"
            for n in noticias
        )
        prompt = (
            f"Estas son las noticias de las últimas 24 horas sobre {nombre} ({ticker}):\n{listado}\n\n"
            "Resume en español, en 4 a 6 viñetas, lo más relevante para un inversionista y "
            "termina con una línea sobre el sentimiento general (positivo, neutral o negativo). "
            "No inventes datos que no estén en la lista."
        )
        return consultar_ia(api_key, prompt, MODELO_IA)

    # Sin noticias de Tiingo: se usa búsqueda web del modelo (sufijo :online)
    prompt = (
        f"Busca en la web las noticias e información relevante de las últimas 24 horas sobre {nombre} ({ticker}). "
        "Resume en español, en 4 a 6 viñetas, lo más importante para un inversionista, indica la fuente "
        "de cada punto y cierra con el sentimiento general. Si no hay noticias relevantes, dilo claramente."
    )
    return consultar_ia(api_key, prompt, MODELO_IA + ":online")


# ---------- Interfaz ----------
st.title("📈 Analizador de Acciones con IA")

with st.sidebar:
    st.header("Configuración")
    tiingo_key = st.text_input("Tiingo API Key", type="password", value=secret("TIINGO_API_KEY"))
    openrouter_key = st.text_input("OpenRouter API Key", type="password", value=secret("OPENROUTER_API_KEY"))
    ticker = st.text_input("Ticker de la acción", value="AAPL").strip().upper()
    analizar = st.button("Analizar Acción 🚀")

if analizar:
    if not tiingo_key:
        st.error("Ingresa tu Tiingo API Key en la barra lateral.")
        st.stop()
    if not ticker:
        st.error("Ingresa un ticker.")
        st.stop()

    try:
        with st.spinner("Consultando datos de mercado..."):
            px = precio_intradia(ticker, tiingo_key)
            meta = metadatos(ticker, tiingo_key)
            hist = historico_52s(ticker, tiingo_key)
            cap = market_cap(ticker, tiingo_key)
    except requests.HTTPError as e:
        codigo = e.response.status_code if e.response is not None else "?"
        st.error(f"Tiingo respondió con error {codigo}. Revisa el ticker y tu API key.")
        st.stop()
    except Exception as e:
        st.error(f"No se pudieron obtener los datos: {e}")
        st.stop()

    if not px:
        st.warning("No hay datos para ese ticker.")
        st.stop()

    nombre = meta.get("name", ticker)
    precio = px.get("last") or px.get("tngoLast")
    cierre_prev = px.get("prevClose")
    apertura = px.get("open")
    variacion = (precio - cierre_prev) if precio and cierre_prev else None
    variacion_pct = (variacion / cierre_prev * 100) if variacion is not None else None

    st.subheader(f"{nombre} ({ticker})")
    st.caption(f"{meta.get('exchangeCode', '')} · Última actualización: {px.get('timestamp', '')[:19].replace('T', ' ')} UTC")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Precio actual",
        fmt_money(precio),
        f"{variacion:+,.2f} ({variacion_pct:+.2f}%)" if variacion is not None else None,
    )
    c2.metric("Cierre día anterior", fmt_money(cierre_prev))
    c3.metric("Apertura hoy", fmt_money(apertura))
    c4.metric("Capitalización de mercado", fmt_cap(cap))

    if not hist.empty:
        minimo, maximo = hist["low"].min(), hist["high"].max()
        st.markdown("**Rango de 52 semanas**")
        st.write(f"{fmt_money(minimo)}  —  {fmt_money(maximo)}")
        if precio and maximo > minimo:
            st.progress(min(max((precio - minimo) / (maximo - minimo), 0.0), 1.0))
        hist["date"] = pd.to_datetime(hist["date"])
        st.line_chart(hist.set_index("date")["close"], height=250)

    if cap is None:
        st.caption("ℹ️ La capitalización de mercado requiere el plan de fundamentales de Tiingo.")

    st.divider()
    st.subheader("🗞️ Información relevante de las últimas 24 horas")
    if not openrouter_key:
        st.info("Ingresa tu OpenRouter API Key para ver el resumen de noticias con IA.")
    else:
        try:
            with st.spinner("Analizando noticias con IA..."):
                noticias = noticias_24h(ticker, tiingo_key)
                st.markdown(resumen_noticias(openrouter_key, ticker, nombre, noticias))
            if noticias:
                with st.expander("Ver noticias originales"):
                    for n in noticias:
                        st.markdown(f"- [{n['title']}]({n['url']}) · {n.get('source', '')}")
        except Exception as e:
            st.error(f"No se pudo generar el resumen con IA: {e}")

    st.caption("Información con fines informativos; no constituye asesoría financiera.")
