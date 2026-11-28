import datetime as dt
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

st.set_page_config(page_title="Analizador de Acciones con IA", page_icon="📈", layout="wide")

TIINGO = "https://api.tiingo.com"
OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
MODELO_IA = "openai/gpt-4o-mini"  # puedes cambiarlo por cualquier modelo de OpenRouter

# Empresas disponibles en el desplegable (nombre -> ticker). Tiingo usa guion para clases de acciones (BRK-B).
EMPRESAS = {
    "NVIDIA (NVDA)": "NVDA",
    "Microsoft (MSFT)": "MSFT",
    "Alphabet (GOOGL)": "GOOGL",
    "Amazon (AMZN)": "AMZN",
    "SpaceX (SPCX)": "SPCX",
    "Meta Platforms (META)": "META",
    "Tesla (TSLA)": "TSLA",
    "Broadcom (AVGO)": "AVGO",
    "Eli Lilly (LLY)": "LLY",
    "Berkshire Hathaway (BRK-B)": "BRK-B",
    "SAP (SAP)": "SAP",
    "Anthropic (ANT)": "ANT",
}
OTRO = "Otro ticker…"


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
def historico(ticker: str, token: str):
    """~2 años de datos diarios: sirve para el rango de 52 semanas y para la MA 200."""
    inicio = (dt.date.today() - dt.timedelta(days=730)).isoformat()
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
def noticias_tiingo(ticker: str, token: str):
    """Noticias de Tiingo (requiere plan con noticias; si no, devuelve lista vacía)."""
    desde = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).strftime("%Y-%m-%d")
    try:
        data = tiingo_get("/tiingo/news", token, {"tickers": ticker, "startDate": desde, "limit": 15})
        corte = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
        return [
            n for n in data
            if dt.datetime.fromisoformat(n["publishedDate"].replace("Z", "+00:00")) >= corte
        ]
    except Exception:
        return []


def parsear_rss(contenido: bytes, horas: int = 24, limite: int = 15):
    """Convierte el RSS de Google News en una lista de noticias de las últimas `horas` horas."""
    corte = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=horas)
    vistos, noticias = set(), []
    for item in ET.fromstring(contenido).iter("item"):
        titulo = (item.findtext("title") or "").strip()
        fuente = (item.findtext("source") or "").strip()
        try:
            fecha = parsedate_to_datetime(item.findtext("pubDate"))
            if fecha.tzinfo is None:
                fecha = fecha.replace(tzinfo=dt.timezone.utc)
        except Exception:
            continue
        if fuente and titulo.endswith(f" - {fuente}"):
            titulo = titulo[: -len(fuente) - 3]
        clave = titulo.lower()
        if not titulo or fecha < corte or clave in vistos:
            continue
        vistos.add(clave)
        noticias.append({"title": titulo, "url": (item.findtext("link") or "").strip(), "source": fuente,
                         "publishedDate": fecha.astimezone(dt.timezone.utc).isoformat(), "description": ""})
    noticias.sort(key=lambda n: n["publishedDate"], reverse=True)
    return noticias[:limite]


@st.cache_data(ttl=600, show_spinner=False)
def noticias_google(ticker: str, nombre: str, horas: int = 24):
    """Titulares desde Google News (RSS gratuito). Devuelve (noticias, diagnóstico)."""
    limpio = re.sub(r"\b(and|inc|corp|corporation|company|co|ltd|plc|holdings|class [a-z])\b\.?,?", "", nombre, flags=re.I)
    limpio = " ".join(limpio.split())
    dias = max(1, round(horas / 24))
    consultas = [f"{limpio} {ticker} stock", limpio, f"{ticker} stock"]
    vistos, noticias, diag = set(), [], []
    for q in dict.fromkeys(c for c in consultas if c.strip()):
        url = (f"https://news.google.com/rss/search?q={quote_plus(q + f' when:{dias}d')}"
               "&hl=en-US&gl=US&ceid=US:en")
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            r.raise_for_status()
            encontradas = parsear_rss(r.content, horas=horas)
            diag.append(f"«{q}»: {len(encontradas)} resultados")
            for n in encontradas:
                if n["title"].lower() not in vistos:
                    vistos.add(n["title"].lower())
                    noticias.append(n)
        except Exception as e:
            diag.append(f"«{q}»: error ({type(e).__name__}: {e})")
        if len(noticias) >= 15:
            break
    noticias.sort(key=lambda n: n["publishedDate"], reverse=True)
    return noticias[:15], diag


