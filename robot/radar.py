#!/usr/bin/env python3
"""Grow UP Radar - robot de rastreo de tendencias.

Junta tendencias de fuentes gratuitas, agrupa las notas que hablan de lo mismo,
las rankea por cantidad de medios y guarda todo en data/latest.json.
Solo usa la libreria estandar de Python (no hay que instalar nada).
"""
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = "Mozilla/5.0 (compatible; GrowUpRadar/1.0; +https://github.com/rubengioffre-lab/RubenRRSS-radar)"
GN = "hl=es-419&gl=AR&ceid=AR:es-419"

# ---------------------------------------------------------------- configuracion
# Para sumar un tema nuevo: agregar una entrada con su nombre y sus busquedas.
CATEGORIAS = {
    "laboral": {
        "nombre": "Mundo laboral y RRHH",
        "busquedas": [
            "empleo OR salarios OR \"mercado laboral\"",
            "\"recursos humanos\" OR reclutamiento OR \"búsqueda laboral\"",
            "despidos OR contrataciones OR \"trabajo remoto\" OR \"reforma laboral\"",
        ],
    },
    "tecnologia": {
        "nombre": "Tecnología e IA",
        "busquedas": [
            "\"inteligencia artificial\"",
            "tecnología",
            "ciberseguridad OR hackeo OR programadores OR software",
        ],
    },
    "economia": {
        "nombre": "Economía",
        "busquedas": [
            "economía argentina",
            "dólar OR inflación OR \"banco central\"",
        ],
    },
    "actualidad": {
        "nombre": "Actualidad",
        "busquedas": ["argentina"],
        "portada": True,
    },
    "deportes": {
        "nombre": "Deportes",
        "busquedas": ["fútbol OR \"selección argentina\"", "deportes"],
    },
    "espectaculos": {
        "nombre": "Espectáculos",
        "busquedas": ["espectáculos OR famosos", "series OR streaming OR música"],
    },
}

PERIODOS = {  # clave -> (filtro de Google News, horas)
    "ahora": ("when:4h", 4),
    "24h": ("when:1d", 24),
    "semana": ("when:7d", 168),
    "mes": ("when:30d", 720),
}
MAX_TEMAS = 25
MAX_NOTAS_POR_TEMA = 6

STOP = set("""a al algo ante antes asi aun cada como con contra cual cuando de del desde donde dos
durante e el ella ellos en entre era es esa ese eso esta estan este esto fue ha hace hacia han hasta
hay la las le lo los mas me mi muy ni no nos o otra otro para pero por que quien se segun ser si sin
sobre son su sus tambien tan te tiene tras tu un una uno unos y ya the of to in for and on is at
tras tres nuevo nueva hoy ayer dia dias ano anos sera esta estos estas porque que como cuanto
dijo dice asi mira video fotos tras ser hacer puede pueden vez""".split())


# ------------------------------------------------------------------- utilidades
def log(*a):
    print(*a, file=sys.stderr, flush=True)


def bajar(url, intentos=2, espera=2):
    ultimo = None
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            ultimo = e
            time.sleep(espera * (i + 1))
    raise RuntimeError(f"no se pudo bajar {url[:90]}: {ultimo}")


def local(tag):
    return tag.rsplit("}", 1)[-1]


def hijo(el, nombre):
    for c in el:
        if local(c.tag) == nombre:
            return c
    return None


def texto(el, nombre):
    c = hijo(el, nombre)
    return (c.text or "").strip() if c is not None else ""


def a_iso(fecha_rss):
    try:
        d = parsedate_to_datetime(fecha_rss)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001
        return None


def sin_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def palabras(titulo):
    t = sin_acentos(titulo.lower())
    toks = re.findall(r"[a-z0-9ñ]+", t)
    return {w for w in toks if len(w) > 2 and w not in STOP}


# ---------------------------------------------------------------------- fuentes
def google_trends():
    """Busquedas en tendencia en Argentina, ahora."""
    raiz = ET.fromstring(bajar("https://trends.google.com/trending/rss?geo=AR"))
    out = []
    for it in raiz.iter():
        if local(it.tag) != "item":
            continue
        notas = []
        for n in it:
            if local(n.tag) == "news_item":
                notas.append({
                    "titulo": texto(n, "news_item_title"),
                    "link": texto(n, "news_item_url"),
                    "medio": texto(n, "news_item_source"),
                })
        trafico = texto(it, "approx_traffic")
        num = int(re.sub(r"\D", "", trafico) or 0)
        out.append({
            "tema": texto(it, "title"),
            "busquedas": trafico,
            "busquedas_num": num,
            "desde": a_iso(texto(it, "pubDate")),
            "notas": notas[:3],
        })
    out.sort(key=lambda x: -x["busquedas_num"])
    return out


