# Copy this file to config.py and fill in your values.
# Environment variables override config.py (useful for Home Assistant).

EMAIL              = "your_email@example.sk"
SECRET             = "your_password"

SOLVER_KEY         = ""                         # 2captcha.com API key — leave empty to use cookie auth
METER_IN           = ""                         # delivery point ID for consumption (EIC code)
METER_OUT          = ""                         # delivery point ID for production (EIC code)

OUTPUT_TYPE        = "text"                     # text | short
DATA_DIR           = "data"                     # directory for history.db and latest.json

WARN_BALANCE_BELOW = 1.0                        # warn when 2captcha balance drops below this ($)