def noticias_24h(ticker: str, nombre: str, token: str):
    """Devuelve (noticias, fuente, diagnóstico, horas_usadas).
    Tiingo si tu plan las incluye; si no, Google News (24 h y, si no hay nada, 7 días)."""
    n = noticias_tiingo(ticker, token)
    if n:
        return n, "Tiingo", [], 24
    noticias, diag = noticias_google(ticker, nombre, 24)
    if noticias:
        return noticias, "Google News", diag, 24
    noticias, diag2 = noticias_google(ticker, nombre, 168)
    return noticias, "Google News", diag + diag2, 168


# ---------- IA (OpenRouter) ----------
def consultar_ia(api_key: str, prompt: str, modelo: str) -> str:
    r = requests.post(
        OPENROUTER,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": modelo, "messages": [{"role": "user", "content": prompt}]},
        timeout=90,
    )
    if r.status_code == 402:
        raise RuntimeError(
            "OpenRouter respondió 402 (pago requerido): tu cuenta no tiene crédito suficiente. "
            "Agrega saldo en openrouter.ai/settings/credits o usa un modelo gratuito (termina en :free) en la barra lateral."
        )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def resumen_noticias(api_key: str, ticker: str, nombre: str, noticias: list, modelo: str, horas: int = 24) -> str:
    listado = "\n".join(
        f"- {n['title']} ({n.get('source', '')}, {n['publishedDate'][:16].replace('T', ' ')} UTC)"
        + (f": {n['description'][:300]}" if n.get("description") else "")
        for n in noticias
    )
    prompt = (
        f"Estos son los titulares de {'las últimas 24 horas' if horas <= 24 else 'los últimos 7 días'} sobre {nombre} ({ticker}):\n{listado}\n\n"
        "Resume en español, en 4 a 6 viñetas, lo más relevante para un inversionista, agrupando titulares "
        "que traten del mismo tema y mencionando la fuente entre paréntesis. Termina con una línea sobre el "
        "sentimiento general (positivo, neutral o negativo). Básate solo en los titulares: no inventes cifras ni "
        "detalles que no aparezcan en ellos y aclara cuando algo no esté claro."
    )
    return consultar_ia(api_key, prompt, modelo)


# ---------- Apertura: pre-market, futuros, resultados y estimación ----------
ET = ZoneInfo("America/New_York")
FINNHUB = "https://finnhub.io/api/v1"
ETIQUETA_SESION = {
    "pre": "🌅 Pre-market (4:00–9:30 ET)",
    "regular": "🟢 Mercado abierto",
    "post": "🌆 After-hours (16:00–20:00 ET)",
    "cerrado": "🌙 Mercado cerrado",
}
MOMENTO = {"bmo": "antes de la apertura", "amc": "después del cierre", "dmh": "durante la sesión"}


def sesion_mercado(ahora: dt.datetime) -> str:
    """Sesión según la hora de Nueva York (no considera feriados)."""
    if ahora.weekday() >= 5:
        return "cerrado"
    m = ahora.hour * 60 + ahora.minute
    if 240 <= m < 570:
        return "pre"
    if 570 <= m < 960:
        return "regular"
    if 960 <= m < 1200:
        return "post"
    return "cerrado"


