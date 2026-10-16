# Copy this file to config.py and fill in your values.
# Environment variables override config.py (useful for Home Assistant).

EMAIL              = "your_email@example.sk"
SECRET             = "your_password"

SOLVER_KEY         = ""                         # 2captcha.com API key — leave empty to use cookie auth
METER_IN           = ""                         # delivery point ID for consumption (EIC code)
METER_OUT          = ""                         # delivery point ID for production (EIC code)

HDO_CODE           = 459                        # tariff switching code (HDO)

OUTPUT_TYPE        = "text"                     # text | short
DATA_DIR           = "data"  # directory for history.db and latest.json

WARN_BALANCE_BELOW = 1.0                        # warn when 2captcha balance drops below this ($)

# ---------------------------------------------------------------------------
# Electricity rates — add a new entry each year when ZSE publishes new prices.
# costs.py will error with a clear message if the year is missing.
# Source: https://www.zse.sk/dokumenty-a-tlaciva (Integrovaný cenník pre domácnosti)
# ---------------------------------------------------------------------------
RATES = {
    2026: {
        # Koncová cena odberu vrátane distribúcie a poplatkov (s DPH), sadzba DD5 / ZSD
        "consumption_eur_kwh": {
            "vt": 0.2297,
            "nt": 0.1750,
        },
        # Výkupné ceny Virtuálna batéria Flexi (s DPH)
        # Zdroj: https://www.zse.sk/dokumenty/cennik-pre-vykup-elektriny-v-dynamickom-produkte-virtualna-bateria.pdf
        "flexi_eur_kwh": {
            "weekday_00_10": 0.08211,   # Po-Pi 00:00 – 09:59
            "weekday_10_18": 0.04284,   # Po-Pi 10:00 – 17:59
            "weekday_18_24": 0.08092,   # Po-Pi 18:00 – 23:59
            "weekend":       0.04046,   # So-Ne + sviatky (celý deň)
        },
        # Fixné mesačné poplatky (s DPH)
        "fixed_eur_month": {
            "meter": 1.79,   # poplatok za odberné miesto
            "flexi": 3.00,   # mesačný poplatok Virtuálna batéria Flexi
        },
    },
    # 2027: { ... },   # doplniť po zverejnení nového cenníka ZSE
}
