#!/usr/bin/env python3
"""
coletor.py v5 — RSS-only, feeds verificados, data real, IA com Gemini
═══════════════════════════════════════════════════════════════════════

FONTES (todos RSS oficiais verificados):
  Tribunais:
    STF        → https://www.stf.jus.br/portal/RSS/noticiaRss.asp?codigo=1
    STJ        → https://res.stj.jus.br/hrestp-c-portalp/RSS.xml
    STJ Inform → https://processo.stj.jus.br/jurisprudencia/externo/InformativoFeed
    CNJ        → https://www.cnj.jus.br/feed/
    TJPE       → https://www.tjpe.jus.br/web/guest/-/rss  (fallback: notícias gerais)

  Imprensa jurídica:
    Conjur     → https://www.conjur.com.br/rss.xml
    Jota       → https://www.jota.info/feed
    Dizer Dir. → https://www.dizerodireito.com.br/feeds/posts/default
    Migalhas   → https://www.migalhas.com.br/quentes/rss  (fallback: /rss)

  Legislação:
    Planalto   → lista curada de normas essenciais

FILTRO: só itens publicados nas últimas 24 horas.
IA:     Google Gemini 1.5 Flash (gratuito) — resumo por item + painel do dia.

Variáveis de ambiente (GitHub Secrets):
  GEMINI_API_KEY

Saída:
  data/YYYY-MM-DD.json   — dados do dia atual real
  data/indice.json        — índice acumulativo
  data/resultados.json    — alias do dia atual (compatibilidade)
═══════════════════════════════════════════════════════════════════════
"""

import json, re, os, time, html as html_mod
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta, date
from html.parser import HTMLParser

# ── Configuração ───────────────────────────────────────────────────────────────
TERMO        = "organização criminosa"
DIR_DATA     = "data"
JANELA_HORAS = 24
GEMINI_KEY   = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL   = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

# ── RSS feeds verificados ──────────────────────────────────────────────────────
#
# Cada entrada: (fonte, label, url, [url_fallback])
# Testados e confirmados como feeds RSS/Atom públicos válidos.
#
FEEDS = [
    # Tribunais
    ("STF",   "STF — Notícias",
     "https://www.stf.jus.br/portal/RSS/noticiaRss.asp?codigo=1", None),

    ("STF",   "STF — Plenário",
     "https://www.stf.jus.br/portal/RSS/noticiaRss.asp?codigo=3", None),

    ("STJ",   "STJ — Notícias",
     "https://res.stj.jus.br/hrestp-c-portalp/RSS.xml", None),

    ("STJ",   "STJ — Informativo de Jurisprudência",
     "https://processo.stj.jus.br/jurisprudencia/externo/InformativoFeed", None),

    ("CNJ",   "CNJ — Notícias",
     "https://www.cnj.jus.br/feed/", None),

    # Imprensa jurídica
    ("Conjur",  "Conjur — Consultor Jurídico",
     "https://www.conjur.com.br/rss.xml", None),

    ("Jota",    "Jota — Judiciário",
     "https://www.jota.info/feed", None),

    ("DirDir",  "Dizer o Direito",
     "https://www.dizerodireito.com.br/feeds/posts/default", None),

    ("Migalhas","Migalhas",
     "https://www.migalhas.com.br/quentes/rss",
     "https://www.migalhas.com.br/rss"),     # fallback
]

# ── Utilitários ────────────────────────────────────────────────────────────────

