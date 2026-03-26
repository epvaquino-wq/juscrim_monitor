#!/usr/bin/env python3
"""
coletor.py v2 — Coleta diária de precedentes sobre organização criminosa.
Salva: data/YYYY-MM-DD.json  +  data/indice.json (atualizado)
Fontes: STF, STJ, TJPE, Planalto/LexML
"""

import json
import re
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, date
from html.parser import HTMLParser

TERMO_BUSCA = "organização criminosa"
TERMO_BUSCA_URL = urllib.parse.quote(TERMO_BUSCA)
DIR_DATA = "data"
ARQUIVO_INDICE = f"{DIR_DATA}/indice.json"

# ─── Utilitários ──────────────────────────────────────────────────────────────

def get_url(url, timeout=20):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; JusCrimBot/2.0)",
            "Accept": "application/json, text/html, application/xml, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        charset = r.headers.get_content_charset() or "utf-8"
        return r.read().decode(charset, errors="replace")

def limpa(txt):
    txt = re.sub(r"<[^>]+>", " ", txt or "")
    return re.sub(r"\s+", " ", txt).strip()

def trunca(txt, n=350):
    txt = txt or ""
    return txt[:n].rsplit(" ", 1)[0] + "…" if len(txt) > n else txt

def hoje_iso():
    return date.today().isoformat()   # "2025-08-01"

def hoje_br():
    return date.today().strftime("%d/%m/%Y")

# ─── Parser RSS ───────────────────────────────────────────────────────────────

class RSSParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items, self._cur, self._tag, self._in = [], {}, None, False

    def handle_starttag(self, tag, attrs):
        self._tag = tag.lower()
        if self._tag == "item":
            self._in, self._cur = True, {}

    def handle_endtag(self, tag):
        if tag.lower() == "item" and self._in:
            self.items.append(self._cur)
            self._in = False
        self._tag = None

    def handle_data(self, data):
        if self._in and self._tag in ("title","link","description","pubdate"):
            self._cur[self._tag] = self._cur.get(self._tag,"") + data

def parse_rss(xml):
    p = RSSParser(); p.feed(xml); return p.items

# ─── STF ──────────────────────────────────────────────────────────────────────

def coleta_stf():
    print("[STF] Coletando…")
    resultados = []
    try:
        url = (
            "https://jurisprudencia.stf.jus.br/api/search/search"
            f"?query={TERMO_BUSCA_URL}&sort=_score&sortBy=desc"
            "&isIncognito=false&offset=0&limit=10"
        )
        data = json.loads(get_url(url))
        for h in data.get("hits", {}).get("hits", []):
            s = h.get("_source", {})
            titulo = limpa(s.get("nome","") or s.get("nomeProcesso",""))
            resumo = limpa(s.get("ementa","") or s.get("observacao",""))
            dt = s.get("dataJulgamento","") or s.get("dataPublicacao","")
            if dt:
                try: dt = datetime.strptime(dt[:10],"%Y-%m-%d").strftime("%d/%m/%Y")
                except: pass
            if titulo:
                resultados.append({
                    "fonte":"STF","titulo":titulo,"resumo":trunca(resumo),
                    "numero":s.get("numeroProcesso",""),
                    "relator":limpa(s.get("nomeRelator","")),
                    "data":dt,
                    "url":f"https://jurisprudencia.stf.jus.br/pages/search/resultado/{h.get('_id','')}/relevance"
                })
    except Exception as e:
        print(f"  [STF] API: {e} → tentando RSS")
        try:
            xml = get_url(f"https://jurisprudencia.stf.jus.br/api/search/rss?query={TERMO_BUSCA_URL}&sort=_score&sortBy=desc")
            for item in parse_rss(xml)[:10]:
                t = limpa(item.get("title",""))
                if t:
                    resultados.append({"fonte":"STF","titulo":t,"resumo":trunca(limpa(item.get("description",""))),"numero":"","relator":"","data":limpa(item.get("pubdate","")),"url":item.get("link","").strip()})
        except Exception as e2:
            print(f"  [STF] RSS: {e2}")
    print(f"  [STF] {len(resultados)} resultado(s).")
    return resultados

