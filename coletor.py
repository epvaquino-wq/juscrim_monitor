#!/usr/bin/env python3
"""
coletor.py v5.1
═══════════════════════════════════════════════════════════════════════
Correções aplicadas:
  - SSL: desabilita verificação para sites gov.br (certificados problemáticos)
  - STF: URL corrigida + SSL bypass
  - Migalhas: URL corrigida para feed real
  - STJ Informativo (403): removido
  - Filtro de imprensa: ampliado com termos relacionados
  - Tribunais: inclui TODOS os itens das últimas 24h (não só por tema)
  - Gemini: leitura garantida da variável de ambiente
═══════════════════════════════════════════════════════════════════════
"""

import json, re, os, time, ssl, html as html_mod
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta, date
from html.parser import HTMLParser

# ── Configuração ───────────────────────────────────────────────────────────────
TERMO        = "organização criminosa"
DIR_DATA     = "data"
JANELA_HORAS = 24

# Leitura explícita da chave — garante que não há problema de encoding
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

# Termos relacionados para busca na imprensa
TERMOS_BUSCA = [
    "organização criminosa",
    "crime organizado",
    "lei 12.850",
    "colaboração premiada",
    "delação premiada",
    "infiltração policial",
    "organização criminosa",
]

# ── SSL: contexto que ignora certificados inválidos (gov.br) ───────────────────
SSL_VERIFICADO   = ssl.create_default_context()
SSL_SEM_VERIF    = ssl.create_default_context()
SSL_SEM_VERIF.check_hostname = False
SSL_SEM_VERIF.verify_mode    = ssl.CERT_NONE

# ── RSS feeds verificados e corrigidos ─────────────────────────────────────────
#
# Formato: (fonte, label, url_principal, url_fallback_ou_None, usar_ssl_sem_verif)
#
FEEDS = [
    # Tribunais — inclui TODOS os itens do dia (não filtra por tema)
    ("STF", "STF — Notícias",
     "https://www.stf.jus.br/portal/RSS/noticiaRss.asp?codigo=1",
     "https://noticias.stf.jus.br/feed/",
     True),   # SSL bypass para gov.br

    ("STF", "STF — Plenário",
     "https://www.stf.jus.br/portal/RSS/noticiaRss.asp?codigo=3",
     None,
     True),

    ("STJ", "STJ — Notícias",
     "https://res.stj.jus.br/hrestp-c-portalp/RSS.xml",
     None,
     False),

    ("CNJ", "CNJ — Notícias",
     "https://www.cnj.jus.br/feed/",
     None,
     False),

    # Imprensa jurídica — filtra por termos relacionados
    ("Conjur",    "Conjur",
     "https://www.conjur.com.br/rss.xml",
     None,
     False),

    ("Jota",      "Jota",
     "https://www.jota.info/feed",
     None,
     False),

    ("DirDir",    "Dizer o Direito",
     "https://www.dizerodireito.com.br/feeds/posts/default",
     None,
     False),

    # Migalhas — URL corrigida (feed real identificado)
    ("Migalhas",  "Migalhas",
     "https://www.migalhas.com.br/arquivo/rss",
     "https://www.migalhas.com.br/feed",
     False),
]

FONTES_TRIBUNAL = {"STF", "STJ", "CNJ", "TJPE", "LEG", "DJe"}

# ── Utilitários ────────────────────────────────────────────────────────────────

def get_url(url, sem_ssl=False, timeout=25):
    ctx = SSL_SEM_VERIF if sem_ssl else SSL_VERIFICADO
    req = urllib.request.Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
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
        return json.loads(r.read())

def limpa(txt):
    txt = html_mod.unescape(txt or "")
    txt = re.sub(r"<!\[CDATA\[|\]\]>", "", txt)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()

def trunca(txt, n=400):
    txt = limpa(txt)
    return txt[:n].rsplit(" ", 1)[0] + "…" if len(txt) > n else txt

def hoje_iso():
    return date.today().isoformat()

def agora_utc():
    return datetime.now(timezone.utc)

# ── Parser de data ─────────────────────────────────────────────────────────────
FMTS = [
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S GMT",
    "%a, %d %b %Y %H:%M:%S +0000",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%Y-%m-%d",
]

