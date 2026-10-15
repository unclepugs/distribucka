#!/usr/bin/env python3
"""
Electricity data collector — fetches consumption/production data.
"""

import json
import os
import sys
import sqlite3
import calendar
from datetime import datetime, date
from pathlib import Path

import requests

########### CONFIGURATION ######################################################
# Priority: environment variable > config.py > default
# Copy config.sample.py to config.py and fill in your values.
def _load_cfg():
    try:
        import config as _c
        return {k: v for k, v in vars(_c).items() if not k.startswith("_")}
    except ImportError:
        return {}

_cfg = _load_cfg()

def _conf(key, env_key, default=""):
    return os.getenv(env_key) or _cfg.get(key) or default

EMAIL              = _conf("EMAIL",              "APP_EMAIL")
SECRET             = _conf("SECRET",             "APP_SECRET")
SOLVER_KEY         = _conf("SOLVER_KEY",         "APIKEY_2CAPTCHA")
RECAPTCHA_SITE_KEY = "6LfdaLUZAAAAAHCVziF1iDFvmCxAjlIP1xF6pjHg"
METER_IN           = _conf("METER_IN",           "APP_METER_IN")
METER_OUT          = _conf("METER_OUT",          "APP_METER_OUT")
OUTPUT_TYPE        = _conf("OUTPUT_TYPE",        "APP_OUTPUT",     "text")   # text | short
DATA_DIR           = _conf("DATA_DIR",           "APP_DATA_DIR",   "data")
WARN_BALANCE_BELOW = float(_cfg.get("WARN_BALANCE_BELOW", os.getenv("APP_WARN_BALANCE", 1.0)))
################################################################################

SOURCE = "KOC"

_today    = date.today()
FROM_DATE = f"{_today.year}-{_today.month:02d}-01"
TO_DATE   = f"{_today.year}-{_today.month:02d}-{calendar.monthrange(_today.year, _today.month)[1]}"

URLS = {
    "login_site":   "https://www.diportal.sk/portal/#/verejne/prihlasenie",
    "news":         "https://www.diportal.sk/portal/api/public/texts/getNewsAndAnnouncements",
    "login":        "https://www.diportal.sk/portal/api/security/login",
    "get_user":     "https://www.diportal.sk/portal/api/commons/getUser",
    "profile_data": "https://www.diportal.sk/portal/api/interval-data/getProfileData",
    "delivery_pts": "https://www.diportal.sk/portal/api/delivery-points-list/loadDeliveryPoints",
    "devices":      "https://www.diportal.sk/portal/api/register-data/getDevicesForDeliveryPoint",
    "register":     "https://www.diportal.sk/portal/api/register-data/getData",
}

BASE_HEADERS = {
    "Accept":             "application/json, text/plain, */*",
    "Accept-Language":    "en-GB,en-US;q=0.9,en;q=0.8",
    "Cache-Control":      "no-cache",
    "Connection":         "keep-alive",
    "Host":               "www.diportal.sk",
    "Origin":             "https://www.diportal.sk",
    "Pragma":             "no-cache",
    "Referer":            "https://www.diportal.sk/portal/",
    "Sec-Fetch-Dest":     "empty",
    "Sec-Fetch-Mode":     "cors",
    "Sec-Fetch-Site":     "same-origin",
    "User-Agent":         "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "content-type":       "application/json",
    "sec-ch-ua":          '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
    "sec-ch-ua-mobile":   "?0",
    "sec-ch-ua-platform": '"macOS"',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg):
    if OUTPUT_TYPE == "text":
        print(msg)


def _check_body(resp):
    if "Chybov" in resp.text or "Request Rejected" in resp.text:
        print("Portal error — check credentials or 2captcha API key.")
        sys.exit(1)


def _get(session, url, xcsrf=None):
    hdrs = {**BASE_HEADERS, **({"X-CSRF": xcsrf} if xcsrf else {})}
    resp = session.get(url, headers=hdrs, verify=True)
    _check_body(resp)
    return resp


def _post(session, url, payload, xcsrf):
    hdrs = {**BASE_HEADERS, "X-CSRF": xcsrf}
    resp = session.post(url, json=payload, headers=hdrs, verify=True)
    _check_body(resp)
    return resp


# ---------------------------------------------------------------------------
# Session / auth
# ---------------------------------------------------------------------------

def create_session():
    return requests.Session()