def google_news(url):
    raiz = ET.fromstring(bajar(url))
    out = []
    for it in raiz.iter():
        if local(it.tag) != "item":
            continue
        titulo = texto(it, "title")
        medio = texto(it, "source")
        if medio and titulo.endswith(" - " + medio):
            titulo = titulo[: -len(" - " + medio)]
        elif " - " in titulo and not medio:
            titulo, medio = titulo.rsplit(" - ", 1)
        if not titulo:
            continue
        out.append({
            "titulo": titulo.strip(),
            "medio": medio.strip() or "?",
            "link": texto(it, "link"),
            "fecha": a_iso(texto(it, "pubDate")),
        })
    return out


def noticias_de(cat, filtro):
    notas = []
    for q in cat["busquedas"]:
        url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{q} {filtro}") + "&" + GN
        try:
            notas += google_news(url)
        except Exception as e:  # noqa: BLE001
            log("  aviso:", e)
        time.sleep(0.6)
    return notas


def wikipedia_top():
    """Articulos mas leidos de Wikipedia desde Argentina (ultimo dia disponible)."""
    hoy = datetime.now(timezone.utc)
    for atras in (1, 2, 3):
        d = hoy - timedelta(days=atras)
        url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/top-per-country/AR/all-access/"
               f"{d:%Y/%m/%d}")
        try:
            arts = json.loads(bajar(url, intentos=1))["items"][0]["articles"]
        except Exception:  # noqa: BLE001
            continue
        out = []
        for a in arts:
            nombre, proj = a.get("article", ""), a.get("project", "")
            if not proj.startswith("es.wikipedia") or ":" in nombre or nombre in ("Wikipedia", "Portada"):
                continue
            out.append({
                "tema": nombre.replace("_", " "),
                "vistas": a.get("views_ceil") or a.get("views") or 0,
                "link": "https://es.wikipedia.org/wiki/" + urllib.parse.quote(nombre),
            })
            if len(out) >= 30:
                break
        return {"fecha": f"{d:%Y-%m-%d}", "temas": out}
    return {"fecha": None, "temas": []}


def hacker_news():
    """Portada de Hacker News: lo que mueve al mundo tech antes de llegar a los diarios."""
    hits = json.loads(bajar("https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30"))["hits"]
    out = [{
        "tema": h.get("title", ""),
        "puntos": h.get("points") or 0,
        "comentarios": h.get("num_comments") or 0,
        "link": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
        "debate": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
    } for h in hits if h.get("title")]
    out.sort(key=lambda x: -x["puntos"])
    return out


# -------------------------------------------------------------------- agrupado
def parecidos(a, b):
    if not a or not b:
        return False
    comun = len(a & b)
    if comun < 2:
        return False
    return comun / min(len(a), len(b)) >= 0.5 or comun / len(a | b) >= 0.34


def agrupar(notas):
    """Junta las notas que hablan de lo mismo y las ordena por cantidad de medios."""
    vistos, limpias = set(), []
    for n in notas:
        clave = (sin_acentos(n["titulo"].lower()), n["medio"].lower())
        if clave in vistos:
            continue
        vistos.add(clave)
        n["_p"] = palabras(n["titulo"])
        limpias.append(n)
    limpias.sort(key=lambda n: n["fecha"] or "", reverse=True)

    grupos = []
    for n in limpias:
        mejor = None
        for g in grupos:
            if parecidos(n["_p"], g["_base"]) or any(parecidos(n["_p"], m["_p"]) for m in g["notas"][:4]):
                mejor = g
                break
        if mejor is None:
            grupos.append({"_base": set(n["_p"]), "notas": [n]})
        else:
            mejor["notas"].append(n)

    temas = []
    for g in grupos:
        medios = []
        for n in g["notas"]:
            if n["medio"] not in medios:
                medios.append(n["medio"])
        fechas = sorted(n["fecha"] for n in g["notas"] if n["fecha"])
        # titular representativo: el que mas palabras comparte con el resto del grupo
        rep = max(g["notas"], key=lambda n: sum(len(n["_p"] & m["_p"]) for m in g["notas"]))
        temas.append({
            "titulo": rep["titulo"],
            "medios": len(medios),
            "lista_medios": medios[:8],
            "notas_total": len(g["notas"]),
            "primera": fechas[0] if fechas else None,
            "ultima": fechas[-1] if fechas else None,
            "notas": [{k: n[k] for k in ("titulo", "medio", "link", "fecha")}
                      for n in g["notas"][:MAX_NOTAS_POR_TEMA]],
        })
    temas.sort(key=lambda t: (t["medios"], t["notas_total"], t["ultima"] or ""), reverse=True)
    return temas[:MAX_TEMAS]