def parse_dt(s):
    if not s:
        return None
    s = re.sub(r"\s+[A-Z]{2,4}$", "", s.strip())
    for fmt in FMTS:
        try:
            d = datetime.strptime(s[:30], fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None

def dentro_janela(dt_str):
    dt = parse_dt(dt_str)
    if dt is None:
        return True
    return (agora_utc() - dt) <= timedelta(hours=JANELA_HORAS)

def fmt_br(dt_str):
    dt = parse_dt(dt_str)
    return dt.strftime("%d/%m/%Y") if dt else (dt_str or "")[:10]

# ── Parser RSS/Atom ────────────────────────────────────────────────────────────

class RSSParser(HTMLParser):
    CAMPOS = {"title","link","description","summary","content",
              "pubdate","published","updated","dc:date",
              "category","author","id","guid"}

    def __init__(self):
        super().__init__()
        self.items = []
        self._c    = {}
        self._tag  = None
        self._in   = False

    def handle_starttag(self, tag, attrs):
        self._tag = tag.lower()
        if self._tag in ("item", "entry"):
            self._in = True
            self._c  = {}

    def handle_endtag(self, tag):
        if tag.lower() in ("item", "entry") and self._in:
            self.items.append(self._c)
            self._in = False
        self._tag = None

    def handle_data(self, data):
        if self._in and self._tag in self.CAMPOS:
            self._c[self._tag] = self._c.get(self._tag, "") + data

def parse_rss(xml):
    p = RSSParser()
    p.feed(xml)
    return p.items

def url_item(it):
    for k in ("link", "guid", "id"):
        v = (it.get(k) or "").strip()
        if v.startswith("http"):
            return v
    return ""

def data_item(it):
    for k in ("pubdate", "published", "updated", "dc:date"):
        v = (it.get(k) or "").strip()
        if v:
            return v
    return ""

def relevante(titulo, desc, eh_tribunal):
    """Decide se o item é relevante para incluir."""
    if eh_tribunal:
        return True   # tribunais: inclui tudo das últimas 24h
    texto = (titulo + " " + desc).lower()
    return any(t in texto for t in TERMOS_BUSCA)

# ── Coleta de um feed ──────────────────────────────────────────────────────────

def coletar_feed(fonte, label, url_p, url_f, sem_ssl):
    urls = [url_p] + ([url_f] if url_f else [])
    xml  = None
    for url in urls:
        try:
            xml = get_url(url, sem_ssl=sem_ssl)
            print(f"  ✓ {url}")
            break
        except Exception as e:
            print(f"  ✗ {url} → {e}")

    if not xml:
        return []

    eh_tribunal = fonte in FONTES_TRIBUNAL
    resultado   = []

    for it in parse_rss(xml):
        titulo = limpa(it.get("title", ""))
        desc   = limpa(it.get("description","") or it.get("summary","") or it.get("content",""))
        data_r = data_item(it)
        url_i  = url_item(it)

        if not titulo or len(titulo) < 8:
            continue
        if not dentro_janela(data_r):
            continue
        if not relevante(titulo, desc, eh_tribunal):
            continue

        resultado.append({
            "fonte":     fonte,
            "label":     label,
            "titulo":    titulo,
            "resumo":    trunca(desc),
            "numero":    "",
            "relator":   limpa(it.get("author", "")),
            "data":      fmt_br(data_r),
            "data_iso":  data_r,
            "url":       url_i,
            "resumo_ia": "",
        })

    print(f"    → {len(resultado)} resultado(s) relevante(s) nas últimas {JANELA_HORAS}h")
    return resultado

# ── Legislação base ────────────────────────────────────────────────────────────

def legislacao_base():
    return [
        {
            "fonte": "LEG", "label": "Planalto",
            "titulo": "Lei nº 12.850/2013 — Define organização criminosa",
            "resumo": (
                "Define organização criminosa e dispõe sobre investigação criminal, "
                "meios de obtenção de prova (colaboração premiada, captação ambiental, "
                "infiltração policial), infrações penais correlatas e procedimento criminal."
            ),
            "numero": "12.850/2013", "relator": "",
            "data": "02/08/2013", "data_iso": "2013-08-02",
            "url": "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2013/lei/l12850.htm",
            "resumo_ia": "",
        },
        {
            "fonte": "LEG", "label": "Planalto",
            "titulo": "Lei nº 12.694/2012 — Julgamento colegiado em 1º grau",
            "resumo": (
                "Dispõe sobre julgamento colegiado em primeiro grau em crimes "
                "praticados por organizações criminosas."
            ),
            "numero": "12.694/2012", "relator": "",
            "data": "24/07/2012", "data_iso": "2012-07-24",
            "url": "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2012/lei/l12694.htm",
            "resumo_ia": "",
        },
    ]

# ── Gemini ─────────────────────────────────────────────────────────────────────

def gemini_call(prompt, max_tokens=300):
    if not GEMINI_KEY:
        return ""
    try:
        url  = f"{GEMINI_URL}?key={GEMINI_KEY}"
        resp = post_json(url, {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0.25,
            },
        })
        return resp["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"  [Gemini] Erro: {e}")
        return ""

def resumo_item(item):
    return gemini_call(f"""Você é assistente jurídico especializado em direito penal brasileiro.
Analise este item sobre organização criminosa em 2-3 frases.
Destaque: relevância prática, impacto e contexto normativo (Lei 12.850/2013 quando aplicável).
Português, linguagem técnica acessível.

Fonte: {item['label']}
Título: {item['titulo']}
Resumo: {item['resumo'] or '(não disponível)'}
Data: {item['data']}

Análise (máx. 3 frases):""", max_tokens=220)

def painel_do_dia(itens):
    if not itens:
        return ""
    linhas = [
        f"{i}. [{it['fonte']}] {it['titulo']} — {(it['resumo'] or '')[:160]} (Data: {it['data']})"
        for i, it in enumerate(itens[:20], 1)
    ]
    return gemini_call(f"""Você é assistente jurídico especializado em direito penal brasileiro.
Elabore um PAINEL EXECUTIVO DIÁRIO sobre "organização criminosa". Data: {hoje_iso()}.

Itens coletados:
{chr(10).join(linhas)}

Estrutura obrigatória:

**PANORAMA DO DIA**
(2-3 frases sobre volume e natureza das atualizações)

**DESTAQUES JURISPRUDENCIAIS**
(STF, STJ, CNJ — se houver; senão: "Nenhuma decisão nova nas últimas 24h.")

**IMPRENSA JURÍDICA**
(Conjur, Jota, Migalhas, Dizer o Direito — se houver)

**LEGISLAÇÃO**
(normas relevantes)

**TENDÊNCIAS**
(1-2 frases finais)

Máx. 300 palavras. Objetivo e técnico.""", max_tokens=600)

# ── Índice ─────────────────────────────────────────────────────────────────────

def load_indice():
    try:
        with open(f"{DIR_DATA}/indice.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"datas": []}

def save_indice(idx):
    with open(f"{DIR_DATA}/indice.json", "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(DIR_DATA, exist_ok=True)
    data_hoje = hoje_iso()

    print(f"\n{'═'*62}")
    print(f"  JusCrim Coletor v5.1 — {data_hoje}")
    print(f"  Janela: últimas {JANELA_HORAS}h")
    print(f"  Gemini: {'✓ ativo' if GEMINI_KEY else '✗ não configurado'}")
    if not GEMINI_KEY:
        print(f"  → Verifique: Settings → Secrets → GEMINI_API_KEY")
    print(f"{'═'*62}\n")

    # 1. Coleta feeds
    todos = []
    for fonte, label, url, fallback, sem_ssl in FEEDS:
        print(f"[{fonte}] {label}")
        todos += coletar_feed(fonte, label, url, fallback, sem_ssl)
        time.sleep(1.5)

    # 2. Legislação base
    todos += legislacao_base()

    # 3. Deduplicação por URL
    vistos, unicos = set(), []
    for it in todos:
        chave = it.get("url") or it.get("titulo", "")
        if chave and chave not in vistos:
            vistos.add(chave)
            unicos.append(it)
    todos = unicos

    print(f"\n{'─'*62}")
    print(f"  Total: {len(todos)} item(s)")
    print(f"{'─'*62}\n")

    # 4. Resumos individuais
    if GEMINI_KEY:
        print(f"[Gemini] Gerando {len(todos)} resumos individuais…")
        for i, it in enumerate(todos, 1):
            print(f"  [{i}/{len(todos)}] {it['titulo'][:60]}…")
            it["resumo_ia"] = resumo_item(it)
            time.sleep(1.2)
    else:
        print("[Gemini] Chave não encontrada — resumos omitidos.")

    # 5. Painel do dia
    print("\n[Gemini] Gerando painel executivo…")
    painel = painel_do_dia(todos) if GEMINI_KEY else (
        "Configure GEMINI_API_KEY nos GitHub Secrets para ativar o painel de IA."
    )

    # 6. Salva
    entrada = {
        "gerado_em":    datetime.now(timezone.utc).isoformat(),
        "data":         data_hoje,
        "janela_horas": JANELA_HORAS,
        "termo_busca":  TERMO,
        "total":        len(todos),
        "resumo_dia":   painel,
        "resultados":   todos,
    }

    arq = f"{DIR_DATA}/{data_hoje}.json"
    with open(arq, "w", encoding="utf-8") as f:
        json.dump(entrada, f, ensure_ascii=False, indent=2)

    with open(f"{DIR_DATA}/resultados.json", "w", encoding="utf-8") as f:
        json.dump(entrada, f, ensure_ascii=False, indent=2)

    # 7. Índice
    idx = load_indice()
    idx["datas"] = sorted(set(idx.get("datas", []) + [data_hoje]), reverse=True)
    idx["ultima_atualizacao"] = datetime.now(timezone.utc).isoformat()
    save_indice(idx)

    print(f"\n{'═'*62}")
    print(f"  ✅ {len(todos)} item(s) → {arq}")
    print(f"  📅 Histórico: {len(idx['datas'])} dia(s)")
    print(f"{'═'*62}\n")

if __name__ == "__main__":
    main()