def analizar_extendido(barras: pd.DataFrame, cierres: dict | None = None):
    """A partir de barras de 5 min (con pre/post market) devuelve el cierre de la última sesión
    regular y la actividad posterior. `cierres` (fecha -> cierre oficial) afina el cierre de referencia."""
    if barras is None or barras.empty or "close" not in barras:
        return None
    b = barras.copy()
    b["date"] = pd.to_datetime(b["date"], utc=True).dt.tz_convert(ET)
    b = b.sort_values("date")
    b = b[b["date"].dt.weekday < 5]
    minutos = b["date"].dt.hour * 60 + b["date"].dt.minute
    regulares = b[(minutos >= 570) & (minutos < 960)]
    if regulares.empty:
        return None
    ultima = regulares.iloc[-1]
    fecha_ref = ultima["date"].date()
    cierre = float((cierres or {}).get(fecha_ref) or ultima["close"])
    ext = b[b["date"] > ultima["date"]]
    if "volume" in ext:
        ext = ext[ext["volume"].fillna(0) > 0]
    resultado = {"cierre_ref": cierre, "fecha_ref": fecha_ref, "ext_precio": None, "ext_hora": None,
                 "ext_volumen": 0, "ext_barras": 0, "pct": None}
    if not ext.empty:
        resultado.update(
            ext_precio=float(ext.iloc[-1]["close"]), ext_hora=ext.iloc[-1]["date"],
            ext_volumen=int(ext["volume"].sum()) if "volume" in ext else 0, ext_barras=len(ext),
            pct=(float(ext.iloc[-1]["close"]) / cierre - 1) * 100,
        )
    return resultado


def calcular_beta(precios_accion: pd.Series, precios_mercado: pd.Series, n: int = 252):
    r = pd.concat([precios_accion.pct_change(), precios_mercado.pct_change()], axis=1, join="inner").dropna().tail(n)
    if len(r) < 40 or r.iloc[:, 1].var() <= 0:
        return None
    return float(r.iloc[:, 0].cov(r.iloc[:, 1]) / r.iloc[:, 1].var())


def sigma_gap(hist: pd.DataFrame, n: int = 60):
    """Desviación típica (en %) de la brecha apertura vs cierre previo en las últimas n sesiones."""
    d = hist.sort_values("date")
    ap = "adjOpen" if "adjOpen" in d else "open"
    ci = "adjClose" if "adjClose" in d else "close"
    g = (d[ap] / d[ci].shift(1) - 1).dropna().tail(n)
    return float(g.std() * 100) if len(g) >= 20 else None


def serie_cierres(df: pd.DataFrame) -> pd.Series:
    col = "adjClose" if "adjClose" in df else "close"
    idx = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None).dt.normalize()
    return pd.Series(df[col].values, index=idx)


def parsear_yahoo(j: dict):
    res = j["chart"]["result"][0]
    precio = res["meta"].get("regularMarketPrice")
    cierres = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    previo = cierres[-2] if len(cierres) >= 2 else res["meta"].get("chartPreviousClose")
    if not precio or not previo:
        return None
    return {"precio": float(precio), "previo": float(previo), "pct": (float(precio) / float(previo) - 1) * 100}


def dia_habil_previo(fecha: dt.date) -> dt.date:
    f = fecha - dt.timedelta(days=1)
    while f.weekday() >= 5:
        f -= dt.timedelta(days=1)
    return f


def resumir_resultados(lista: list, hoy: dt.date):
    """Devuelve (próximo reporte, último reporte ya publicado) a partir del calendario de Finnhub."""
    items = sorted([x for x in lista if x.get("date")], key=lambda x: x["date"])
    prox = next((x for x in items if x["date"] >= hoy.isoformat() and x.get("epsActual") is None), None)
    ult = next((x for x in reversed(items) if x.get("epsActual") is not None), None)
    return prox, ult


def resultados_afectan_apertura(prox, ult, hoy: dt.date) -> bool:
    """True si hubo (o habrá antes de abrir) un reporte de resultados que mueva la apertura de `hoy`."""
    if ult and ult.get("date") == dia_habil_previo(hoy).isoformat() and ult.get("hour") == "amc":
        return True
    if ult and ult.get("date") == hoy.isoformat() and ult.get("hour") == "bmo":
        return True
    if prox and prox.get("date") == hoy.isoformat() and prox.get("hour") in ("bmo", "", None):
        return True
    return False


