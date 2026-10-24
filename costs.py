#!/usr/bin/env python3
"""
Calculates daily/monthly electricity costs from history.db.
Uses 15-min interval data + VT/NT schedule (tariffs.json) + rates (config.py RATES).

Usage:
  python3 costs.py                    # yesterday
  python3 costs.py --date 2026-10-14  # specific day
  python3 costs.py --month 2026-10    # full month
"""

import argparse
import json
import os
import sqlite3
from calendar import monthrange
from datetime import date, timedelta


def _load_cfg():
    try:
        import config as _c
        return {k: v for k, v in vars(_c).items() if not k.startswith("_")}
    except ImportError:
        return {}

_cfg     = _load_cfg()
DATA_DIR = _cfg.get("DATA_DIR", "data")
RATES    = _cfg.get("RATES", {})


# ---------------------------------------------------------------------------
# Slovak public holidays (needed for Flexi buy-back rate)
# ---------------------------------------------------------------------------

def _easter(year):
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day   = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def sk_holidays(year):
    easter = _easter(year)
    return {
        date(year, 1,  1),
        date(year, 1,  6),
        easter - timedelta(days=2),   # Veľký piatok
        easter + timedelta(days=1),   # Veľkonočný pondelok
        date(year, 5,  1),
        date(year, 5,  8),
        date(year, 7,  5),
        date(year, 8, 29),
        date(year, 9,  1),
        date(year, 9, 15),
        date(year, 11, 1),
        date(year, 11,17),
        date(year, 12,24),
        date(year, 12,25),
        date(year, 12,26),
    }


# ---------------------------------------------------------------------------
# Tariff helpers
# ---------------------------------------------------------------------------

def load_tariffs():
    path = os.path.join(DATA_DIR, "tariffs.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"tariffs.json not found — run tariffs.py first.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _t2m(t):
    h, m = map(int, t.split(":"))
    return h * 60 + m


def _build_nt_ranges(tariffs):
    nt_weekday, nt_weekend = [], []
    for iv in tariffs["nt_intervals"]:
        s, e = _t2m(iv["t_from"]), _t2m(iv["t_to"])
        if iv.get("weekday", True):
            nt_weekday.append((s, e))
        if iv.get("weekend", True):
            nt_weekend.append((s, e))
    return nt_weekday, nt_weekend


def _in_range(m, s, e):
    if s < e:
        return s <= m < e
    return m >= s or m < e   # wraps midnight


def is_nt(slot_hhmm, is_weho, nt_weekday, nt_weekend):
    m = _t2m(slot_hhmm)
    return any(_in_range(m, s, e) for s, e in (nt_weekend if is_weho else nt_weekday))


# ---------------------------------------------------------------------------
# Rate helpers
# ---------------------------------------------------------------------------

def get_rates(year):
    if year not in RATES:
        available = sorted(RATES.keys())
        raise KeyError(
            f"Chýba cenník pre rok {year}. "
            f"Dostupné roky: {available or 'žiadne'}. "
            f"Doplň RATES[{year}] do config.py podľa aktuálneho cenníka ZSE."
        )
    return RATES[year]


def flexi_rate(slot_hhmm, is_weho, rates):
    if is_weho:
        return rates["flexi_eur_kwh"]["weekend"]
    h = int(slot_hhmm.split(":")[0])
    if h < 10:
        return rates["flexi_eur_kwh"]["weekday_00_10"]
    if h < 18:
        return rates["flexi_eur_kwh"]["weekday_10_18"]
    return rates["flexi_eur_kwh"]["weekday_18_24"]


# ---------------------------------------------------------------------------
# DB — readings (read) + costs (read/write)
# ---------------------------------------------------------------------------

def open_db():
    db_path = os.path.join(DATA_DIR, "history.db")
    if not os.path.exists(db_path):
        raise FileNotFoundError("history.db not found — run collector.py first.")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS costs (
            date             TEXT PRIMARY KEY,
            consumption_vt   REAL,
            consumption_nt   REAL,
            consumption_total REAL,
            production_vt    REAL,
            production_nt    REAL,
            production_total REAL,
            cost_consumption REAL,
            credit_flexi     REAL,
            net_variable     REAL,
            rates_year       INTEGER,
            computed_at      TEXT
        )
    """)
    conn.commit()
    return conn


def load_intervals(conn, day_str):
    return conn.execute(
        """SELECT ts, type, value_kwh FROM readings
           WHERE interval_minutes = 15 AND DATE(ts) = ?
           ORDER BY ts""",
        (day_str,),
    ).fetchall()


def save_cost(conn, r, rates_year, computed_at):
    conn.execute(
        """INSERT OR REPLACE INTO costs
           (date, consumption_vt, consumption_nt, consumption_total,
            production_vt, production_nt, production_total,
            cost_consumption, credit_flexi, net_variable,
            rates_year, computed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            r["date"],
            r["consumption_vt"], r["consumption_nt"], r["consumption_total"],
            r["production_vt"],  r["production_nt"],  r["production_total"],
            r["cost_consumption"], r["credit_flexi"], r["net_variable"],
            rates_year, computed_at,
        ),
    )
    conn.commit()


