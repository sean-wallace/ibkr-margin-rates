import json
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

IBKR_MARGIN_URL = "https://www.interactivebrokers.ca/en/trading/margin-rates.php"
HISTORY_FILE = Path(__file__).parent / "margin_rates_history.jsonl"
TEMPLATE_FILE = Path(__file__).parent / "template.html"
CHART_FILE = Path(__file__).parent / "docs" / "index.html"


def scrape_margin_rates():
    """Scrape current USD and CAD margin rates from Interactive Brokers."""
    try:
        response = requests.get(IBKR_MARGIN_URL, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        rates = {}
        table = soup.find("table")
        if not table:
            return None

        for row in table.find_all("tr"):
            cells = [cell.get_text(strip=True) for cell in row.find_all(["td", "th"])]
            if len(cells) < 3:
                continue

            # Look for rows with: Currency, tier starting with 0, and a percentage rate
            currency = cells[0]
            tier = cells[1]

            if currency in ["USD", "CAD"] and tier.startswith("0") and "≤" in tier:
                # Find the rate (has % symbol)
                for cell in cells:
                    if "%" in cell and any(char.isdigit() for char in cell):
                        # Extract the rate, removing parenthetical info
                        rate = cell.split("(")[0].strip()
                        rates[currency] = rate
                        break

        return rates if rates else None

    except Exception as e:
        print(f"Error fetching margin rates: {e}")
        return None


def load_previous_rates():
    """Load previously stored margin rates from file."""
    if not HISTORY_FILE.exists():
        return None

    try:
        with open(HISTORY_FILE) as f:
            lines = f.readlines()
            if lines:
                return json.loads(lines[-1].strip())
    except (OSError, json.JSONDecodeError) as e:
        print(f"Error reading previous rates: {e}")

    return None


def save_rates(rates):
    """Save current rates to file with timestamp."""
    data = {"timestamp": datetime.now().isoformat(), "rates": rates}
    try:
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(data) + "\n")
    except OSError as e:
        print(f"Error saving rates: {e}")


def prune_history():
    """Keep only one entry per day (the latest) in the history file."""
    if not HISTORY_FILE.exists():
        return

    try:
        with open(HISTORY_FILE) as f:
            lines = f.readlines()

        if not lines:
            return

        # Group entries by date, keeping the latest for each day
        entries_by_date = {}
        for line in lines:
            try:
                data = json.loads(line.strip())
                timestamp = datetime.fromisoformat(data["timestamp"])
                date_key = timestamp.date().isoformat()

                # Keep only if this is the first entry for this date or if it's later
                if date_key not in entries_by_date:
                    entries_by_date[date_key] = (timestamp, data)
                else:
                    existing_timestamp, _ = entries_by_date[date_key]
                    if timestamp > existing_timestamp:
                        entries_by_date[date_key] = (timestamp, data)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

        # Write back only the latest entry for each day, sorted by date
        with open(HISTORY_FILE, "w") as f:
            for date_key in sorted(entries_by_date.keys()):
                _, data = entries_by_date[date_key]
                f.write(json.dumps(data) + "\n")

    except OSError as e:
        print(f"Error pruning history: {e}")


def check_for_changes(current_rates, previous_data):
    """Compare current rates with previous rates and return change status."""
    if not previous_data or "rates" not in previous_data:
        return True, "First run - no previous data"

    previous_rates = previous_data["rates"]
    changes = []

    for currency in current_rates:
        if currency not in previous_rates:
            changes.append(f"{currency}: NEW (now {current_rates[currency]})")
        elif current_rates[currency] != previous_rates[currency]:
            changes.append(f"{currency}: {previous_rates[currency]} → {current_rates[currency]}")

    if changes:
        return True, changes

    return False, "No changes detected"


def generate_html_chart():
    """Generate docs/index.html from the full rate history."""
    if not HISTORY_FILE.exists():
        return

    try:
        with open(HISTORY_FILE) as f:
            lines = f.readlines()

        if not lines:
            return

        raw_data = []
        for line in lines:
            try:
                data = json.loads(line.strip())
                rates = data["rates"]
                timestamp = datetime.fromisoformat(data["timestamp"])
                usd_rate = float(rates["USD"].rstrip("%")) if "USD" in rates else None
                cad_rate = float(rates["CAD"].rstrip("%")) if "CAD" in rates else None
                raw_data.append({"date": timestamp.date().isoformat(), "usd": usd_rate, "cad": cad_rate})
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

        if not raw_data:
            return

        labels = [d["date"] for d in raw_data]
        usd_vals = [d["usd"] for d in raw_data]
        cad_vals = [d["cad"] for d in raw_data]
        usd_nums = [x for x in usd_vals if x is not None]
        cad_nums = [x for x in cad_vals if x is not None]

        rate_data = {
            "labels": labels,
            "usd": usd_vals,
            "cad": cad_vals,
            "meta": {
                "date_range": f"{labels[0]} to {labels[-1]}",
                "n_points": len(raw_data),
                "usd_current": f"{usd_nums[-1]:.3f}",
                "usd_min": f"{min(usd_nums):.3f}",
                "usd_max": f"{max(usd_nums):.3f}",
                "cad_current": f"{cad_nums[-1]:.3f}",
                "cad_min": f"{min(cad_nums):.3f}",
                "cad_max": f"{max(cad_nums):.3f}",
                "last_updated": labels[-1],
            },
        }

        template = TEMPLATE_FILE.read_text()
        html = template.replace("__RATE_DATA__", json.dumps(rate_data, indent=2))

        CHART_FILE.parent.mkdir(exist_ok=True)
        CHART_FILE.write_text(html)
        print(f"Chart: {CHART_FILE}")

    except OSError as e:
        print(f"Error generating chart: {e}")


def main():
    current_rates = scrape_margin_rates()

    if not current_rates:
        print("Failed to retrieve margin rates. Exiting.")
        return

    previous_data = load_previous_rates()
    has_changes, change_info = check_for_changes(current_rates, previous_data)

    print("Current Rates:")
    print("-" * 40)
    for currency, rate in current_rates.items():
        print(f"  {currency}: {rate}")
    print()

    if has_changes:
        print("CHANGES DETECTED:")
        print("-" * 40)
        if isinstance(change_info, list):
            for change in change_info:
                print(f"  {change}")
        else:
            print(f"  {change_info}")
        print()
        save_rates(current_rates)
        prune_history()
        generate_html_chart()
    else:
        print("No changes since last check")
        if previous_data:
            print(f"  Last checked: {previous_data.get('timestamp', 'Unknown')}")


if __name__ == "__main__":
    main()