def estimar_apertura(cierre, pct_pre, pre_fresco, pct_fut, beta, sigma, hay_resultados):
    """Combina pre-market y futuros (ajustados por beta) en un precio de apertura sugerido."""
    notas, componentes = [], []
    implicito = None
    if pct_fut is not None:
        b = beta if beta is not None else 1.0
        implicito = b * pct_fut
        if beta is None:
            notas.append("No hay historial suficiente para calcular la beta; se asumió 1,0.")
    if pct_pre is not None and implicito is not None:
        w = 0.7 if pre_fresco else 0.4
        gap = w * pct_pre + (1 - w) * implicito
        componentes = [("Pre-market de la acción", pct_pre, w), ("Futuros S&P 500 × beta", implicito, 1 - w)]
    elif pct_pre is not None:
        gap = pct_pre
        componentes = [("Pre-market de la acción", pct_pre, 1.0)]
    elif implicito is not None:
        gap = implicito
        componentes = [("Futuros S&P 500 × beta", implicito, 1.0)]
    else:
        gap = 0.0
        notas.append("Sin datos de pre-market ni de futuros: la estimación es simplemente el cierre anterior.")
    if pct_pre is not None and not pre_fresco:
        notas.append("La última operación en pre-market tiene más de 30 minutos: puede estar desactualizada.")
    if hay_resultados:
        notas.append("Hay un reporte de resultados que afecta esta apertura: la incertidumbre es mayor.")

    puntos = (2 if (pct_pre is not None and pre_fresco) else 1 if pct_pre is not None else 0) + (1 if pct_fut is not None else 0)
    if hay_resultados:
        puntos -= 1
    confianza = "Alta" if puntos >= 3 else "Media" if puntos == 2 else "Baja"

    precio = cierre * (1 + gap / 100)
    rango = (precio * (1 - sigma / 100), precio * (1 + sigma / 100)) if sigma else None
    return {"precio": precio, "gap": gap, "rango": rango, "confianza": confianza, "componentes": componentes, "notas": notas}


@st.cache_data(ttl=120, show_spinner=False)
def barras_extendidas(ticker: str, token: str):
    inicio = (dt.date.today() - dt.timedelta(days=6)).isoformat()
    data = tiingo_get(f"/iex/{ticker}/prices", token,
                      {"startDate": inicio, "resampleFreq": "5min", "afterHours": "true"})
    return pd.DataFrame(data)


@st.cache_data(ttl=120, show_spinner=False)
def futuro_yahoo(simbolo: str):
    try:
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote_plus(simbolo)}",
                         params={"range": "5d", "interval": "1d"}, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.raise_for_status()
        return parsear_yahoo(r.json())
    except Exception:
        return None


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def calendario_resultados(ticker: str, key: str):
    hoy = dt.date.today()
    r = requests.get(f"{FINNHUB}/calendar/earnings", timeout=15, params={
        "symbol": ticker.replace("-", "."), "from": (hoy - dt.timedelta(days=100)).isoformat(),
        "to": (hoy + dt.timedelta(days=120)).isoformat(), "token": key})
    r.raise_for_status()
    return r.json().get("earningsCalendar", [])