def _month_summaries(conn):
    rows = conn.execute(
        """SELECT strftime('%Y-%m', date) AS month,
                  COUNT(*),
                  SUM(consumption_vt), SUM(consumption_nt), SUM(consumption_total),
                  SUM(production_total),
                  SUM(cost_consumption), SUM(credit_flexi),
                  SUM(net_variable)
           FROM costs
           GROUP BY month
           ORDER BY month"""
    ).fetchall()

    result = []
    for month_str, days, cons_vt, cons_nt, cons, prod, cost, cred, net_var in rows:
        year = int(month_str[:4])
        try:
            rates = get_rates(year)
            fixed = sum(rates["fixed_eur_month"].values())
            total = round(net_var + fixed, 4)
            avg   = round(total / cons, 4) if cons else None
        except KeyError:
            fixed = total = avg = None
        result.append({
            "month":              month_str,
            "days_with_data":     days,
            "consumption_vt_kwh": round(cons_vt, 4),
            "consumption_nt_kwh": round(cons_nt, 4),
            "consumption_kwh":    round(cons, 4),
            "production_kwh":     round(prod, 4),
            "cost_eur":           round(cost, 4),
            "credit_eur":         round(cred, 4),
            "net_variable_eur":   round(net_var, 4),
            "fixed_eur":          round(fixed, 2) if fixed is not None else None,
            "total_eur":          total,
            "avg_price_eur_kwh":  avg,
        })
    return result


