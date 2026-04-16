# APEX OMEGA BOT v1.0

> **Football signal engine** — Dixon-Coles · Trust Matrix · Ghost Signals · Kelly Staking

---

## Architecture

```
apex_omega/
├── core/           config, database, logger
├── ingestion/      API-Football, FootyStats, The Odds API
├── models/         Dixon-Coles Poisson engine
├── trust/          7-factor Trust Matrix (0-100)
├── decisions/      Verdict engine + formatter
├── storage/        Ghost signal SQLite memory
├── scanner/        Central orchestrator
└── interfaces/     Telegram bot + CLI
```

## Commands

### Telegram
| Command | Description |
|---------|-------------|
| `/scan` | Scan 24h |
| `/scan_today` | Matchs du jour |
| `/scan_1h` | Urgence 1h |
| `/scan_3h` | Prochaines 3h |
| `/scan_6h` | Prochaines 6h |
| `/scan_12h` | Prochaines 12h |
| `/scan_48h` | Prochaines 48h |
| `/stats` | Ghost Memory + P&L |
| `/history` | 10 derniers signaux |
| `/mode` | Basculer Safe/Aggressive |
| `/bankroll [n]` | Définir bankroll |
| `/result HASH WIN` | Enregistrer résultat |

### Natural language
```
Arsenal Chelsea
ligue1 PSG Lyon
ucl Man City Real Madrid 15/07
```

### CLI
```bash
python main.py scan 24h
python main.py scan today
python main.py scan 3h
python main.py match Arsenal Chelsea
python main.py report
python main.py history --n 20
python main.py result abc123 WIN 12.5
```

## Deploy on Render

1. Push this repo to GitHub
2. Create a **Worker** service on Render
3. Set environment variables (see `.env.example`)
4. Add a **Persistent Disk** at `/var/data` (1 GB)
5. Build: `pip install -r requirements.txt`
6. Start: `python main.py`

## Engine Logic

```
Fixture → xG (FootyStats/proxy) → Trust Matrix → Dixon-Coles
       → Edge per market → Ghost Filter → Confidence /50
       → Kelly ¼ → Verdict (BET / SIGNAL / NO_BET / REJECT)
```

### Trust gates
- `< 50` → hard REJECT
- `< 70` → THIN_DATA route (N2/N3 blocked)
- DCS `< 0.58` → NO BET

### Edge thresholds (safe mode)
| Tier | Edge min |
|------|----------|
| P0 (UEFA) | 5.5% |
| N1 (Top5) | 5.0% |
| N2 | 4.0% |
| N3 | 3.0% |

### Ghost Signal Memory
Each signal pattern is hashed by `league × teams × market × edge_bucket`.
If reliability drops below **40%** over ≥5 samples → auto-REJECT.

---

*NO BET is the default. A signal is emitted only when data, model, and odds align.*

---

## 🔌 Sources de Données

### Architecture des APIs

```
API-Football (api-sports.io)     → Fixtures, Form, H2H
FootyStats                       → xG, BTTS%, O/U% (source premium)
odds-api.io                      → Cotes live (Bet365, Pinnacle, 265+ bookies)
```

### Problème fréquent : clé API incorrecte

Le bot utilise **odds-api.io** (pas `the-odds-api.com` qui est un service différent).

| Service | Base URL | Site pour clé |
|---------|----------|---------------|
| API-Football | `v3.football.api-sports.io` | dashboard.api-football.com |
| odds-api.io | `api.odds-api.io/v3` | odds-api.io/#pricing |
| FootyStats | `api.football-data-api.com` | footystats.org |

Variables Render requises :
```
API_FOOTBALL_KEY = ta_cle_api_sports_io
ODDS_API_KEY     = ta_cle_odds_api_io     ← obtenir sur odds-api.io
FOOTYSTATS_KEY   = ta_cle_footystats      ← optionnel (améliore xG)
BOT_TOKEN        = token_telegram
CHAT_ID          = ton_chat_id
```

---

## 🤖 MCP Server odds-api.io — Clarification

Le repo `odds-api-io/odds-api-mcp-server` est un serveur **Node.js** conçu pour
**Claude Desktop** et **Cursor** (assistants IA locaux). Il ne peut pas être intégré
dans un bot Python déployé sur Render.

Ce bot utilise l'**API REST directe** `api.odds-api.io/v3` — fonctionnellement
équivalente aux 22 outils MCP, sans dépendance Node.js.

### Utiliser le MCP avec Claude Desktop (séparément)

Si tu veux utiliser les outils MCP depuis Claude Desktop :
```json
{
  "mcpServers": {
    "odds-api": {
      "command": "npx",
      "args": ["odds-api-mcp-server"],
      "env": {
        "ODDS_API_KEY": "ta_cle"
      }
    }
  }
}
```
Fichier : `~/Library/Application Support/Claude/claude_desktop_config.json`

Ce MCP Claude Desktop et le bot Render sont **deux systèmes indépendants**.