def solve_captcha():
    from twocaptcha import TwoCaptcha
    solver = TwoCaptcha(SOLVER_KEY)
    try:
        result = solver.recaptcha(sitekey=RECAPTCHA_SITE_KEY, url=URLS["login_site"])
        code   = result["code"]
        _check_2captcha_balance(solver)
        return code
    except Exception as e:
        sys.exit(f"Captcha solving failed: {e}")


def _check_2captcha_balance(solver):
    try:
        balance = float(solver.balance())
        log(f"2captcha balance: ${balance:.2f}")
        if balance < WARN_BALANCE_BELOW:
            print(f"WARNING: 2captcha balance is low (${balance:.2f}). Recharge at 2captcha.com.")
    except Exception:
        pass


def login(session, captcha_code):
    _get(session, URLS["news"])
    payload = {
        "userId":                     EMAIL,
        "password":                   SECRET,
        "invisibleRecaptchaResponse": captcha_code,
    }
    resp = session.post(URLS["login"], json=payload, headers=BASE_HEADERS, verify=True)
    csrf = resp.headers.get("x-csrf")
    log(f"CSRF after login: {csrf}")
    return csrf


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def get_user(session, xcsrf):
    data = _get(session, URLS["get_user"], xcsrf).json()["data"]
    bp   = data["businessPartnerAssignments"][0]
    user = {
        "lastName":          data["lastName"],
        "firstName":         data["firstName"],
        "email":             data["email"],
        "city":              data["city"],
        "businessPartnerId": bp["businessPartnerId"],
        "businessRoleId":    bp["businessRoleIds"][0],
    }
    log(f"User: {user['firstName']} {user['lastName']} ({user['email']})")
    return user


def get_delivery_points(session, xcsrf, user):
    payload = {
        "filter": {"onlyActive": True, "smartMeterEnabled": None, "dateFrom": "", "dateTo": ""},
        "businessPartnerId": user["businessPartnerId"],
        "businessRoleId":    user["businessRoleId"],
    }
    data = _post(session, URLS["delivery_pts"], payload, xcsrf).json()["data"]
    ids  = [p["deliveryPointId"] for p in data]
    log(f"Delivery points: {ids}")
    return ids


def get_devices(session, xcsrf, user, dp_id):
    payload = {
        "filter": {"dateTo": TO_DATE, "dateFrom": "2021-01-01", "deliveryPointId": dp_id},
        "businessPartnerId": user["businessPartnerId"],
        "businessRoleId":    user["businessRoleId"],
    }
    device = _post(session, URLS["devices"], payload, xcsrf).json()["data"][0]
    log(f"  Device: {device['serialNumber']} / {device['equipmentNumber']}")
    return {
        "serialNumber":    device["serialNumber"],
        "equipmentNumber": device["equipmentNumber"],
    }


def get_interval_data(session, xcsrf, user, dp_id):
    payload = {
        "filter": {
            "deliveryPointId":  dp_id,
            "from":             FROM_DATE,
            "to":               TO_DATE,
            "loadProfileRoles": True,
        },
        "businessPartnerId": user["businessPartnerId"],
        "businessRoleId":    user["businessRoleId"],
        "source":            SOURCE,
    }
    profile = _post(session, URLS["profile_data"], payload, xcsrf).json()["data"]["profileData"]

    daily_records    = []   # one record per day (kWh total)
    interval_records = []   # one record per 15-min slot (kWh = kW × 0.25h)

    for day in profile.get("dailyIntervalData", []):
        daily_records.append({
            "ts":               day["date"],
            "value_kwh":        day["consumption"],
            "state":            day["dailyState"],
            "interval_minutes": 1440,
        })
        if OUTPUT_TYPE == "text" and day["dailyState"] == "ALL_VALID":
            log(f"  {day['date']} — {day['consumption']} kWh")

        for v in day.get("values", []):
            ts = f"{v['dateMeasuredAt']}T{v['measuredAt']}"
            interval_records.append({
                "ts":               ts,
                "value_kwh":        round(v["measuredValue"] * 0.25, 4),
                "state":            v["state"],
                "interval_minutes": 15,
            })

    log(f"  → {len(daily_records)} days, {len(interval_records)} × 15-min records")
    return daily_records, interval_records