# ─── STJ ──────────────────────────────────────────────────────────────────────

def coleta_stj():
    print("[STJ] Coletando…")
    resultados = []
    try:
        url = (
            "https://scon.stj.jus.br/SCON/pesquisar.jsp"
            f"?b=ACOR&livre={TERMO_BUSCA_URL}&tipo_visualizacao=RESUMO"
            "&operador=E&p=true&l=10&i=1&formato=JSON"
        )
        data = json.loads(get_url(url))
        for d in data.get("documento", []):
            titulo = limpa(d.get("docTitulo","") or d.get("titulo",""))
            resumo = limpa(d.get("ementa","") or d.get("docEmenta",""))
            if titulo:
                resultados.append({
                    "fonte":"STJ","titulo":titulo,"resumo":trunca(resumo),
                    "numero":d.get("numProcesso","") or d.get("docNumero",""),
                    "relator":limpa(d.get("ministroRelator","") or d.get("relator","")),
                    "data":d.get("dtPublicacao","") or d.get("dataJulgamento",""),
                    "url":d.get("urlDocumento","https://scon.stj.jus.br/SCON/")
                })
    except Exception as e:
        print(f"  [STJ] API: {e} → tentando RSS")
        try:
            xml = get_url("https://www.stj.jus.br/sites/portalp/Paginas/Comunicacao/Noticias/RSS.aspx")
            for item in parse_rss(xml):
                t = limpa(item.get("title",""))
                d = limpa(item.get("description",""))
                if TERMO_BUSCA.lower() in (t+d).lower():
                    resultados.append({"fonte":"STJ","titulo":t,"resumo":trunca(d),"numero":"","relator":"","data":limpa(item.get("pubdate","")),"url":item.get("link","").strip()})
        except Exception as e2:
            print(f"  [STJ] RSS: {e2}")
    print(f"  [STJ] {len(resultados)} resultado(s).")
    return resultados

# ─── TJPE ─────────────────────────────────────────────────────────────────────

def coleta_tjpe():
    print("[TJPE] Coletando…")
    resultados = []
    try:
        url = f"https://www.tjpe.jus.br/jurisprudencia/pesquisar?tipo=0&pesquisa={TERMO_BUSCA_URL}&formato=JSON"
        data = json.loads(get_url(url))
        docs = data if isinstance(data, list) else data.get("resultado", data.get("documentos", []))
        for d in docs[:10]:
            t = limpa(d.get("ementa","") or d.get("titulo",""))
            if t:
                resultados.append({
                    "fonte":"TJPE","titulo":trunca(t,180),"resumo":"",
                    "numero":d.get("processo","") or d.get("numero",""),
                    "relator":limpa(d.get("relator","")),
                    "data":d.get("dataJulgamento","") or d.get("data",""),
                    "url":d.get("url","https://www.tjpe.jus.br/jurisprudencia")
                })
    except Exception as e:
        print(f"  [TJPE] {e} → fallback")
        resultados.append({
            "fonte":"TJPE",
            "titulo":f"Pesquisa '{TERMO_BUSCA}' no TJPE — clique para acessar",
            "resumo":"Acesse o portal de jurisprudência do TJPE para consultar manualmente.",
            "numero":"","relator":"","data":hoje_br(),
            "url":"https://www.tjpe.jus.br/jurisprudencia"
        })
    print(f"  [TJPE] {len(resultados)} resultado(s).")
    return resultados

# ─── Legislação ───────────────────────────────────────────────────────────────

