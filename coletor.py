#!/usr/bin/env python3
"""
coletor.py — Coleta diária de precedentes sobre organização criminosa.
Fontes: STF (RSS), STJ (API), TJPE (portal), Planalto (legislação).
Gera: data/resultados.json
"""

import json
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from html.parser import HTMLParser

TERMO_BUSCA = "organização criminosa"
TERMO_BUSCA_URL = urllib.parse.quote(TERMO_BUSCA)
ARQUIVO_SAIDA = "data/resultados.json"

# ─── Utilitários ─────────────────────────────────────────────────────────────

def get_url(url, timeout=20):
    """Faz GET simples com User-Agent."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; JusCrimBot/1.0; +https://github.com)",
            "Accept": "application/json, text/html, application/xml, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        charset = r.headers.get_content_charset() or "utf-8"
        return r.read().decode(charset, errors="replace")

def limpa(txt):
    """Remove tags HTML e normaliza espaços."""
    txt = re.sub(r"<[^>]+>", " ", txt or "")
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt

def trunca(txt, n=300):
    if len(txt) <= n:
        return txt
    return txt[:n].rsplit(" ", 1)[0] + "…"

def hoje_br():
    return datetime.now().strftime("%d/%m/%Y")

# ─── Parser RSS genérico ──────────────────────────────────────────────────────

class RSSParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []
        self._current = {}
        self._tag = None
        self._in_item = False

    def handle_starttag(self, tag, attrs):
        self._tag = tag.lower()
        if self._tag == "item":
            self._in_item = True
            self._current = {}

    def handle_endtag(self, tag):
        if tag.lower() == "item" and self._in_item:
            self.items.append(self._current)
            self._in_item = False
        self._tag = None

    def handle_data(self, data):
        if self._in_item and self._tag in ("title", "link", "description", "pubdate"):
            key = self._tag
            self._current[key] = self._current.get(key, "") + data

def parse_rss(xml):
    p = RSSParser()
    p.feed(xml)
    return p.items

# ─── STF ─────────────────────────────────────────────────────────────────────

def coleta_stf():
    print("[STF] Coletando…")
    resultados = []
    try:
        # API de pesquisa de jurisprudência do STF
        url = (
            "https://jurisprudencia.stf.jus.br/api/search/search"
            f"?query={TERMO_BUSCA_URL}"
            "&sort=_score&sortBy=desc&isIncognito=false&offset=0&limit=10"
        )
        raw = get_url(url)
        data = json.loads(raw)
        hits = data.get("hits", {}).get("hits", [])
        for h in hits:
            src = h.get("_source", {})
            titulo = limpa(src.get("nome", "") or src.get("nomeProcesso", ""))
            resumo = limpa(src.get("ementa", "") or src.get("observacao", ""))
            numero = src.get("numeroProcesso", "")
            relator = limpa(src.get("nomeRelator", ""))
            data_julgamento = src.get("dataJulgamento", "") or src.get("dataPublicacao", "")
            if data_julgamento:
                try:
                    data_julgamento = datetime.strptime(data_julgamento[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
                except Exception:
                    pass
            link = f"https://jurisprudencia.stf.jus.br/pages/search/resultado/{h.get('_id','')}/relevance"
            if titulo:
                resultados.append({
                    "fonte": "STF",
                    "titulo": titulo,
                    "resumo": trunca(resumo),
                    "numero": numero,
                    "relator": relator,
                    "data": data_julgamento,
                    "url": link,
                })
    except Exception as e:
        print(f"  [STF] Erro na API JSON: {e}. Tentando RSS…")
        try:
            rss_url = (
                "https://jurisprudencia.stf.jus.br/api/search/rss"
                f"?query={TERMO_BUSCA_URL}&sort=_score&sortBy=desc"
            )
            xml = get_url(rss_url)
            for item in parse_rss(xml)[:10]:
                titulo = limpa(item.get("title", ""))
                if titulo:
                    resultados.append({
                        "fonte": "STF",
                        "titulo": titulo,
                        "resumo": trunca(limpa(item.get("description", ""))),
                        "numero": "",
                        "relator": "",
                        "data": limpa(item.get("pubdate", "")),
                        "url": item.get("link", "").strip(),
                    })
        except Exception as e2:
            print(f"  [STF] Erro no RSS também: {e2}")
    print(f"  [STF] {len(resultados)} resultado(s).")
    return resultados

# ─── STJ ─────────────────────────────────────────────────────────────────────

def coleta_stj():
    print("[STJ] Coletando…")
    resultados = []
    try:
        url = (
            "https://scon.stj.jus.br/SCON/pesquisar.jsp"
            f"?b=ACOR&livre={TERMO_BUSCA_URL}&tipo_visualizacao=RESUMO&operador=E"
            "&p=true&l=10&i=1&formato=JSON"
        )
        raw = get_url(url)
        data = json.loads(raw)
        docs = data.get("documento", [])
        for d in docs:
            titulo = limpa(d.get("docTitulo", "") or d.get("titulo", ""))
            resumo = limpa(d.get("ementa", "") or d.get("docEmenta", ""))
            numero = d.get("numProcesso", "") or d.get("docNumero", "")
            relator = limpa(d.get("ministroRelator", "") or d.get("relator", ""))
            data_pub = d.get("dtPublicacao", "") or d.get("dataJulgamento", "")
            link = d.get("urlDocumento", "") or f"https://scon.stj.jus.br/SCON/"
            if titulo:
                resultados.append({
                    "fonte": "STJ",
                    "titulo": titulo,
                    "resumo": trunca(resumo),
                    "numero": numero,
                    "relator": relator,
                    "data": data_pub,
                    "url": link,
                })
    except Exception as e:
        print(f"  [STJ] Erro: {e}. Tentando RSS…")
        try:
            rss_url = (
                "https://www.stj.jus.br/sites/portalp/Paginas/Comunicacao/Noticias/RSS.aspx"
            )
            xml = get_url(rss_url)
            for item in parse_rss(xml):
                titulo = limpa(item.get("title", ""))
                desc = limpa(item.get("description", ""))
                if TERMO_BUSCA.lower() in (titulo + desc).lower():
                    resultados.append({
                        "fonte": "STJ",
                        "titulo": titulo,
                        "resumo": trunca(desc),
                        "numero": "",
                        "relator": "",
                        "data": limpa(item.get("pubdate", "")),
                        "url": item.get("link", "").strip(),
                    })
        except Exception as e2:
            print(f"  [STJ] Erro no RSS: {e2}")
    print(f"  [STJ] {len(resultados)} resultado(s).")
    return resultados

# ─── TJPE ─────────────────────────────────────────────────────────────────────

def coleta_tjpe():
    print("[TJPE] Coletando…")
    resultados = []
    try:
        # Portal de jurisprudência do TJPE
        url = (
            "https://www.tjpe.jus.br/jurisprudencia/pesquisar"
            f"?tipo=0&pesquisa={TERMO_BUSCA_URL}&formato=JSON"
        )
        raw = get_url(url)
        data = json.loads(raw)
        docs = data if isinstance(data, list) else data.get("resultado", data.get("documentos", []))
        for d in docs[:10]:
            titulo = limpa(d.get("ementa", "") or d.get("titulo", ""))
            numero = d.get("processo", "") or d.get("numero", "")
            relator = limpa(d.get("relator", ""))
            data_pub = d.get("dataJulgamento", "") or d.get("data", "")
            link = d.get("url", "https://www.tjpe.jus.br/jurisprudencia")
            if titulo:
                resultados.append({
                    "fonte": "TJPE",
                    "titulo": trunca(titulo, 180),
                    "resumo": "",
                    "numero": numero,
                    "relator": relator,
                    "data": data_pub,
                    "url": link,
                })
    except Exception as e:
        print(f"  [TJPE] Erro: {e}. Sem dados disponíveis via API pública.")
        # Fallback: item genérico apontando para o portal
        resultados.append({
            "fonte": "TJPE",
            "titulo": f"Pesquisa manual: '{TERMO_BUSCA}' no portal TJPE",
            "resumo": "Clique para pesquisar diretamente no portal de jurisprudência do TJPE.",
            "numero": "",
            "relator": "",
            "data": hoje_br(),
            "url": f"https://www.tjpe.jus.br/jurisprudencia",
        })
    print(f"  [TJPE] {len(resultados)} resultado(s).")
    return resultados

# ─── Legislação Federal (Planalto) ───────────────────────────────────────────

def coleta_legislacao():
    print("[LEG] Coletando legislação…")
    resultados = []
    # Leis e decretos relevantes (lista curada + busca no Portal LexML)
    normas_fixas = [
        {
            "titulo": "Lei nº 12.850/2013 — Define organização criminosa",
            "resumo": "Define organização criminosa, dispõe sobre a investigação criminal, os meios de obtenção da prova, infrações penais correlatas e o procedimento criminal.",
            "numero": "12.850/2013",
            "data": "02/08/2013",
            "url": "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2013/lei/l12850.htm",
        },
        {
            "titulo": "Lei nº 9.034/1995 — Organização criminosa (revogada pela 12.850)",
            "resumo": "Dispunha sobre a utilização de meios operacionais para a prevenção e repressão de ações praticadas por organizações criminosas.",
            "numero": "9.034/1995",
            "data": "03/05/1995",
            "url": "https://www.planalto.gov.br/ccivil_03/leis/l9034.htm",
        },
        {
            "titulo": "Lei nº 12.694/2012 — Julgamento colegiado em crimes de org. criminosa",
            "resumo": "Dispõe sobre o processo e o julgamento colegiado em primeiro grau de jurisdição de crimes praticados por organizações criminosas.",
            "numero": "12.694/2012",
            "data": "24/07/2012",
            "url": "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2012/lei/l12694.htm",
        },
    ]

    for n in normas_fixas:
        resultados.append({
            "fonte": "LEG",
            **n,
        })

    # Tenta busca dinâmica no LexML
    try:
        lexml_url = (
            "https://www.lexml.gov.br/busca/SRU?operation=searchRetrieve"
            f"&query=organizacao+criminosa&maximumRecords=5&recordSchema=opendocument"
        )
        raw = get_url(lexml_url, timeout=15)
        # Extrai títulos simples via regex do XML retornado
        titulos = re.findall(r"<dc:title[^>]*>([^<]+)</dc:title>", raw)
        links = re.findall(r"<dc:identifier[^>]*>(https?://[^<]+)</dc:identifier>", raw)
        datas = re.findall(r"<dc:date[^>]*>([^<]+)</dc:date>", raw)
        for i, titulo in enumerate(titulos[:5]):
            titulo = limpa(titulo)
            if titulo and not any(titulo in r["titulo"] for r in resultados):
                resultados.append({
                    "fonte": "LEG",
                    "titulo": titulo,
                    "resumo": "Norma encontrada no acervo LexML.",
                    "numero": "",
                    "data": datas[i] if i < len(datas) else "",
                    "url": links[i] if i < len(links) else "https://www.lexml.gov.br",
                })
    except Exception as e:
        print(f"  [LEG] LexML indisponível: {e}")

    print(f"  [LEG] {len(resultados)} resultado(s).")
    return resultados

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    import os
    os.makedirs("data", exist_ok=True)

    todos = []
    todos += coleta_stf()
    time.sleep(1)
    todos += coleta_stj()
    time.sleep(1)
    todos += coleta_tjpe()
    time.sleep(1)
    todos += coleta_legislacao()

    saida = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "termo_busca": TERMO_BUSCA,
        "total": len(todos),
        "resultados": todos,
    }

    with open(ARQUIVO_SAIDA, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    print(f"\n✓ {len(todos)} resultados salvos em '{ARQUIVO_SAIDA}'.")

if __name__ == "__main__":
    main()
