# 🤖 APEX OMEGA BOT

**Moteur de paris sportifs automatisé — Dixon-Coles + Ghost Signal Memory + Trust Matrix**

---

## Architecture

```
apex_omega/
├── core/           → Config, DB, Logger
├── ingestion/      → API-Football, FootyStats, Odds API
├── models/         → Dixon-Coles (Poisson bivarié + correction τ)
├── trust/          → Trust Matrix 7 facteurs (0-100)
├── decisions/      → Verdict Engine + Rationale Builder
├── storage/        → Ghost Signals, Signal Log (SQLite)
├── scanner/        → Scan Engine (orchestrateur central)
├── interfaces/     → Telegram Bot + CLI
├── risk/           → Bankroll, Exposure
└── backtest/       → Walk-forward backtester
```

---

## Commandes

### Telegram
```
/start          → Menu principal
/scan           → Scan 24h
/scan today     → Matchs du jour
/scan 1h        → Urgence (prochaine heure)
/scan 6h        → 6 heures
/stats          → Statistiques & Ghost Memory
/mode           → Basculer Safe ↔ Aggressive
/help           → Aide

Message libre:  "Arsenal Chelsea"
                "EPL Arsenal Chelsea 26/04"
                "Champions League Real Madrid Bayern"
```

### CLI
```bash
python main.py scan             # 24h
python main.py scan today       # Aujourd'hui
python main.py scan 1h          # 1 heure
python main.py scan 6h --mode aggressive
python main.py analyse "Arsenal" "Chelsea" --league 39
python main.py report           # Ghost Signal Memory
```

---

## Déploiement Render

1. **Fork** ce repo
2. **New Worker Service** sur Render → connecter le repo
3. Ajouter le **Persistent Disk** (`/var/data`, 1 GB)
4. Configurer les **Environment Variables** (voir `.env.example`)
5. Build: `pip install -r requirements.txt`
6. Start: `python main.py`

---

## Variables d'environnement

```env
BOT_TOKEN=...
CHAT_ID=...
API_FOOTBALL_KEY=...
FOOTYSTATS_KEY=...
ODDS_API_KEY=...
ODDS_API_BOOKMAKERS=Bet365,Pinnacle
DB_PATH=/var/data/apex_signals.db
DATA_DIR=/var/data
BANKROLL=1000
DEFAULT_MODE=safe
```

---

## Modèle APEX

| Composant | Description |
|-----------|-------------|
| **Dixon-Coles** | Poisson bivarié + correction τ sur les scores bas |
| **Trust Matrix** | 7 facteurs → score 0-100, gate < 50 = REJECT |
| **DCS** | Data Confidence Score — gate < 0.58 = NO BET |
| **Ghost Filter** | Mémoire des signaux perdants → block si reliability < 0.4 |
| **Kelly 25%** | Mise fractionnée, plafond 5% bankroll |
| **Edge min** | P0: 4% | N1: 4% | N2: 3% | N3: 2% |

---

## Signaux

| Code | Description |
|------|-------------|
| 🚀 **BET** | Edge ✅, cote ✅, confiance ✅, Ghost ✅ |
| 📡 **SIGNAL** | Signal pur (cote hors plage BET ou mode signal) |
| ⛔ **NO_BET** | Critères non remplis |
| 🚫 **REJECT** | Trust/DCS insuffisant |
| 👻 **GHOST** | Bloqué par mémoire des pertes |

---

*APEX OMEGA — La qualité prime sur la quantité.*
