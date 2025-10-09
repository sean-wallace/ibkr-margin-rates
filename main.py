import json
import os
from datetime import datetime
from pathlib import Path


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
        soup = BeautifulSoup(response.content, 'html.parser')

        rates = {}
        table = soup.find('table')
        if not table:
            return None

        for row in table.find_all('tr'):
            cells = [cell.get_text(strip=True) for cell in row.find_all(['td', 'th'])]
            if len(cells) < 3:
                continue

            # Look for rows with: Currency, tier starting with 0, and a percentage rate
            currency = cells[0]
            tier = cells[1]

            if currency in ['USD', 'CAD'] and tier.startswith('0') and '≤' in tier:
                # Find the rate (has % symbol)
                for cell in cells:
                    if '%' in cell and any(char.isdigit() for char in cell):
                        # Extract the rate, removing parenthetical info
                        rate = cell.split('(')[0].strip()
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
        with open(HISTORY_FILE, 'r') as f:
            lines = f.readlines()
            if lines:
                return json.loads(lines[-1].strip())
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error reading previous rates: {e}")

    return None


def save_rates(rates):
    """Save current rates to file with timestamp."""
    data = {
        'timestamp': datetime.now().isoformat(),
        'rates': rates
    }

    try:
        # Append to history (JSON Lines format)
        with open(HISTORY_FILE, 'a') as f:
            f.write(json.dumps(data) + '\n')
    except IOError as e:
        print(f"Error saving rates: {e}")


def check_for_changes(current_rates, previous_data):
    """Compare current rates with previous rates and return change status."""
    if not previous_data or 'rates' not in previous_data:
        return True, "First run - no previous data"

    previous_rates = previous_data['rates']
    changes = []

    for currency in current_rates:
        if currency not in previous_rates:
            changes.append(f"{currency}: NEW (now {current_rates[currency]})")
        elif current_rates[currency] != previous_rates[currency]:
            changes.append(f"{currency}: {previous_rates[currency]} → {current_rates[currency]}")

    if changes:
        return True, changes

    return False, "No changes detected"


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


if __name__ == "__main__":
    main()