def palabras_calientes(notas, top=12):
    """Palabras que mas se repiten entre medios distintos."""
    cuenta = {}
    for n in notas:
        for w in palabras(n["titulo"]):
            cuenta.setdefault(w, set()).add(n["medio"])
    orden = sorted(cuenta.items(), key=lambda kv: -len(kv[1]))
    return [{"palabra": w, "medios": len(m)} for w, m in orden[:top] if len(m) >= 3]


# ------------------------------------------------------------------- principal
def correr():
    ahora = datetime.now(timezone.utc)
    salida = {
        "generado": ahora.isoformat(timespec="seconds"),
        "tendencias_ar": [],
        "wikipedia": {"fecha": None, "temas": []},
        "hacker_news": [],
        "categorias": {},
        "errores": [],
    }

    for nombre, fn, clave in (("Google Trends", google_trends, "tendencias_ar"),
                              ("Wikipedia", wikipedia_top, "wikipedia"),
                              ("Hacker News", hacker_news, "hacker_news")):
        try:
            log("Bajando", nombre)
            salida[clave] = fn()
        except Exception as e:  # noqa: BLE001
            log("  ERROR", nombre, e)
            salida["errores"].append(f"{nombre}: {e}")

    total = 0
    for cid, cat in CATEGORIAS.items():
        log("Tema:", cat["nombre"])
        bloque = {"nombre": cat["nombre"], "periodos": {}}
        for pid, (filtro, _h) in PERIODOS.items():
            notas = noticias_de(cat, filtro)
            if cat.get("portada") and pid in ("ahora", "24h"):
                try:
                    notas += google_news("https://news.google.com/rss?" + GN)
                except Exception as e:  # noqa: BLE001
                    log("  aviso:", e)
            total += len(notas)
            bloque["periodos"][pid] = {
                "notas_leidas": len(notas),
                "calientes": palabras_calientes(notas),
                "temas": agrupar(notas),
            }
        salida["categorias"][cid] = bloque
    salida["notas_leidas"] = total

    if total == 0 and not salida["tendencias_ar"]:
        log("No se pudo leer ninguna fuente: no se pisa el archivo anterior.")
        return 1

    DATA.mkdir(exist_ok=True)
    (DATA / "latest.json").write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":")),
                                      encoding="utf-8")

    # Foto chica de esta corrida, para medir despues la velocidad de cada tema (Fase 2).
    foto = {
        "t": salida["generado"],
        "trends": [[t["tema"], t["busquedas_num"]] for t in salida["tendencias_ar"][:40]],
        "cats": {cid: [[t["titulo"], t["medios"], t["notas_total"]]
                       for t in b["periodos"]["24h"]["temas"][:20]]
                 for cid, b in salida["categorias"].items()},
    }
    dia = DATA / "historial" / f"{ahora:%Y-%m-%d}"
    dia.mkdir(parents=True, exist_ok=True)
    (dia / f"{ahora:%H%M}.json").write_text(json.dumps(foto, ensure_ascii=False, separators=(",", ":")),
                                            encoding="utf-8")

    # Limpieza: se guarda hasta 45 dias de historial.
    limite = f"{ahora - timedelta(days=45):%Y-%m-%d}"
    for carpeta in (DATA / "historial").iterdir():
        if carpeta.is_dir() and carpeta.name < limite:
            for f in carpeta.iterdir():
                f.unlink()
            carpeta.rmdir()

    log(f"Listo: {total} notas leidas, {len(salida['tendencias_ar'])} tendencias de Google, "
        f"{len(salida['errores'])} errores.")
    return 0


if __name__ == "__main__":
    sys.exit(correr())