def write_costs_json(conn, computed_at):
    today = date.today()
    month_start = f"{today.year}-{today.month:02d}-01"

    rows = conn.execute(
        """SELECT date, consumption_total, production_total,
                  cost_consumption, credit_flexi, net_variable,
                  consumption_vt, consumption_nt
           FROM costs WHERE date >= ? ORDER BY date""",
        (month_start,),
    ).fetchall()

    if not rows:
        return

    year   = today.year
    rates  = get_rates(year)
    fixed  = sum(rates["fixed_eur_month"].values())

    cons  = sum(r[1] for r in rows)
    prod  = sum(r[2] for r in rows)
    cost  = sum(r[3] for r in rows)
    cred  = sum(r[4] for r in rows)
    net   = cost - cred + fixed

    payload = {
        "computed_at":        computed_at,
        "month":              f"{today.year}-{today.month:02d}",
        "days_with_data":     len(rows),
        "consumption_kwh":    round(cons, 4),
        "production_kwh":     round(prod, 4),
        "cost_eur":           round(cost, 4),
        "credit_eur":         round(cred, 4),
        "net_variable_eur":   round(cost - cred, 4),
        "fixed_eur":          round(fixed, 2),
        "total_eur":          round(net, 4),
        "avg_price_eur_kwh":  round(net / cons, 4) if cons else None,
        "daily": [
            {
                "date":              r[0],
                "consumption_vt":    r[6],
                "consumption_nt":    r[7],
                "consumption_total": r[1],
                "production_total":  r[2],
                "cost_consumption":  r[3],
                "credit_flexi":      r[4],
                "net_variable":      r[5],
            }
            for r in rows
        ],
        "months": _month_summaries(conn),
    }

    path = os.path.join(DATA_DIR, "costs.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"costs.json written → {path}")


# ---------------------------------------------------------------------------
# Calculation
# ---------------------------------------------------------------------------

def calc_day(conn, day: date, tariffs, holidays_set):
    rates   = get_rates(day.year)
    is_weho = day.weekday() >= 5 or day in holidays_set
    nt_weekday, nt_weekend = _build_nt_ranges(tariffs)

    rows = load_intervals(conn, day.isoformat())
    if not rows:
        return None

    cons = {"vt": 0.0, "nt": 0.0}
    prod = {"vt": 0.0, "nt": 0.0}
    cost_cons  = 0.0
    cred_flexi = 0.0

    for ts, type_, kwh in rows:
        hhmm   = ts[11:16]
        tariff = "nt" if is_nt(hhmm, is_weho, nt_weekday, nt_weekend) else "vt"

        if type_ == "consumption":
            cons[tariff] += kwh
            cost_cons    += kwh * rates["consumption_eur_kwh"][tariff]
        elif type_ == "production":
            prod[tariff] += kwh
            cred_flexi   += kwh * flexi_rate(hhmm, is_weho, rates)

    return {
        "date":              day.isoformat(),
        "is_weho":           is_weho,
        "consumption_vt":    round(cons["vt"], 4),
        "consumption_nt":    round(cons["nt"], 4),
        "consumption_total": round(cons["vt"] + cons["nt"], 4),
        "production_vt":     round(prod["vt"], 4),
        "production_nt":     round(prod["nt"], 4),
        "production_total":  round(prod["vt"] + prod["nt"], 4),
        "cost_consumption":  round(cost_cons, 4),
        "credit_flexi":      round(cred_flexi, 4),
        "net_variable":      round(cost_cons - cred_flexi, 4),
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _sep(char="-", width=54):
    print(char * width)


def print_day(r, rates):
    fixed_day = sum(rates["fixed_eur_month"].values()) / 30
    label = "  [víkend/sviatok]" if r["is_weho"] else ""
    print()
    _sep("=")
    print(f"  {r['date']}{label}")
    _sep("=")
    print(f"  Odber   VT {r['consumption_vt']:>7.3f} kWh   NT {r['consumption_nt']:>7.3f} kWh   Σ {r['consumption_total']:>7.3f} kWh")
    print(f"  Výroba  VT {r['production_vt']:>7.3f} kWh   NT {r['production_nt']:>7.3f} kWh   Σ {r['production_total']:>7.3f} kWh")
    _sep()
    print(f"  Náklad odber:        {r['cost_consumption']:>8.4f} €")
    print(f"  Kredit Flexi:       -{r['credit_flexi']:>8.4f} €")
    print(f"  Variabilné náklady:  {r['net_variable']:>8.4f} €")
    print(f"  Fixné (1/30 mes.): + {fixed_day:>8.4f} €")
    _sep()
    print(f"  Celkom:              {r['net_variable'] + fixed_day:>8.4f} €")


def print_month(results, month_str, rates):
    fixed = sum(rates["fixed_eur_month"].values())
    cons  = sum(r["consumption_total"] for r in results)
    prod  = sum(r["production_total"]  for r in results)
    cost  = sum(r["cost_consumption"]  for r in results)
    cred  = sum(r["credit_flexi"]      for r in results)
    net   = cost - cred + fixed

    print()
    _sep("=")
    print(f"  Mesiac: {month_str}   ({len(results)} dní s dátami)")
    _sep("=")
    print(f"  Odber celkom:        {cons:>8.3f} kWh")
    print(f"  Výroba celkom:       {prod:>8.3f} kWh")
    _sep()
    print(f"  Náklad odber:        {cost:>8.4f} €")
    print(f"  Kredit Flexi:       -{cred:>8.4f} €")
    print(f"  Variabilné náklady:  {cost - cred:>8.4f} €")
    print(f"  Fixné poplatky:    + {fixed:>8.2f} €")
    _sep()
    print(f"  CELKOM:              {net:>8.4f} €")
    if cons > 0:
        print(f"  Priem. cena/kWh:     {net / cons:>8.4f} €/kWh")

    print()
    print("  Deň          Odber    Výroba   Náklad   Kredit  Netto var.")
    _sep()
    for r in results:
        flag = " *" if r["is_weho"] else ""
        print(
            f"  {r['date']}"
            f"  {r['consumption_total']:>6.3f}"
            f"  {r['production_total']:>7.3f}"
            f"  {r['cost_consumption']:>7.4f}"
            f"  {r['credit_flexi']:>7.4f}"
            f"  {r['net_variable']:>8.4f}{flag}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Kalkulácia nákladov na elektrinu")
    group  = parser.add_mutually_exclusive_group()
    group.add_argument("--date",  metavar="YYYY-MM-DD", help="Konkrétny deň (default: včera)")
    group.add_argument("--month", metavar="YYYY-MM",    help="Celý mesiac")
    args = parser.parse_args()

    from datetime import datetime
    tariffs     = load_tariffs()
    conn        = open_db()
    computed_at = datetime.now().isoformat(timespec="seconds")

    if args.month:
        year, month = map(int, args.month.split("-"))
        rates    = get_rates(year)
        holidays = sk_holidays(year)
        results  = []
        for d in range(1, monthrange(year, month)[1] + 1):
            r = calc_day(conn, date(year, month, d), tariffs, holidays)
            if r:
                save_cost(conn, r, year, computed_at)
                results.append(r)
        if not results:
            print(f"Žiadne dáta pre {args.month}.")
            conn.close()
            return
        print_month(results, args.month, rates)

    else:
        day      = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
        rates    = get_rates(day.year)
        holidays = sk_holidays(day.year)
        r        = calc_day(conn, day, tariffs, holidays)
        if not r:
            print(f"Žiadne 15-minútové dáta pre {day}.")
            conn.close()
            return
        save_cost(conn, r, day.year, computed_at)
        print_day(r, rates)

    write_costs_json(conn, computed_at)
    conn.close()


if __name__ == "__main__":
    main()