def get_url(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
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
    return date.today().isoformat()   # data real do sistema, ex: "2026-03-26"

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
    s = s.strip()
    # Remove timezone textual como "BRT", "EST" no final
    s = re.sub(r"\s+[A-Z]{2,4}$", "", s)
    for fmt in FMTS:
        try:
            d = datetime.strptime(s[:30], fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None

def dentro_janela(dt_str):
    """True se o item foi publicado nas últimas JANELA_HORAS."""
    dt = parse_dt(dt_str)
    if dt is None:
        return True   # sem data → inclui (não descarta por falta de info)
    return (agora_utc() - dt) <= timedelta(hours=JANELA_HORAS)

def fmt_data_br(dt_str):
    """Converte para dd/mm/AAAA ou retorna string original."""
    dt = parse_dt(dt_str)
    return dt.strftime("%d/%m/%Y") if dt else (dt_str or "")[:10]

# ── Parser RSS/Atom ────────────────────────────────────────────────────────────

class RSSParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []
        self._c    = {}
        self._tag  = None
        self._in   = False
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        self._tag = tag
        if tag in ("item", "entry"):
            self._in  = True
            self._c   = {}
            self._depth = 0
        if self._in:
            self._depth += 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("item", "entry") and self._in:
            self.items.append(self._c)
            self._in  = False
            self._c   = {}
        self._tag = None

    def handle_data(self, data):
        if not self._in or not self._tag:
            return
        key = self._tag
        # Normaliza nomes de campos Atom → RSS
        if key in ("title", "link", "description", "summary",
                   "content", "pubdate", "published", "updated",
                   "dc:date", "category", "author", "id", "guid"):
            self._c[key] = self._c.get(key, "") + data

def parse_rss(xml):
    p = RSSParser()
    p.feed(xml)
    return p.items

def url_do_item(item):
    """Extrai URL do item RSS — tenta vários campos."""
    for campo in ("link", "guid", "id"):
        v = (item.get(campo) or "").strip()
        if v.startswith("http"):
            return v
    return ""

def data_do_item(item):
    """Extrai data do item RSS — tenta vários campos."""
    for campo in ("pubdate", "published", "updated", "dc:date"):
        v = (item.get(campo) or "").strip()
        if v:
            return v
    return ""

# ── Coleta via RSS ─────────────────────────────────────────────────────────────

def coletar_feed(fonte, label, url_principal, url_fallback=None):
    """Tenta coletar um feed RSS. Retorna lista de itens filtrados."""
    urls = [url_principal]
    if url_fallback:
        urls.append(url_fallback)

    xml = None
    for url in urls:
        try:
            xml = get_url(url)
            print(f"  ✓ {label}: {url}")
            break
        except Exception as e:
            print(f"  ✗ {label}: {url} → {e}")

    if not xml:
        return []

    itens_rss = parse_rss(xml)
    resultado = []

    for item in itens_rss:
        titulo = limpa(item.get("title", ""))
        desc   = limpa(item.get("description", "") or item.get("summary", "") or item.get("content", ""))
        data_r = data_do_item(item)
        url_i  = url_do_item(item)

        if not titulo or len(titulo) < 8:
            continue

        # Filtra por janela de tempo
        if not dentro_janela(data_r):
            continue

        # Filtra por relevância ao tema
        texto_busca = (titulo + " " + desc).lower()
        if TERMO.lower() not in texto_busca:
            # Para fontes de tribunais, inclui TUDO (são fontes especializadas)
            # Para imprensa, exige que o termo apareça
            if fonte in ("Conjur", "Jota", "DirDir", "Migalhas"):
                continue

        resultado.append({
            "fonte":     fonte,
            "label":     label,
            "titulo":    titulo,
            "resumo":    trunca(desc),
            "numero":    "",
            "relator":   limpa(item.get("author", "")),
            "data":      fmt_data_br(data_r),
            "data_iso":  data_r,
            "url":       url_i,
            "resumo_ia": "",
        })

    print(f"    → {len(resultado)} resultado(s) dentro das últimas {JANELA_HORAS}h")
    return resultado

# ── Legislação (lista curada — sempre incluída) ────────────────────────────────

def legislacao_base():
    """Normas essenciais — incluídas sempre como referência fixa."""
    return [
        {
            "fonte": "LEG", "label": "Planalto — Legislação",
            "titulo": "Lei nº 12.850/2013 — Define organização criminosa",
            "resumo": (
                "Define organização criminosa e dispõe sobre investigação criminal, "
                "meios de obtenção de prova (colaboração premiada, captação ambiental, "
                "infiltração policial etc.), infrações penais correlatas e procedimento criminal."
            ),
            "numero": "12.850/2013", "relator": "",
            "data": "02/08/2013", "data_iso": "2013-08-02",
            "url": "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2013/lei/l12850.htm",
            "resumo_ia": "",
        },
        {
            "fonte": "LEG", "label": "Planalto — Legislação",
            "titulo": "Lei nº 12.694/2012 — Julgamento colegiado em 1º grau",
            "resumo": (
                "Dispõe sobre o processo e julgamento colegiado em primeiro grau "
                "em crimes praticados por organizações criminosas."
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
        print(f"  [Gemini] {e}")
        return ""

def resumo_item(item):
    prompt = f"""Você é um assistente jurídico especializado em direito penal brasileiro.
Analise o seguinte item sobre organização criminosa e produza uma análise jurídica em 2-3 frases.
Destaque: relevância prática, impacto e contexto normativo (Lei 12.850/2013 quando aplicável).
Escreva em português, linguagem técnica mas acessível. Seja direto.

Fonte: {item['label']}
Título: {item['titulo']}
Resumo: {item['resumo'] or '(não disponível)'}
Data: {item['data']}

Análise (máx. 3 frases):"""
    return gemini_call(prompt, max_tokens=220)

def painel_do_dia(itens):
    if not itens:
        return ""
    linhas = []
    for i, it in enumerate(itens[:20], 1):
        linhas.append(
            f"{i}. [{it['fonte']}] {it['titulo']} — "
            f"{(it['resumo'] or '')[:180]} (Data: {it['data']})"
        )
    bloco = "\n".join(linhas)

    prompt = f"""Você é um assistente jurídico especializado em direito penal brasileiro.
Elabore um PAINEL EXECUTIVO DIÁRIO sobre monitoramento de "organização criminosa".
Fontes: STF, STJ, CNJ, Conjur, Jota, Dizer o Direito, Migalhas, Legislação Federal.
Data de hoje: {hoje_iso()}.

Itens coletados:
{bloco}

Use exatamente esta estrutura:

**PANORAMA DO DIA**
(2-3 frases sobre o volume e natureza das atualizações)

**DESTAQUES JURISPRUDENCIAIS**
(decisões de STF, STJ, CNJ — se houver; se não, escreva "Nenhuma decisão nova nas últimas 24h.")

**IMPRENSA JURÍDICA**
(pautas do Conjur, Jota, Migalhas, Dizer o Direito — se houver)

**LEGISLAÇÃO**
(normas relevantes — se houver)

**TENDÊNCIAS**
(1-2 frases sobre padrões observados)

Máximo 300 palavras. Seja objetivo e técnico."""
    return gemini_call(prompt, max_tokens=600)

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
    data_hoje = hoje_iso()   # DATA REAL do sistema

    print(f"\n{'═'*62}")
    print(f"  JusCrim Coletor v5 — {data_hoje}  (data real do sistema)")
    print(f"  Janela: últimas {JANELA_HORAS}h")
    print(f"  Gemini: {'✓ ativo' if GEMINI_KEY else '✗ não configurado'}")
    print(f"{'═'*62}\n")

    # 1. Coleta todos os feeds
    todos = []
    for fonte, label, url, fallback in FEEDS:
        print(f"[{fonte}] {label}")
        todos += coletar_feed(fonte, label, url, fallback)
        time.sleep(1.5)   # respeita os servidores

    # 2. Adiciona legislação base
    todos += legislacao_base()

    # 3. Remove duplicatas por URL
    vistos, unicos = set(), []
    for it in todos:
        chave = it.get("url") or it.get("titulo", "")
        if chave and chave not in vistos:
            vistos.add(chave)
            unicos.append(it)
    todos = unicos

    print(f"\n{'─'*62}")
    print(f"  Total após deduplicação: {len(todos)} item(s)")
    print(f"{'─'*62}\n")

    # 4. Gera resumos individuais com Gemini
    if GEMINI_KEY:
        print(f"[Gemini] Gerando {len(todos)} resumos individuais…")
        for i, it in enumerate(todos, 1):
            print(f"  [{i}/{len(todos)}] {it['titulo'][:65]}…")
            it["resumo_ia"] = resumo_item(it)
            time.sleep(1.2)   # rate-limit gratuito: 60 req/min
    else:
        print("[Gemini] Não configurado — resumos individuais omitidos.")

    # 5. Gera painel executivo do dia
    print("\n[Gemini] Gerando painel executivo do dia…")
    painel = painel_do_dia(todos) if GEMINI_KEY else (
        "⚠ Configure GEMINI_API_KEY nos GitHub Secrets para ativar o painel executivo com IA."
    )

    # 6. Monta entrada
    entrada = {
        "gerado_em":    datetime.now(timezone.utc).isoformat(),
        "data":         data_hoje,
        "janela_horas": JANELA_HORAS,
        "termo_busca":  TERMO,
        "total":        len(todos),
        "resumo_dia":   painel,
        "resultados":   todos,
    }

    # 7. Salva arquivo do dia
    arq = f"{DIR_DATA}/{data_hoje}.json"
    with open(arq, "w", encoding="utf-8") as f:
        json.dump(entrada, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Salvo: {arq}")

    # 8. Alias de compatibilidade
    with open(f"{DIR_DATA}/resultados.json", "w", encoding="utf-8") as f:
        json.dump(entrada, f, ensure_ascii=False, indent=2)

    # 9. Atualiza índice
    idx = load_indice()
    idx["datas"] = sorted(set(idx.get("datas", []) + [data_hoje]), reverse=True)
    idx["ultima_atualizacao"] = datetime.now(timezone.utc).isoformat()
    save_indice(idx)

    print(f"\n{'═'*62}")
    print(f"  ✅ {len(todos)} item(s) → {arq}")
    print(f"  📅 Histórico total: {len(idx['datas'])} dia(s)")
    print(f"{'═'*62}\n")

if __name__ == "__main__":
    main()
