#!/usr/bin/env python3
"""
coletor.py v4
═══════════════════════════════════════════════════════════════════════════════
Coleta das ÚLTIMAS 24 HORAS sobre "organização criminosa".

Fontes:
  Tribunais  → STF · STJ · TJPE · DJe
  Legislação → Planalto · LexML
  Imprensa   → Migalhas · Conjur · Jota · Dizer o Direito

IA: Google Gemini (gratuito) gera:
  • resumo_ia  — análise individual por item (gerado durante coleta)
  • resumo_dia — painel executivo geral do dia (gerado ao final)

Variáveis de ambiente (GitHub Secrets):
  GEMINI_API_KEY  ← obrigatório para resumos de IA

Saída:
  data/YYYY-MM-DD.json
  data/indice.json
  data/resultados.json  (alias do dia mais recente)
═══════════════════════════════════════════════════════════════════════════════
"""

import json, re, os, sys, time, html as html_mod
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta, date
from html.parser import HTMLParser

# ── Configuração ──────────────────────────────────────────────────────────────
TERMO          = "organização criminosa"
TERMO_URL      = urllib.parse.quote(TERMO)
DIR_DATA       = "data"
JANELA_HORAS   = 24
MAX_FONTE      = 12

GEMINI_KEY     = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL     = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

# ── Utilitários ────────────────────────────────────────────────────────────────

