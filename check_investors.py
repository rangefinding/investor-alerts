import requests
import json
import os
from datetime import datetime, timezone

# ─────────────────────────────────────────────
# INVESTOR CONFIG
# Each entry maps a display name to:
#   cik   – SEC EDGAR Central Index Key
#   forms – filing types to watch
# ─────────────────────────────────────────────
INVESTORS = {
    "Elon Musk": {
        "cik": "1494730",
        "forms": ["4", "SC 13D", "SC 13G"],
    },
    "Jeff Bezos": {
        "cik": "1043298",
        "forms": ["4", "SC 13D", "SC 13G"],
    },
    "Bill Gates (Foundation Trust)": {
        "cik": "1166559",
        "forms": ["13F-HR", "13F-HR/A", "SC 13D", "SC 13G"],
    },
    "Bill Ackman (Pershing Square)": {
        "cik": "1336528",
        "forms": ["13F-HR", "13F-HR/A", "SC 13D", "SC 13G"],
    },
    "Ray Dalio (Bridgewater)": {
        "cik": "1350694",
        "forms": ["13F-HR", "13F-HR/A", "SC 13D", "SC 13G"],
    },
    "Warren Buffett (Berkshire)": {
        "cik": "1067983",
        "forms": ["13F-HR", "13F-HR/A", "SC 13D", "SC 13G", "4"],
    },
    "Cathie Wood (ARK Invest)": {
        "cik": "1697748",
        "forms": ["13F-HR", "13F-HR/A", "SC 13D", "SC 13G"],
    },
}

# Form descriptions for readable Slack messages
FORM_DESCRIPTIONS = {
    "4":        "Insider Trade (Form 4) — buy/sell of company securities",
    "13F-HR":   "Quarterly Portfolio Disclosure (13F) — full holdings snapshot",
    "13F-HR/A": "Amended Quarterly Portfolio Disclosure (13F/A)",
    "SC 13D":   "Schedule 13D — activist stake (≥5% ownership w/ intent to influence)",
    "SC 13G":   "Schedule 13G — passive stake (≥5% ownership, no activist intent)",
}

STATE_FILE = "seen_filings.json"
EDGAR_BASE = "https://data.sec.gov/submissions"
HEADERS = {"User-Agent": "WhiteOrthodontics blair@whiteorthodontics.com"}


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch_recent_filings(cik: str) -> list[dict]:
    """Fetch recent filings for a CIK from SEC EDGAR submissions API."""
    padded = cik.zfill(10)
    url = f"{EDGAR_BASE}/CIK{padded}.json"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    recent = data.get("filings", {}).get("recent", {})
    accessions = recent.get("accessionNumber", [])
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    descriptions = recent.get("primaryDocument", [])

    filings = []
    for acc, form, date, doc in zip(accessions, forms, dates, descriptions):
        filings.append({
            "accession": acc,
            "form": form,
            "date": date,
            "doc": doc,
            "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=5",
        })
    return filings


def send_slack_alert(name: str, filing: dict):
    webhook_url = os.environ["SLACK_WEBHOOK_URL"]

    form = filing["form"]
    description = FORM_DESCRIPTIONS.get(form, f"SEC Filing ({form})")
    edgar_link = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={INVESTORS[name]['cik']}&type={form}&dateb=&owner=include&count=5"

    emoji = {
        "4":        ":moneybag:",
        "13F-HR":   ":bar_chart:",
        "13F-HR/A": ":bar_chart:",
        "SC 13D":   ":rotating_light:",
        "SC 13G":   ":eyes:",
    }.get(form, ":memo:")

    message = (
        f"{emoji} *New SEC Filing: {name}*\n"
        f"*Form:* {form} — {description}\n"
        f"*Filed:* {filing['date']}\n"
        f"*Accession:* `{filing['accession']}`\n"
        f"<{edgar_link}|View on SEC EDGAR>\n"
        f"_Detected at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_"
    )

    resp = requests.post(webhook_url, json={"text": message}, timeout=10)
    resp.raise_for_status()
    print(f"  ✓ Slack alert sent for {name} — {form} filed {filing['date']}")


def main():
    state = load_state()
    new_filings_found = False

    for name, config in INVESTORS.items():
        cik = config["cik"]
        watched_forms = set(config["forms"])
        seen = set(state.get(cik, []))

        print(f"\nChecking {name} (CIK: {cik})...")

        try:
            filings = fetch_recent_filings(cik)
        except Exception as e:
            print(f"  ✗ Error fetching filings: {e}")
            continue

        new_accessions = []
        for filing in filings:
            if filing["form"] not in watched_forms:
                continue
            if filing["accession"] in seen:
                continue

            # New filing found
            print(f"  → New {filing['form']} filed on {filing['date']} ({filing['accession']})")
            try:
                send_slack_alert(name, filing)
                new_filings_found = True
            except Exception as e:
                print(f"  ✗ Slack error: {e}")

            new_accessions.append(filing["accession"])

        if not new_accessions:
            print(f"  ✓ No new filings.")

        # Update state with all seen accessions (cap at 50 per investor to keep file small)
        all_seen = list(seen) + new_accessions
        state[cik] = all_seen[-50:]

    save_state(state)
    print(f"\nDone. {'New filings detected and alerted.' if new_filings_found else 'No new filings.'}")


if __name__ == "__main__":
    main()