def seccion_apertura(ticker, tiingo_key, finnhub_key, hist, px):
    st.subheader("🌅 Apertura: pre-market, futuros y estimación")
    ahora = dt.datetime.now(ET)
    hoy = ahora.date()
    sesion = sesion_mercado(ahora)
    st.caption(f"{ETIQUETA_SESION[sesion]} · Hora en Nueva York: {ahora:%d/%m/%Y %H:%M}")

    if sesion == "regular":
        st.info(f"El mercado ya está abierto. Apertura real de hoy: **{fmt_money(px.get('open'))}**. "
                "La estimación de apertura se muestra entre las 16:00 y las 9:30 (hora de Nueva York) del día hábil siguiente.")
        return

    # 1) Pre / post market de la acción
    ext = None
    try:
        cierres = {d.date(): c for d, c in zip(hist["date"], hist["close"])}
        ext = analizar_extendido(barras_extendidas(ticker, tiingo_key), cierres)
    except Exception:
        pass
    pre_fresco = bool(ext and ext["ext_hora"] is not None and (ahora - ext["ext_hora"]) <= dt.timedelta(minutes=30))
    pct_pre = ext["pct"] if ext else None

    nombre_sesion = "Pre-market" if sesion == "pre" else "After-hours / último extendido"
    c1, c2, c3, c4 = st.columns(4)
    if ext:
        c1.metric("Cierre de referencia", fmt_money(ext["cierre_ref"]), f"{ext['fecha_ref']:%d/%m}", delta_color="off")
        c2.metric(nombre_sesion, fmt_money(ext["ext_precio"]),
                  f"{pct_pre:+.2f}%" if pct_pre is not None else None)
        c3.metric("Volumen (IEX)", f"{ext['ext_volumen']:,}" if ext["ext_barras"] else "N/D")
        c4.metric("Última operación (ET)", f"{ext['ext_hora']:%H:%M}" if ext["ext_hora"] is not None else "N/D")
        if ext["ext_precio"] is None:
            st.caption("Aún no hay operaciones en la sesión extendida desde el último cierre.")
    else:
        st.warning("No se pudieron obtener datos de pre-market de Tiingo (el plan o el ticker podrían no incluirlos).")
    st.caption("ℹ️ Los datos extendidos de Tiingo provienen del mercado IEX, que representa una parte pequeña del volumen "
               "total: úsalos como referencia, no como precio exacto.")

    # 2) Futuros del S&P 500 y del Nasdaq 100 (con respaldo en ETF SPY / QQQ)
    futuros = {"S&P 500": futuro_yahoo("ES=F"), "Nasdaq 100": futuro_yahoo("NQ=F")}
    origen_fut = "Futuros E-mini (Yahoo Finance)"
    if not any(futuros.values()):
        origen_fut = "ETF SPY / QQQ en sesión extendida (respaldo, sin datos de futuros)"
        for nombre, etf in (("S&P 500", "SPY"), ("Nasdaq 100", "QQQ")):
            try:
                a = analizar_extendido(barras_extendidas(etf, tiingo_key))
                if a and a["pct"] is not None:
                    futuros[nombre] = {"precio": a["ext_precio"], "previo": a["cierre_ref"], "pct": a["pct"]}
            except Exception:
                pass
    st.markdown(f"**Mercado general** · _{origen_fut}_")
    f1, f2 = st.columns(2)
    for col, nombre in ((f1, "S&P 500"), (f2, "Nasdaq 100")):
        d = futuros.get(nombre)
        col.metric(nombre, f"{d['precio']:,.2f}" if d else "N/D", f"{d['pct']:+.2f}%" if d else None)
    pct_fut = futuros["S&P 500"]["pct"] if futuros.get("S&P 500") else None

    # 3) Calendario de resultados
    st.markdown("**📅 Calendario de resultados**")
    prox = ult = None
    resultados_ok = False
    if not finnhub_key:
        st.info("Para ver el calendario de resultados agrega una clave gratuita de Finnhub (finnhub.io/register) "
                "en la barra lateral o en Secrets como `FINNHUB_API_KEY`.")
    else:
        try:
            prox, ult = resumir_resultados(calendario_resultados(ticker, finnhub_key), hoy)
            resultados_ok = True
        except Exception as e:
            st.warning(f"No se pudo consultar el calendario de resultados: {e}")
    if resultados_ok:
        if prox:
            est = f" · EPS estimado: ${prox['epsEstimate']:.2f}" if prox.get("epsEstimate") is not None else ""
            st.write(f"**Próximo reporte:** {prox['date']} ({MOMENTO.get(prox.get('hour'), 'hora por confirmar')}){est}")
        if ult:
            act, est_ = ult.get("epsActual"), ult.get("epsEstimate")
            sorpresa = f" ({(act / est_ - 1) * 100:+.1f}% vs estimado)" if act is not None and est_ else ""
            ing = ""
            if ult.get("revenueActual") is not None:
                ing = f" · Ingresos: {fmt_cap(ult['revenueActual'])}"
                if ult.get("revenueEstimate"):
                    ing += f" (estimado {fmt_cap(ult['revenueEstimate'])})"
            st.write(f"**Último reporte ({ult['date']}):** EPS ${act:.2f}"
                     + (f" vs ${est_:.2f} estimado{sorpresa}" if est_ is not None else "") + ing)
        if not prox and not ult:
            st.caption("Sin reportes de resultados en el período consultado (por ejemplo, una empresa recién listada).")
    hay_resultados = resultados_afectan_apertura(prox, ult, hoy) if resultados_ok else False

    # 4) Estimación
    st.markdown("**🎯 Precio de apertura sugerido**")
    if not ext:
        st.warning("Sin datos del cierre de referencia no se puede estimar la apertura.")
        return
    beta = sigma = None
    try:
        beta = calcular_beta(serie_cierres(hist), serie_cierres(historico("SPY", tiingo_key)))
    except Exception:
        pass
    try:
        sigma = sigma_gap(hist)
    except Exception:
        pass
    est = estimar_apertura(ext["cierre_ref"], pct_pre, pre_fresco, pct_fut, beta, sigma, hay_resultados)

    e1, e2, e3 = st.columns(3)
    e1.metric("Apertura estimada", fmt_money(est["precio"]), f"{est['gap']:+.2f}% vs cierre {fmt_money(ext['cierre_ref'])}")
    e2.metric("Rango probable (±1σ)",
              f"{fmt_money(est['rango'][0])} – {fmt_money(est['rango'][1])}" if est["rango"] else "N/D")
    e3.metric("Confianza", est["confianza"])
    if est["componentes"]:
        st.dataframe(pd.DataFrame([{"Fuente": n, "Señal": f"{v:+.2f}%", "Peso": f"{w:.0%}"} for n, v, w in est["componentes"]]),
                     hide_index=True)
    if beta is not None:
        st.caption(f"Beta de la acción frente al S&P 500 (1 año): {beta:.2f}")
    for nota in est["notas"]:
        st.warning(nota)
    with st.expander("¿Cómo se calcula esta estimación?"):
        st.markdown(
            "- **Punto de partida:** el cierre oficial de la última sesión regular.\n"
            "- **Pre-market:** variación de la acción en la sesión extendida frente a ese cierre.\n"
            "- **Futuros:** variación de los futuros del S&P 500 multiplicada por la **beta** de la acción "
            "(cuánto suele moverse respecto al mercado).\n"
            "- **Combinación:** 70 % pre-market y 30 % futuros si el último dato es reciente (≤ 30 min); 40 % / 60 % si no.\n"
            "- **Rango (±1σ):** desviación típica de las brechas de apertura de las últimas 60 sesiones.\n"
            "- **Confianza:** sube con más fuentes frescas y baja si hay resultados o datos viejos.\n\n"
            "Es una **estimación heurística**, no una predicción: la apertura real la fija la subasta de la bolsa."
        )


