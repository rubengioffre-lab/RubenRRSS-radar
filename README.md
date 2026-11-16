# Radar RRSS

Radar de tendencias para armar contenido en redes a tiempo.

## Cómo funciona

1. **El robot** (`robot/radar.py`) corre solo una vez por hora en GitHub Actions.
2. Lee fuentes gratuitas: Google Trends Argentina, Google News (por tema y período),
   Wikipedia (lo más leído en Argentina) y Hacker News.
3. Agrupa las notas que hablan de lo mismo y las ordena por cantidad de medios.
4. Guarda el resultado en `data/latest.json` y una foto chica en `data/historial/`.
5. **El panel** (`index.html`) muestra todo, con filtros por tema y período.

No usa claves, no usa base de datos y no cuesta nada.

## Cambiar los temas

En `robot/radar.py`, arriba de todo, está `CATEGORIAS`. Cada tema tiene un nombre
y una lista de búsquedas. Para sumar un tema, se agrega una entrada más.

## Correrlo a mano

En GitHub: pestaña **Actions** → **Radar** → **Run workflow**.
