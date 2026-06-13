import json
import re
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

IBKR_MARGIN_URL = "https://www.interactivebrokers.ca/en/trading/margin-rates.php"
HISTORY_FILE = Path(__file__).parent / "margin_rates_history.jsonl"
TEMPLATE_FILE = Path(__file__).parent / "template.html"
CHART_FILE = Path(__file__).parent / "docs" / "index.html"


def _parse_tier_text(tier_text):
    """Return (lower_bound, upper_bound) from text like '0 ≤ 100,000' or '> 250,000,000'."""
    clean = tier_text.replace(",", "").strip()
    if clean.startswith(">"):
        nums = re.findall(r"\d+", clean)
        return (int(nums[0]), None) if nums else (None, None)
    nums = re.findall(r"\d+", clean)
    if len(nums) >= 2:
        return int(nums[0]), int(nums[1])
    return None, None


def _parse_rate_text(rate_text):
    """Return rate string like '5.120%' from '5.120%(BM +1.5%)'."""
    return rate_text.split("(")[0].strip()


def _extract_tier1_rate(rate_value):
    """Extract first-tier rate as float from either old (str) or new (list) format."""
    if isinstance(rate_value, str):
        return float(rate_value.rstrip("%"))
    if isinstance(rate_value, list) and rate_value:
        return float(rate_value[0]["rate"].rstrip("%"))
    return None


def _tiers_for_meta(rate_value):
    """Convert rate value to [{threshold, rate (float)}] list for the template."""
    if isinstance(rate_value, str):
        return [{"threshold": None, "rate": float(rate_value.rstrip("%"))}]
    if isinstance(rate_value, list):
        return [{"threshold": t["threshold"], "rate": float(t["rate"].rstrip("%"))} for t in rate_value]
    return []


def scrape_margin_rates():
    """Scrape current USD and CAD margin rates (all tiers) from Interactive Brokers."""
    try:
        response = requests.get(IBKR_MARGIN_URL, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        rates = {}
        current_currency = None
        current_tiers = []
        expected_lower = None

        table = soup.find("table")
        if not table:
            return None

        for row in table.find_all("tr"):
            cells = [cell.get_text(strip=True) for cell in row.find_all(["td", "th"])]
            if len(cells) < 3:
                continue

            currency, tier_text, rate_text = cells[0], cells[1], cells[2]

            if currency in ("USD", "CAD"):
                # New named currency block — save whatever we have and start fresh
                if current_currency and current_tiers:
                    rates[current_currency] = current_tiers
                current_currency = currency
                current_tiers = []
                expected_lower = 0
            elif currency != "":
                # Some other named currency — end current block
                if current_currency and current_tiers:
                    rates[current_currency] = current_tiers
                current_currency = None
                current_tiers = []
                expected_lower = None
                continue
            elif current_currency is None:
                continue  # blank currency row, not currently collecting

            lower, upper = _parse_tier_text(tier_text)
            if lower is None or lower != expected_lower:
                # Sequence broken — this row belongs to a different product in the table
                if current_currency and current_tiers:
                    rates[current_currency] = current_tiers
                current_currency = None
                current_tiers = []
                expected_lower = None
                continue

            rate = _parse_rate_text(rate_text)
            if "%" not in rate:
                continue

            current_tiers.append({"threshold": upper, "rate": rate})
            expected_lower = upper  # None once the last (open-ended) tier is added

            if upper is None:
                # Last tier — finalize this currency
                rates[current_currency] = current_tiers
                current_currency = None
                current_tiers = []
                expected_lower = None

        if current_currency and current_tiers:
            rates[current_currency] = current_tiers

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
        current_tier1 = _extract_tier1_rate(current_rates[currency])
        previous_rate = previous_rates.get(currency)
        if previous_rate is None:
            changes.append(f"{currency}: NEW (now {current_tier1}%)")
        else:
            previous_tier1 = _extract_tier1_rate(previous_rate)
            if current_tier1 != previous_tier1:
                changes.append(f"{currency}: {previous_tier1}% → {current_tier1}%")

    return (True, changes) if changes else (False, "No changes detected")


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
                usd_rate = _extract_tier1_rate(rates.get("USD")) if "USD" in rates else None
                cad_rate = _extract_tier1_rate(rates.get("CAD")) if "CAD" in rates else None
                raw_data.append(
                    {
                        "date": timestamp.date().isoformat(),
                        "usd": usd_rate,
                        "cad": cad_rate,
                        "rates": rates,
                    }
                )
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

        if not raw_data:
            return

        labels = [d["date"] for d in raw_data]
        usd_vals = [d["usd"] for d in raw_data]
        cad_vals = [d["cad"] for d in raw_data]
        usd_nums = [x for x in usd_vals if x is not None]
        cad_nums = [x for x in cad_vals if x is not None]

        last_rates = raw_data[-1]["rates"]
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
                "usd_tiers": _tiers_for_meta(last_rates.get("USD", [])),
                "cad_tiers": _tiers_for_meta(last_rates.get("CAD", [])),
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
    for currency, rate_value in current_rates.items():
        tier1 = _extract_tier1_rate(rate_value)
        n = len(rate_value) if isinstance(rate_value, list) else 1
        print(f"  {currency}: {tier1}% ({n} tier{'s' if n != 1 else ''})")
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