# ---------- Medias móviles ----------
VENTANAS = [20, 50, 100, 200]
COLORES = {"Precio": "#9aa0a6", "MA 20": "#f4b400", "MA 50": "#34a853", "MA 100": "#4285f4", "MA 200": "#ea4335"}


def calcular_medias(close: pd.Series, tipo: str) -> pd.DataFrame:
    out = pd.DataFrame({"Precio": close})
    for n in VENTANAS:
        if tipo == "SMA":
            serie = close.rolling(n).mean()
        else:
            serie = close.ewm(span=n, adjust=False).mean()
            serie.iloc[: n - 1] = float("nan")  # primeros valores poco fiables
        out[f"MA {n}"] = serie
    return out


@st.fragment
def seccion_medias(hist: pd.DataFrame, precio):
    st.subheader("📊 Medias móviles")
    tipo = st.radio(
        "Tipo de media",
        ["SMA", "EMA"],
        horizontal=True,
        help="SMA: media simple. EMA: exponencial, da más peso a los precios recientes y reacciona más rápido.",
    )
    col_precio = "adjClose" if "adjClose" in hist.columns else "close"
    medias = calcular_medias(hist.set_index("date")[col_precio], tipo)
    ultimo = medias.iloc[-1]
    ref = precio or ultimo["Precio"]

    # Gráfico (último año)
    visible = medias[medias.index >= medias.index.max() - pd.Timedelta(days=365)]
    fig = go.Figure()
    for col in visible.columns:
        fig.add_trace(go.Scatter(
            x=visible.index, y=visible[col], name=col if col == "Precio" else col.replace("MA", tipo),
            line=dict(color=COLORES[col], width=2.5 if col == "Precio" else 1.6),
        ))
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified",
                      legend=dict(orientation="h", y=1.08))
    st.plotly_chart(fig)

    # Tabla: precio vs cada media
    filas, encima, validas = [], 0, 0
    for n in VENTANAS:
        v = ultimo[f"MA {n}"]
        if pd.notna(v):
            validas += 1
            arriba = ref > v
            encima += int(arriba)
            filas.append({"Media": f"{tipo} {n}", "Valor": fmt_money(v),
                          "Precio vs media": f"{(ref / v - 1) * 100:+.2f}%",
                          "Posición": "🟢 Por encima" if arriba else "🔴 Por debajo"})
        else:
            filas.append({"Media": f"{tipo} {n}", "Valor": "N/D", "Precio vs media": "N/D",
                          "Posición": "Sin datos suficientes"})
    st.dataframe(pd.DataFrame(filas), hide_index=True)

    # Lectura de la tendencia
    if validas == len(VENTANAS) and encima == len(VENTANAS):
        st.success("Precio por encima de las cuatro medias: tendencia generalmente **alcista**.")
    elif validas == len(VENTANAS) and encima == 0:
        st.error("Precio por debajo de las cuatro medias: tendencia generalmente **bajista**.")
    elif validas == 0:
        st.info("Todavía no hay historial suficiente (mínimo 20 sesiones) para calcular las medias móviles.")
    else:
        st.info(f"Señales mixtas: el precio está por encima de {encima} de {validas} medias.")

    # Golden Cross / Death Cross (MA 50 vs MA 200)
    d = (medias["MA 50"] - medias["MA 200"]).dropna()
    if len(d) > 1:
        positivo = d > 0
        cambios = positivo != positivo.shift()
        cambios.iloc[0] = False
        estado = "MA 50 por encima de la MA 200 (configuración alcista)" if positivo.iloc[-1] \
            else "MA 50 por debajo de la MA 200 (configuración bajista)"
        if cambios.any():
            fecha = cambios[cambios].index[-1]
            nombre_cruce = "🟡 Golden Cross (alcista)" if positivo.loc[fecha] else "⚫ Death Cross (bajista)"
            st.markdown(f"**Estado actual:** {estado}.  \n**Último cruce detectado:** {nombre_cruce} el {fecha:%d/%m/%Y}.")
        else:
            st.markdown(f"**Estado actual:** {estado}.  \nNo se detectaron cruces MA 50 / MA 200 en el período analizado.")

    else:
        st.caption("No hay historial suficiente para evaluar el cruce MA 50 / MA 200.")

    st.caption("Las medias se calculan con precios de cierre ajustados por splits y dividendos. "
               "Son indicadores rezagados: describen la tendencia pasada, no garantizan el futuro.")


