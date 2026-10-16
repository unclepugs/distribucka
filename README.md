# Electricity Data Collector

Stiahne dáta o spotrebe a výrobe elektrickej energie.
Portál neponúka verejné API — script ho obchádza priamymi HTTP volaniami s 2captcha na vyriešenie reCAPTCHA pri prihlásení.

**Čo získaš:**
- Denné súčty spotreby a výroby (FVE) za aktuálny mesiac
- 15-minútové intervalové dáta pre každý deň
- Odpočty meradla (mesačné stavy)
- Rozvrh prepínania VT/NT taríf pre tvoj HDO kód
- SQLite databáza na históriu + `latest.json` pre Home Assistant
- Výpočet finančných nákladov na elektrinu za deň alebo mesiac (vrátane Flexi výkupu)

---

## Požiadavky

- Python 3.8+
- API kľúč z [2captcha.com](https://2captcha.com) (kredit ~$3 vystačí na ~2 roky denného spúšťania)

---

## Štruktúra projektu

```
├── collector.py         # sťahuje spotrebu a výrobu
├── tariffs.py           # sťahuje rozvrh VT/NT prepínania
├── costs.py             # výpočet finančných nákladov za deň / mesiac
├── config.py            # tvoje nastavenia (v .gitignore, necommitovať!)
├── config.sample.py     # šablóna — skopíruj a vyplň
├── requirements.txt     # Python závislosti
├── .gitignore
└── data/                # vytvorí sa automaticky
    ├── history.db       # SQLite — celá história spotreby/výroby + tabuľka costs
    ├── latest.json      # aktuálny mesiac + 15-min detail (pre HA)
    ├── costs.json       # finančné náklady aktuálneho mesiaca (pre HA)
    └── tariffs.json     # VT/NT rozvrh pre nakonfigurovaný HDO kód
```

---

## Lokálne spustenie (Mac / Linux)

### 1. Inštalácia

```bash
pip3 install -r requirements.txt
```

### 2. Konfigurácia

```bash
cp config.sample.py config.py
```

Edituj `config.py`:

```python
EMAIL              = "tvoj@email.sk"
SECRET             = "heslo"
SOLVER_KEY         = "tvoj_api_kluc"       # z 2captcha.com → Dashboard → API key
METER_IN           = ""          # ID odberného miesta (spotreba)
METER_OUT          = ""          # ID odberného miesta (FVE výroba)
HDO_CODE           = 459        # kód prepínania VT/NT taríf
OUTPUT_TYPE        = "text"               # text | short
DATA_DIR           = "data"               # adresár pre history.db a latest.json
WARN_BALANCE_BELOW = 1.0                  # upozornenie pri nízkom kredite 2captcha ($)
```

> **Kde nájdeš delivery point IDs?**
> Spusti script prvýkrát bez nastavených IDs — vypíše `Delivery points: [...]`.
> Z výpisu register dát spoznáš ktoré je spotreba (`CINNY_ODBER`) a ktoré výroba (`CINNA_DODAV`).

### 3. Spustenie

```bash
# spotreba a výroba
python3 collector.py

# VT/NT rozvrh taríf
python3 tariffs.py
```

Príklady výstupov `collector.py`:

```bash
# Ľudsky čitateľný výpis (debug)
OUTPUT_TYPE=text python3 collector.py

# Len mesačné súčty ako JSON (spotreba / výroba / delta)
OUTPUT_TYPE=short python3 collector.py
```

**Inkrementálne sťahovanie:** Script si pri každom spustení pozrie `history.db` a stiahne len dáta, ktoré ešte nemá — od prvého dňa po poslednom `ALL_VALID` dennom zázname. Ak je DB aktuálna, skript skončí bez prihlásenia (bez spotreby 2captcha kreditu).

**Prvé spustenie (prázdna DB):** Script automaticky stiahne dáta od 1. januára aktuálneho roku — portál historické dáta podporuje.

### Výpočet nákladov (`costs.py`)

Vypočíta finančné náklady na elektrinu z dát v `history.db`. Vyžaduje `tariffs.json` (spusti `tariffs.py`) a `RATES` v `config.py`.

```bash
# Včerajší deň (default)
python3 costs.py

# Konkrétny deň
python3 costs.py --date 2026-10-14

# Celý mesiac
python3 costs.py --month 2026-10
```

**Cenník (RATES v `config.py`):** Každý rok doplň nový záznam `RATES[rok]` podľa aktuálneho [Integrovaného cenníka ZSE](https://www.zse.sk/dokumenty-a-tlaciva). Ak cenník pre daný rok chýba, script skončí s jasnou chybovou hláškou.

### 4. Automatické spúšťanie (cron)

Raz denne o 6:00:

```bash
crontab -e
```

```
0 6 * * * cd /cesta/k/projektu && python3 collector.py >> /tmp/collector.log 2>&1
0 5 * * * cd /cesta/k/projektu && python3 tariffs.py >> /tmp/tariffs.log 2>&1
```

---

## Dátový výstup

### `data/latest.json`

Aktualizuje sa pri každom spustení. Obsahuje:

```json
{
  "fetched_at": "2026-10-15T06:00:00",
  "month": "2026-10",
  "consumption_kwh_month": 73.09,
  "production_kwh_month": 355.34,
  "delta_kwh_month": -282.24,
  "daily": [
    { "ts": "2026-10-01", "value_kwh": 8.22, "type": "consumption", "..." : "..." },
    { "ts": "2026-10-01", "value_kwh": 31.75, "type": "production", "..." : "..." }
  ],
  "last_day": "2026-10-14",
  "last_day_intervals": [
    { "ts": "2026-10-14T00:00:00", "value_kwh": 0.071, "type": "consumption", "..." : "..." },
    { "ts": "2026-10-14T08:00:00", "value_kwh": 0.8,   "type": "production",  "..." : "..." }
  ]
}
```

`delta_kwh_month < 0` znamená, že FVE produkovala viac ako dom spotreboval.

### `data/tariffs.json`

Aktualizuje sa spustením `tariffs.py`. Obsahuje NT intervaly (zo zdroja) a dopočítané VT intervaly:

```json
{
  "hdo_code": 459,
  "nt_intervals": [
    { "t_type": "nt", "t_from": "23:45", "t_to": "6:15", "weekday": true, "weekend": true, "..." : "..." }
  ],
  "vt_intervals": [
    { "t_type": "vt", "t_from": "06:15", "t_to": "07:15" }
  ],
  "all_intervals": [...]
}
```

### `data/history.db`

SQLite tabuľka `readings`:

| stĺpec | popis |
|---|---|
| `ts` | timestamp (`2026-10-14` pre denné, `2026-10-14T08:00:00` pre 15-min) |
| `delivery_point_id` | ID odberného miesta |
| `type` | `consumption` alebo `production` |
| `value_kwh` | energia v kWh |
| `state` | `ALL_VALID` / `VM` |
| `interval_minutes` | `1440` (deň) alebo `15` (štvrťhodina) |
| `fetched_at` | kedy sa záznam stiahol |

Príklad SQL dotazu — denná spotreba za posledný mesiac:

```sql
SELECT ts, value_kwh
FROM readings
WHERE type = 'consumption' AND interval_minutes = 1440
ORDER BY ts DESC
LIMIT 31;
```

---

## Home Assistant integrácia

### Príprava

Script spúšťaj na tom istom stroji kde beží HA (alebo na mieste odkiaľ HA vie čítať súbory).
`latest.json` musí byť dostupný pre HA, napr. v `/config/collector/latest.json`.

V `config.py` nastav:

```python
DATA_DIR = "/config/collector"
```

### Cron v HA (SSH addon)

```bash
# v termináli HA (SSH & Web Terminal addon)
pip3 install requests 2captcha-python

crontab -e
# pridaj:
0 6 * * * python3 /config/collector/collector.py
```

### File sensor v `configuration.yaml`

```yaml
sensor:
  - platform: file
    name: Collector Latest
    file_path: /config/collector/latest.json
    value_template: "{{ value_json.fetched_at }}"

template:
  - sensor:
      - name: "Spotreba mesiac"
        unit_of_measurement: kWh
        state_class: total
        device_class: energy
        state: "{{ state_attr('sensor.collector_latest', 'consumption_kwh_month') }}"

      - name: "Výroba mesiac"
        unit_of_measurement: kWh
        state_class: total
        device_class: energy
        state: "{{ state_attr('sensor.collector_latest', 'production_kwh_month') }}"

      - name: "Delta mesiac"
        unit_of_measurement: kWh
        state: "{{ state_attr('sensor.collector_latest', 'delta_kwh_month') }}"
```

> **Poznámka:** File sensor načíta JSON ako atribúty — pre komplexnejšie spracovanie
> (napr. 15-min grafy) použi `command_line` sensor alebo custom integration.

### Upozornenie na nízky kredit 2captcha

Script vypíše `WARNING: 2captcha balance is low ($X.XX)` na stdout.
V HA to môžeš zachytiť cez log sensor alebo notifikáciu z cron mailu.

---

## Poznámky

- Script sa prihlasuje cez 2captcha **len keď je čo sťahovať** — ak je DB aktuálna, captcha sa nerieši
- Sťahuje len **chýbajúce dáta** od posledného platného záznamu; pri prvom spustení stiahne celý aktuálny mesiac
- Portál vracia dáta za **aktuálny mesiac** — história sa buduje postupne v `history.db`
- 15-minútové dáta sú dostupné s oneskorením (predchádzajúci deň)
- `measuredValue` z API je v **kW** (okamžitý výkon) — script ho konvertuje na kWh (`× 0.25`)
