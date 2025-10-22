import json
from datetime import datetime, timedelta
from pathlib import Path

import asciichartpy
import requests
from bs4 import BeautifulSoup

# Configuration
IBKR_MARGIN_URL = "https://www.interactivebrokers.ca/en/trading/margin-rates.php"
HISTORY_FILE = Path(__file__).parent / "margin_rates_history.jsonl"


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
    data = {
        "timestamp": datetime.now().isoformat(),
        "rates": rates,
    }

    try:
        # Append to history (JSON Lines format)
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(data) + "\n")
    except OSError as e:
        print(f"Error saving rates: {e}")


def prune_history():
    """Keep only one entry per day (the latest) in the history file."""
    if not HISTORY_FILE.exists():
        return

    try:
        # Read all entries
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


def generate_rate_chart():
    """Generate ASCII chart of historical margin rates with interpolated missing days."""
    if not HISTORY_FILE.exists():
        return

    try:
        with open(HISTORY_FILE) as f:
            lines = f.readlines()

        if len(lines) < 2:
            print("Not enough historical data to generate chart.")
            return

        # Parse historical data
        raw_data = []
        for line in lines:
            try:
                data = json.loads(line.strip())
                rates = data["rates"]
                timestamp = datetime.fromisoformat(data["timestamp"])

                usd_rate = float(rates["USD"].rstrip("%")) if "USD" in rates else None
                cad_rate = float(rates["CAD"].rstrip("%")) if "CAD" in rates else None

                raw_data.append({"date": timestamp.date(), "usd": usd_rate, "cad": cad_rate})
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

        if not raw_data:
            return

        # Fill in missing dates with interpolated values
        start_date = raw_data[0]["date"]
        end_date = raw_data[-1]["date"]
        actual_dates = {entry["date"] for entry in raw_data}
        date_map = {entry["date"]: entry for entry in raw_data}

        # Build complete series with interpolated values
        usd_series = []
        cad_series = []
        dates = []
        last_usd = None
        last_cad = None
        current_date = start_date

        while current_date <= end_date:
            dates.append(current_date.strftime("%Y-%m-%d"))

            if current_date in actual_dates:
                entry = date_map[current_date]
                last_usd = entry["usd"]
                last_cad = entry["cad"]

            usd_series.append(last_usd)
            cad_series.append(last_cad)
            current_date += timedelta(days=1)

        print("\nHistorical Margin Rates:")
        print("=" * 60)

        # Generate chart
        has_usd = any(x is not None for x in usd_series)
        has_cad = any(x is not None for x in cad_series)

        if has_usd and has_cad:
            print(f"\nMargin Rates ({dates[0]} to {dates[-1]}, {len(dates)} days):")

            config = {"height": 10, "colors": [asciichartpy.blue, asciichartpy.red], "format": "{:8.3f}%"}
            print(asciichartpy.plot([usd_series, cad_series], config))

            usd_vals = [x for x in usd_series if x is not None]
            cad_vals = [x for x in cad_series if x is not None]

            print(f"  USD (blue):  Current: {usd_series[-1]}% | Min: {min(usd_vals)}% | Max: {max(usd_vals)}%")
            print(f"  CAD (red):   Current: {cad_series[-1]}% | Min: {min(cad_vals)}% | Max: {max(cad_vals)}%")
            print(f"  ({len(actual_dates)} actual data points, {len(dates) - len(actual_dates)} interpolated)")

    except OSError as e:
        print(f"Error generating chart: {e}")


def main():
    # Scrape current rates
    current_rates = scrape_margin_rates()

    if not current_rates:
        print("Failed to retrieve margin rates. Exiting.")
        return

    # Load previous rates
    previous_data = load_previous_rates()

    # Check for changes
    has_changes, change_info = check_for_changes(current_rates, previous_data)

    # Display results
    print("Current Rates:")
    print("-" * 60)
    for currency, rate in current_rates.items():
        print(f"  {currency}: {rate}")
    print()

    if has_changes:
        print("⚠ CHANGES DETECTED:")
        print("-" * 60)
        if isinstance(change_info, list):
            for change in change_info:
                print(f"  {change}")
        else:
            print(f"  {change_info}")
    else:
        print("✓ No changes since last check")
    if previous_data:
        print(f"  Last checked: {previous_data.get('timestamp', 'Unknown')}")

    print()

    # Save current rates
    save_rates(current_rates)

    # Prune history to keep only one entry per day
    prune_history()

    # Generate ASCII chart of historical rates
    generate_rate_chart()


if __name__ == "__main__":
    main()