# ---------- Interfaz ----------
st.title("📈 Analizador de Acciones con IA")

with st.sidebar:
    st.header("Configuración")
    tiingo_key = st.text_input("Tiingo API Key", type="password", value=secret("TIINGO_API_KEY"))
    openrouter_key = st.text_input("OpenRouter API Key", type="password", value=secret("OPENROUTER_API_KEY"))
    finnhub_key = st.text_input(
        "Finnhub API Key (opcional)", type="password", value=secret("FINNHUB_API_KEY"),
        help="Gratuita en finnhub.io/register. Se usa para el calendario de resultados.",
    )
    modelo_ia = st.text_input(
        "Modelo de IA (OpenRouter)",
        value=MODELO_IA,
        help="Para no gastar crédito prueba uno gratuito, por ejemplo: meta-llama/llama-3.3-70b-instruct:free",
    ).strip()
    opcion = st.selectbox("Empresa", list(EMPRESAS) + [OTRO])
    if opcion == OTRO:
        ticker = st.text_input("Ticker personalizado", value="AAPL").strip().upper()
    else:
        ticker = EMPRESAS[opcion]
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
            hist = historico(ticker, tiingo_key)
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
        hist["date"] = pd.to_datetime(hist["date"]).dt.tz_localize(None)
        ultimo_anio = hist[hist["date"] >= hist["date"].max() - pd.Timedelta(days=365)]
        minimo, maximo = ultimo_anio["low"].min(), ultimo_anio["high"].max()
        st.markdown("**Rango de 52 semanas**")
        st.write(f"{fmt_money(minimo)}  —  {fmt_money(maximo)}")
        if precio and maximo > minimo:
            st.progress(min(max((precio - minimo) / (maximo - minimo), 0.0), 1.0))
        if len(ultimo_anio) < 240:
            st.caption(f"ℹ️ Solo hay {len(ultimo_anio)} sesiones de historial (listado reciente): "
                       "el rango corresponde al período disponible y las medias largas pueden aparecer como N/D.")
        st.divider()
        try:
            seccion_apertura(ticker, tiingo_key, finnhub_key, hist, px)
        except Exception as e:
            st.warning(f"No se pudo calcular la sección de apertura: {e}")
        st.divider()
        seccion_medias(hist, precio)

    if cap is None:
        st.caption("ℹ️ La capitalización de mercado requiere el plan de fundamentales de Tiingo.")

    st.divider()
    st.subheader("🗞️ Información relevante de las últimas 24 horas")
    with st.spinner("Buscando noticias..."):
        noticias, fuente, diag, horas_usadas = noticias_24h(ticker, nombre, tiingo_key)

    if not noticias:
        st.info("No se encontraron noticias recientes para esta acción.")
        if diag:
            with st.expander("Detalles de la búsqueda"):
                st.write("\n".join(f"- {d}" for d in diag))
                st.caption("Si todas las consultas dan error, Google News puede estar bloqueando el servidor de Streamlit.")
    else:
        if horas_usadas > 24:
            st.caption("ℹ️ No hubo titulares en las últimas 24 horas; se muestran los de los últimos 7 días.")
        resumen_ok = False
        if openrouter_key:
            try:
                with st.spinner("Resumiendo con IA..."):
                    st.markdown(resumen_noticias(openrouter_key, ticker, nombre, noticias, modelo_ia, horas_usadas))
                resumen_ok = True
            except Exception as e:
                st.error(f"No se pudo generar el resumen con IA: {e}")
        else:
            st.info("Ingresa tu OpenRouter API Key para ver un resumen con IA. Abajo tienes los titulares.")

        ventana = "24 horas" if horas_usadas <= 24 else "7 días"
        with st.expander(f"Titulares de los últimos {ventana} ({fuente})", expanded=not resumen_ok):
            for n in noticias:
                hora = n["publishedDate"][:16].replace("T", " ")
                st.markdown(f"- [{n['title']}]({n['url']}) · {n.get('source', '')} · {hora} UTC")

    st.caption("Información con fines informativos; no constituye asesoría financiera.")