def coleta_legislacao():
    print("[LEG] Coletando…")
    normas = [
        {"titulo":"Lei nº 12.850/2013 — Define organização criminosa","resumo":"Define organização criminosa, dispõe sobre investigação criminal, meios de obtenção da prova, infrações penais correlatas e procedimento criminal.","numero":"12.850/2013","data":"02/08/2013","url":"https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2013/lei/l12850.htm"},
        {"titulo":"Lei nº 12.694/2012 — Julgamento colegiado","resumo":"Dispõe sobre julgamento colegiado em primeiro grau em crimes de organizações criminosas.","numero":"12.694/2012","data":"24/07/2012","url":"https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2012/lei/l12694.htm"},
        {"titulo":"Lei nº 9.034/1995 — Revogada pela 12.850","resumo":"Dispunha sobre meios operacionais para prevenção e repressão de organizações criminosas (revogada).","numero":"9.034/1995","data":"03/05/1995","url":"https://www.planalto.gov.br/ccivil_03/leis/l9034.htm"},
    ]
    resultados = [{"fonte":"LEG", **n} for n in normas]
    try:
        xml = get_url("https://www.lexml.gov.br/busca/SRU?operation=searchRetrieve&query=organizacao+criminosa&maximumRecords=5&recordSchema=opendocument", timeout=15)
        titulos = re.findall(r"<dc:title[^>]*>([^<]+)</dc:title>", xml)
        links   = re.findall(r"<dc:identifier[^>]*>(https?://[^<]+)</dc:identifier>", xml)
        datas   = re.findall(r"<dc:date[^>]*>([^<]+)</dc:date>", xml)
        for i, t in enumerate(titulos[:5]):
            t = limpa(t)
            if t and not any(t in r["titulo"] for r in resultados):
                resultados.append({"fonte":"LEG","titulo":t,"resumo":"Norma localizada no acervo LexML.","numero":"","data":datas[i] if i<len(datas) else "","url":links[i] if i<len(links) else "https://www.lexml.gov.br"})
    except Exception as e:
        print(f"  [LEG] LexML: {e}")
    print(f"  [LEG] {len(resultados)} resultado(s).")
    return resultados

# ─── Índice ───────────────────────────────────────────────────────────────────

def carregar_indice():
    try:
        with open(ARQUIVO_INDICE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"datas": []}

def salvar_indice(indice):
    with open(ARQUIVO_INDICE, "w", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False, indent=2)

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    import os
    os.makedirs(DIR_DATA, exist_ok=True)

    data_hoje = hoje_iso()
    arquivo_dia = f"{DIR_DATA}/{data_hoje}.json"

    todos = []
    todos += coleta_stf();  time.sleep(1)
    todos += coleta_stj();  time.sleep(1)
    todos += coleta_tjpe(); time.sleep(1)
    todos += coleta_legislacao()

    entrada = {
        "gerado_em":   datetime.now(timezone.utc).isoformat(),
        "data":        data_hoje,
        "termo_busca": TERMO_BUSCA,
        "total":       len(todos),
        "resultados":  todos,
    }

    # Salva arquivo do dia
    with open(arquivo_dia, "w", encoding="utf-8") as f:
        json.dump(entrada, f, ensure_ascii=False, indent=2)
    print(f"\n✓ Dados do dia salvos em '{arquivo_dia}'.")

    # Atualiza índice
    indice = carregar_indice()
    if data_hoje not in indice["datas"]:
        indice["datas"].append(data_hoje)
    indice["datas"] = sorted(set(indice["datas"]), reverse=True)
    indice["ultima_atualizacao"] = datetime.now(timezone.utc).isoformat()
    salvar_indice(indice)
    print(f"✓ Índice atualizado: {len(indice['datas'])} dia(s) no histórico.")

    # Mantém resultados.json compatível (legado)
    with open(f"{DIR_DATA}/resultados.json", "w", encoding="utf-8") as f:
        json.dump(entrada, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Coleta concluída: {len(todos)} resultado(s) em {data_hoje}.")

if __name__ == "__main__":
    main()