def get_register_data(session, xcsrf, user, dp_id, device):
    payload = {
        "filter": {
            "deliveryPointId":       dp_id,
            "dateFrom":              "2022-12-31",
            "dateTo":                TO_DATE,
            "deviceSerialNumber":    device["serialNumber"],
            "deviceEquipmentNumber": device["equipmentNumber"],
        },
        "businessPartnerId": user["businessPartnerId"],
        "businessRoleId":    user["businessRoleId"],
    }
    entries = _post(session, URLS["register"], payload, xcsrf).json()["data"]
    log("\nRegister data:")
    for e in entries:
        if e["deviceSerialNumber"] == device["serialNumber"]:
            log(f"  {e['settlementDate']} — {e['counterId']} {e['settlementState']} kWh")
    return entries


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def init_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            ts                TEXT NOT NULL,
            delivery_point_id TEXT NOT NULL,
            type              TEXT NOT NULL,
            value_kwh         REAL,
            state             TEXT,
            interval_minutes  INTEGER,
            fetched_at        TEXT NOT NULL,
            PRIMARY KEY (ts, delivery_point_id, type)
        )
    """)
    conn.commit()
    return conn


def save_to_db(conn, dp_id, dp_type, records, fetched_at):
    conn.executemany(
        """INSERT OR REPLACE INTO readings
           (ts, delivery_point_id, type, value_kwh, state, interval_minutes, fetched_at)
           VALUES (:ts, :dp_id, :type, :value_kwh, :state, :interval_minutes, :fetched_at)""",
        [{
            "ts":               r["ts"],
            "dp_id":            dp_id,
            "type":             dp_type,
            "value_kwh":        r["value_kwh"],
            "state":            r["state"],
            "interval_minutes": r["interval_minutes"],
            "fetched_at":       fetched_at,
        } for r in records]
    )
    conn.commit()
    log(f"  Saved {len(records)} records to DB ({dp_type})")


def write_latest_json(output, daily_records, interval_records, json_path, fetched_at):
    """Writes a JSON file that Home Assistant can read directly."""
    # find the latest day that has 15-min data
    last_day = sorted({r["ts"][:10] for r in interval_records})[-1] if interval_records else None
    last_day_intervals = [r for r in interval_records if r["ts"].startswith(last_day)] if last_day else []

    payload = {
        "fetched_at":            fetched_at,
        "month":                 f"{_today.year}-{_today.month:02d}",
        "consumption_kwh_month": output.get("consumption"),
        "production_kwh_month":  output.get("production"),
        "delta_kwh_month":       output.get("delta"),
        "daily":                 daily_records,
        "last_day":              last_day,
        "last_day_intervals":    last_day_intervals,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    log(f"latest.json written → {json_path} ({len(daily_records)} days, {len(last_day_intervals)} × 15-min for {last_day})")


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def fetch_all(session, xcsrf):
    user   = get_user(session, xcsrf)
    dp_ids = get_delivery_points(session, xcsrf, user)

    Path(DATA_DIR).mkdir(exist_ok=True)
    conn       = init_db(os.path.join(DATA_DIR, "history.db"))
    fetched_at = datetime.now().isoformat(timespec="seconds")
    output     = {}
    all_daily     = []
    all_intervals = []

    for dp_id in dp_ids:
        dp_type = (
            "consumption" if dp_id == METER_IN  else
            "production"  if dp_id == METER_OUT else
            "unknown"
        )
        log(f"\n--- {dp_id} ({dp_type}) ---")

        daily, intervals = get_interval_data(session, xcsrf, user, dp_id)
        save_to_db(conn, dp_id, dp_type, daily + intervals, fetched_at)

        valid_total = sum(r["value_kwh"] for r in daily if r["state"] == "ALL_VALID")
        if dp_id == METER_IN:
            output["consumption"] = valid_total
        if dp_id == METER_OUT:
            output["production"] = valid_total

        all_daily.extend([{**r, "delivery_point_id": dp_id, "type": dp_type} for r in daily])
        all_intervals.extend([{**r, "delivery_point_id": dp_id, "type": dp_type} for r in intervals])

        device = get_devices(session, xcsrf, user, dp_id)
        get_register_data(session, xcsrf, user, dp_id, device)

    conn.close()

    if "production" in output and "consumption" in output:
        output["delta"] = output["consumption"] - output["production"]

    write_latest_json(output, all_daily, all_intervals, os.path.join(DATA_DIR, "latest.json"), fetched_at)
    return output


def main():
    if not EMAIL or not SECRET:
        print("EMAIL and SECRET must be set in config.py.")
        sys.exit(1)
    if not SOLVER_KEY:
        print("SOLVER_KEY must be set in config.py.")
        sys.exit(1)

    session = create_session()
    log("Solving captcha via 2captcha...")
    xcsrf = login(session, solve_captcha())
    if not xcsrf:
        print("Login failed — check credentials or 2captcha API key.")
        sys.exit(1)

    output = fetch_all(session, xcsrf)

    if OUTPUT_TYPE == "short":
        print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
