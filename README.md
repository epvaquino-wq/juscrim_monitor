# JusCrim Monitor 🏛️

Site que coleta automaticamente, todo dia, precedentes e normas sobre **organização criminosa** dos tribunais superiores e do TJPE.

---

## O que está incluído

| Arquivo | Para que serve |
|---|---|
| `index.html` | O site (página principal) |
| `coletor.py` | Script Python que busca os dados |
| `data/resultados.json` | Dados coletados (atualizado automaticamente) |
| `.github/workflows/coleta.yml` | Agendamento automático diário |

---

## Como publicar (passo a passo, sem programação)

### 1. Crie uma conta no GitHub
Acesse [github.com](https://github.com) e crie uma conta gratuita.

### 2. Crie um novo repositório
- Clique em **"New"** (botão verde)
- Nome sugerido: `juscrim-monitor`
- Deixe **público**
- Clique em **"Create repository"**

### 3. Faça upload dos arquivos
- Na página do repositório, clique em **"uploading an existing file"**
- Arraste todos os arquivos desta pasta:
  - `index.html`
  - `coletor.py`
  - Pasta `data/` (com `resultados.json`)
  - Pasta `.github/` (com `workflows/coleta.yml`)
- Clique em **"Commit changes"**

### 4. Ative o GitHub Pages (site gratuito)
- Vá em **Settings** (aba no menu do repositório)
- Role até **"Pages"** no menu lateral
- Em "Source", selecione **"Deploy from a branch"**
- Branch: **main** / Pasta: **/ (root)**
- Clique em **Save**
- Aguarde 2-3 minutos → seu site estará em:
  `https://SEU-USUARIO.github.io/juscrim-monitor`

### 5. Ative as Actions (automação diária)
- Vá em **Actions** (aba no menu do repositório)
- Clique em **"I understand my workflows, go ahead and enable them"**
- Pronto! O script rodará todo dia às 07:00 (Brasília) automaticamente.

---

## Como testar manualmente
- Vá em **Actions** → **"Coleta Diária — JusCrim"** → **"Run workflow"**
- Aguarde ~1 minuto → os dados serão atualizados no site.

---

## Personalização

### Mudar o horário de atualização
Edite `.github/workflows/coleta.yml`, linha com `cron`:
```
# Formato: minuto hora dia mês dia-semana (UTC)
# 10:00 UTC = 07:00 Brasília (horário de verão: 08:00 Brasília)
- cron: '0 10 * * *'
```

### Mudar o termo de busca
Edite `coletor.py`, linha:
```python
TERMO_BUSCA = "organização criminosa"
```

---

## Fontes utilizadas
- **STF** — [jurisprudencia.stf.jus.br](https://jurisprudencia.stf.jus.br)
- **STJ** — [scon.stj.jus.br](https://scon.stj.jus.br)
- **TJPE** — [tjpe.jus.br](https://www.tjpe.jus.br)
- **LexML / Planalto** — [lexml.gov.br](https://www.lexml.gov.br)

Todas são fontes públicas e oficiais, sem necessidade de login.