def get_url(url, timeout=25, extra_headers=None):
    h = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
    }
    if extra_headers:
        h.update(extra_headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        charset = r.headers.get_content_charset() or "utf-8"
        return r.read().decode(charset, errors="replace")

def post_json(url, payload, timeout=30):
    body = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def limpa(txt):
    txt = html_mod.unescape(txt or "")
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()

def trunca(txt, n=420):
    txt = limpa(txt)
    return txt[:n].rsplit(" ", 1)[0] + "…" if len(txt) > n else txt

def hoje_iso():
    return date.today().isoformat()

def agora_utc():
    return datetime.now(timezone.utc)

FMTS_DATA = [
    "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",   "%d/%m/%Y %H:%M",      "%d/%m/%Y",
    "%Y-%m-%d",            "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S GMT",
]

def parse_dt(s):
    if not s:
        return None
    for fmt in FMTS_DATA:
        try:
            d = datetime.strptime(s.strip()[:30], fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None

def dentro_janela(dt_str):
    dt = parse_dt(dt_str)
    if dt is None:
        return True
    return (agora_utc() - dt) <= timedelta(hours=JANELA_HORAS)

def fmt_data(dt_str):
    dt = parse_dt(dt_str)
    return dt.strftime("%d/%m/%Y") if dt else (dt_str or "")[:10]

# ── Parser RSS ─────────────────────────────────────────────────────────────────

class RSS(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []; self._c = {}; self._t = None; self._in = False

    def handle_starttag(self, tag, attrs):
        self._t = tag.lower()
        if self._t == "item":
            self._in = True; self._c = {}

    def handle_endtag(self, tag):
        if tag.lower() == "item" and self._in:
            self.items.append(self._c); self._in = False
        self._t = None

    def handle_data(self, data):
        if self._in and self._t in ("title","link","description","pubdate","dc:date","category"):
            self._c[self._t] = self._c.get(self._t,"") + data

def rss(xml):
    p = RSS(); p.feed(xml); return p.items

def item_de_rss(i, fonte, label):
    t   = limpa(i.get("title",""))
    d   = i.get("pubdate","") or i.get("dc:date","")
    url = i.get("link","").strip()
    desc= limpa(i.get("description",""))
    if not t or len(t) < 8:
        return None
    if not dentro_janela(d):
        return None
    return {"fonte": fonte, "label": label, "titulo": t,
            "resumo": trunca(desc), "numero": "", "relator": "",
            "data": fmt_data(d), "url": url, "resumo_ia": ""}

# ══════════════════════════════════════════════════════════════════════════════
#  FONTES TRIBUNAIS
# ══════════════════════════════════════════════════════════════════════════════

def coleta_stf():
    print("[STF] Coletando…")
    out = []
    try:
        raw = get_url(
            f"https://jurisprudencia.stf.jus.br/api/search/search"
            f"?query={TERMO_URL}&sort=dtDecisao&sortBy=desc&offset=0&limit={MAX_FONTE}"
        )
        data = json.loads(raw)
        for h in data.get("hits",{}).get("hits",[]):
            s  = h.get("_source",{})
            dt = s.get("dataJulgamento","") or s.get("dataPublicacao","")
            if not dentro_janela(dt):
                continue
            t = limpa(s.get("nome","") or s.get("nomeProcesso",""))
            if not t:
                continue
            out.append({
                "fonte": "STF", "label": "STF",
                "titulo":  t,
                "resumo":  trunca(s.get("ementa","") or s.get("observacao","")),
                "numero":  s.get("numeroProcesso",""),
                "relator": limpa(s.get("nomeRelator","")),
                "data":    fmt_data(dt),
                "url":     f"https://jurisprudencia.stf.jus.br/pages/search/resultado/{h.get('_id','')}/relevance",
                "resumo_ia": "",
            })
    except Exception as e:
        print(f"  [STF] API: {e} → RSS")
        try:
            xml = get_url(f"https://jurisprudencia.stf.jus.br/api/search/rss?query={TERMO_URL}&sort=dtDecisao&sortBy=desc")
            for i in rss(xml)[:MAX_FONTE]:
                it = item_de_rss(i, "STF", "STF")
                if it:
                    out.append(it)
        except Exception as e2:
            print(f"  [STF] RSS: {e2}")
    print(f"  [STF] {len(out)} resultado(s).")
    return out

def coleta_stj():
    print("[STJ] Coletando…")
    out = []
    try:
        raw = get_url(
            f"https://scon.stj.jus.br/SCON/pesquisar.jsp"
            f"?b=ACOR&livre={TERMO_URL}&tipo_visualizacao=RESUMO"
            f"&operador=E&p=true&l={MAX_FONTE}&i=1&formato=JSON&ordenacao=MAI_REC"
        )
        data = json.loads(raw)
        for d in data.get("documento",[]):
            dt = d.get("dtPublicacao","") or d.get("dataJulgamento","")
            if not dentro_janela(dt):
                continue
            t = limpa(d.get("docTitulo","") or d.get("titulo",""))
            if not t:
                continue
            out.append({
                "fonte": "STJ", "label": "STJ",
                "titulo":  t,
                "resumo":  trunca(d.get("ementa","") or d.get("docEmenta","")),
                "numero":  d.get("numProcesso","") or d.get("docNumero",""),
                "relator": limpa(d.get("ministroRelator","") or d.get("relator","")),
                "data":    fmt_data(dt),
                "url":     d.get("urlDocumento","https://scon.stj.jus.br/SCON/"),
                "resumo_ia": "",
            })
    except Exception as e:
        print(f"  [STJ] API: {e} → RSS notícias")
        try:
            xml = get_url("https://www.stj.jus.br/sites/portalp/Paginas/Comunicacao/Noticias/RSS.aspx")
            for i in rss(xml):
                desc = limpa(i.get("description",""))
                t    = limpa(i.get("title",""))
                if TERMO.lower() not in (t+desc).lower():
                    continue
                it = item_de_rss(i, "STJ", "STJ")
                if it:
                    out.append(it)
        except Exception as e2:
            print(f"  [STJ] RSS: {e2}")
    print(f"  [STJ] {len(out)} resultado(s).")
    return out

def coleta_tjpe():
    print("[TJPE] Coletando…")
    out = []
    try:
        raw  = get_url(f"https://www.tjpe.jus.br/jurisprudencia/pesquisar?tipo=0&pesquisa={TERMO_URL}&formato=JSON")
        data = json.loads(raw)
        docs = data if isinstance(data,list) else data.get("resultado", data.get("documentos",[]))
        for d in docs[:MAX_FONTE]:
            dt = d.get("dataJulgamento","") or d.get("data","")
            if not dentro_janela(dt):
                continue
            t = limpa(d.get("ementa","") or d.get("titulo",""))
            if not t:
                continue
            out.append({
                "fonte": "TJPE", "label": "TJPE",
                "titulo":  trunca(t, 180),
                "resumo":  "",
                "numero":  d.get("processo","") or d.get("numero",""),
                "relator": limpa(d.get("relator","")),
                "data":    fmt_data(dt),
                "url":     d.get("url","https://www.tjpe.jus.br/jurisprudencia"),
                "resumo_ia": "",
            })
    except Exception as e:
        print(f"  [TJPE] {e}")
    print(f"  [TJPE] {len(out)} resultado(s).")
    return out

def coleta_dje():
    """Diário da Justiça Eletrônico — RSS do CNJ."""
    print("[DJe] Coletando…")
    out = []
    urls_rss = [
        "https://www.cnj.jus.br/feed/",
        "https://portal.stf.jus.br/noticias/rss.asp",
    ]
    for rss_url in urls_rss:
        try:
            xml = get_url(rss_url)
            for i in rss(xml):
                t    = limpa(i.get("title",""))
                desc = limpa(i.get("description",""))
                if TERMO.lower() not in (t+desc).lower():
                    continue
                it = item_de_rss(i, "DJe", "DJe / CNJ")
                if it:
                    out.append(it)
        except Exception as e:
            print(f"  [DJe] {rss_url}: {e}")
    print(f"  [DJe] {len(out)} resultado(s).")
    return out

# ══════════════════════════════════════════════════════════════════════════════
#  LEGISLAÇÃO
# ══════════════════════════════════════════════════════════════════════════════

def coleta_legislacao():
    print("[LEG] Normas base…")
    normas = [
        {
            "titulo":  "Lei nº 12.850/2013 — Define organização criminosa",
            "resumo":  "Principal marco normativo. Define organização criminosa, dispõe sobre investigação criminal, meios de obtenção de prova, infrações penais correlatas e procedimento criminal.",
            "numero":  "12.850/2013", "data": "02/08/2013",
            "url":     "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2013/lei/l12850.htm",
        },
        {
            "titulo":  "Lei nº 12.694/2012 — Julgamento colegiado em 1º grau",
            "resumo":  "Dispõe sobre julgamento colegiado em primeiro grau de jurisdição de crimes praticados por organizações criminosas.",
            "numero":  "12.694/2012", "data": "24/07/2012",
            "url":     "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2012/lei/l12694.htm",
        },
    ]
    out = [{"fonte":"LEG","label":"Legislação","relator":"","resumo_ia":"",**n} for n in normas]

    # Busca dinâmica no LexML
    try:
        xml = get_url(
            "https://www.lexml.gov.br/busca/SRU?operation=searchRetrieve"
            "&query=organizacao+criminosa&maximumRecords=5&recordSchema=opendocument",
            timeout=15
        )
        titulos = re.findall(r"<dc:title[^>]*>([^<]+)</dc:title>", xml)
        links   = re.findall(r"<dc:identifier[^>]*>(https?://[^<]+)</dc:identifier>", xml)
        datas   = re.findall(r"<dc:date[^>]*>([^<]+)</dc:date>", xml)
        for i, t in enumerate(titulos[:5]):
            t = limpa(t)
            if t and not any(t[:30] in r["titulo"] for r in out):
                out.append({"fonte":"LEG","label":"Legislação","titulo":t,"resumo":"Norma localizada no acervo LexML.","numero":"","relator":"","data":datas[i] if i<len(datas) else "","url":links[i] if i<len(links) else "https://www.lexml.gov.br","resumo_ia":""})
    except Exception as e:
        print(f"  [LEG] LexML: {e}")
    print(f"  [LEG] {len(out)} norma(s).")
    return out

# ══════════════════════════════════════════════════════════════════════════════
#  IMPRENSA JURÍDICA
# ══════════════════════════════════════════════════════════════════════════════

IMPRENSA = [
    {
        "fonte": "Migalhas",
        "label": "Migalhas",
        "rss":   "https://www.migalhas.com.br/rss/quentes",
        "extra": ["https://www.migalhas.com.br/rss/penais"],
    },
    {
        "fonte": "Conjur",
        "label": "Conjur",
        "rss":   "https://www.conjur.com.br/rss.xml",
    },
    {
        "fonte": "Jota",
        "label": "Jota",
        "rss":   "https://www.jota.info/feed",
    },
    {
        "fonte": "DizeODireito",
        "label": "Dizer o Direito",
        "rss":   "https://www.dizerodireito.com.br/feeds/posts/default",
    },
]

def coleta_imprensa():
    print("[Imprensa] Coletando…")
    out = []
    for cfg in IMPRENSA:
        feeds = [cfg["rss"]] + cfg.get("extra", [])
        encontrados = 0
        for feed_url in feeds:
            try:
                xml = get_url(feed_url)
                for i in rss(xml):
                    t    = limpa(i.get("title",""))
                    desc = limpa(i.get("description",""))
                    cat  = limpa(i.get("category",""))
                    if TERMO.lower() not in (t+desc+cat).lower():
                        continue
                    it = item_de_rss(i, cfg["fonte"], cfg["label"])
                    if it:
                        it["label"] = cfg["label"]
                        out.append(it)
                        encontrados += 1
            except Exception as e:
                print(f"  [{cfg['fonte']}] {feed_url}: {e}")
        print(f"  [{cfg['fonte']}] {encontrados} resultado(s).")
    return out

# ══════════════════════════════════════════════════════════════════════════════
#  GEMINI — RESUMOS DE IA
# ══════════════════════════════════════════════════════════════════════════════

def gemini(prompt, max_tokens=512):
    """Chama Gemini 1.5 Flash (gratuito) e retorna texto."""
    if not GEMINI_KEY:
        return ""
    try:
        url  = f"{GEMINI_URL}?key={GEMINI_KEY}"
        resp = post_json(url, {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
        })
        return resp["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"  [Gemini] Erro: {e}")
        return ""

def resumo_item(item):
    """Gera análise jurídica individual para um item."""
    prompt = f"""Você é um assistente jurídico especializado em direito penal brasileiro.
Analise o seguinte resultado sobre organização criminosa e produza uma análise jurídica
objetiva em 2-3 frases, destacando: relevância, impacto prático e contexto normativo (Lei 12.850/2013).
Escreva em português, linguagem técnica mas acessível.

Fonte: {item.get('fonte','')} — {item.get('label','')}
Título: {item.get('titulo','')}
Ementa/Resumo: {item.get('resumo','(não disponível)')}
Número: {item.get('numero','')}
Relator: {item.get('relator','')}
Data: {item.get('data','')}

Análise jurídica (máximo 3 frases):"""
    return gemini(prompt, max_tokens=200)

def resumo_dia(todos):
    """Gera painel executivo geral do dia."""
    if not todos:
        return ""
    linhas = []
    for i, it in enumerate(todos[:25], 1):
        linhas.append(
            f"{i}. [{it.get('fonte','')}] {it.get('titulo','')} — "
            f"{it.get('resumo','')[:180] or '(sem resumo)'} (Data: {it.get('data','')})"
        )
    bloco = "\n".join(linhas)
    prompt = f"""Você é um assistente jurídico especializado em direito penal brasileiro.
Elabore um PAINEL EXECUTIVO DIÁRIO em português sobre os seguintes resultados de monitoramento
de "organização criminosa" coletados hoje de fontes oficiais e jornalísticas abalizadas.

{bloco}

Estruture seu painel com as seguintes seções (use os títulos exatos):

**PANORAMA DO DIA**
(2-3 frases descrevendo o volume e natureza das atualizações)

**DESTAQUES JURISPRUDENCIAIS**
(principais decisões de STF, STJ e TJPE — se houver)

**IMPRENSA JURÍDICA**
(principais pautas do Migalhas, Conjur, Jota e Dizer o Direito — se houver)

**LEGISLAÇÃO E NORMAS**
(normas relevantes mencionadas — se houver)

**TENDÊNCIAS E OBSERVAÇÕES**
(1-2 frases finais sobre padrões ou pontos de atenção)

Seja objetivo, técnico e direto. Máximo 350 palavras."""
    return gemini(prompt, max_tokens=600)

# ══════════════════════════════════════════════════════════════════════════════
#  ÍNDICE
# ══════════════════════════════════════════════════════════════════════════════

def load_indice():
    try:
        with open(f"{DIR_DATA}/indice.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"datas": []}

def save_indice(idx):
    with open(f"{DIR_DATA}/indice.json", "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    os.makedirs(DIR_DATA, exist_ok=True)
    data_hoje = hoje_iso()

    print(f"\n{'═'*60}")
    print(f"  JusCrim Coletor v4 — {data_hoje}")
    print(f"  Janela: últimas {JANELA_HORAS}h")
    print(f"  IA: {'Gemini ativo ✓' if GEMINI_KEY else 'Gemini NÃO configurado — resumos desativados'}")
    print(f"{'═'*60}\n")

    todos = []
    todos += coleta_stf();       time.sleep(1)
    todos += coleta_stj();       time.sleep(1)
    todos += coleta_tjpe();      time.sleep(1)
    todos += coleta_dje();       time.sleep(1)
    todos += coleta_legislacao(); time.sleep(1)
    todos += coleta_imprensa()

    # Remove duplicatas por URL
    vistos, unicos = set(), []
    for it in todos:
        k = it.get("url","") or it.get("titulo","")
        if k not in vistos:
            vistos.add(k); unicos.append(it)
    todos = unicos

    print(f"\n[IA] Gerando resumos individuais ({len(todos)} itens)…")
    if GEMINI_KEY:
        for idx, it in enumerate(todos, 1):
            print(f"  [{idx}/{len(todos)}] {it.get('titulo','')[:60]}…")
            it["resumo_ia"] = resumo_item(it)
            time.sleep(1.2)   # respeita rate-limit gratuito do Gemini (60 req/min)
    else:
        print("  Gemini não configurado — resumos individuais pulados.")

    print("\n[IA] Gerando painel executivo do dia…")
    painel = resumo_dia(todos) if GEMINI_KEY else (
        "Configure GEMINI_API_KEY nos GitHub Secrets para ativar o painel executivo com IA."
    )

    entrada = {
        "gerado_em":    datetime.now(timezone.utc).isoformat(),
        "data":         data_hoje,
        "janela_horas": JANELA_HORAS,
        "termo_busca":  TERMO,
        "total":        len(todos),
        "resumo_dia":   painel,
        "resultados":   todos,
    }

    # Arquivo do dia
    arq = f"{DIR_DATA}/{data_hoje}.json"
    with open(arq, "w", encoding="utf-8") as f:
        json.dump(entrada, f, ensure_ascii=False, indent=2)

    # Alias legado
    with open(f"{DIR_DATA}/resultados.json", "w", encoding="utf-8") as f:
        json.dump(entrada, f, ensure_ascii=False, indent=2)

    # Índice
    idx = load_indice()
    idx["datas"] = sorted(set(idx.get("datas",[]) + [data_hoje]), reverse=True)
    idx["ultima_atualizacao"] = datetime.now(timezone.utc).isoformat()
    save_indice(idx)

    print(f"\n{'═'*60}")
    print(f"  ✅ {len(todos)} resultado(s) → {arq}")
    print(f"  📅 Histórico: {len(idx['datas'])} dia(s)")
    print(f"{'═'*60}\n")

if __name__ == "__main__":
    main()
