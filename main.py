import json
import os
from datetime import datetime
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Required packages not installed. Run: pip install requests beautifulsoup4")
    exit(1)

# Configuration
IBKR_MARGIN_URL = "https://www.interactivebrokers.ca/en/trading/margin-rates.php"
DATA_FILE = Path(__file__).parent / "margin_rates_data.json"


def scrape_margin_rates():
    """Scrape current USD and CAD margin rates from Interactive Brokers."""
    try:
        response = requests.get(IBKR_MARGIN_URL, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        rates = {}

        # Find the margin rates table
        tables = soup.find_all('table')

        if not tables:
            print("Error: No tables found on page")
            return None

        # Parse the main table (usually the first one)
        table = tables[0]
        rows = table.find_all('tr')

        current_currency = None

        for row in rows:
            cells = row.find_all(['td', 'th'])
            if not cells:
                continue

            # Get text from all cells
            cell_texts = [cell.get_text(strip=True) for cell in cells]

            # Check if this row indicates a currency
            if len(cell_texts) > 0 and cell_texts[0] in ['USD', 'CAD', 'EUR', 'GBP', 'CHF', 'AUD', 'JPY', 'HKD', 'SEK', 'NOK', 'DKK', 'SGD']:
                current_currency = cell_texts[0]

            # Check if this is a base tier row (tier 0)
            if current_currency and len(cell_texts) >= 3:
                tier_text = cell_texts[0] if cell_texts[0] != current_currency else (cell_texts[1] if len(cell_texts) > 1 else '')

                # Look for tier 0 (base tier) - starts with "0" or is empty after currency
                if tier_text.startswith('0') or (current_currency in ['USD', 'CAD'] and '≤' in ' '.join(cell_texts)):
                    # Find the rate (usually has % sign)
                    for cell_text in cell_texts:
                        if '%' in cell_text:
                            # Extract just the percentage rate
                            rate = cell_text.split('%')[0].split('(')[0].strip() + '%'
                            if current_currency in ['USD', 'CAD']:
                                rates[current_currency] = rate
                            # Reset currency after finding base tier
                            current_currency = None
                            break

        if not rates:
            print("Warning: Could not find margin rates on page. Page structure may have changed.")
            return None

        return rates

    except requests.RequestException as e:
        print(f"Error fetching margin rates: {e}")
        return None


def load_previous_rates():
    """Load previously stored margin rates from file."""
    if not DATA_FILE.exists():
        return None

    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
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
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
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
    print("=" * 60)
    print("Interactive Brokers Margin Rate Checker")
    print("=" * 60)
    print()

    # Scrape current rates
    print("Fetching current margin rates...")
    current_rates = scrape_margin_rates()

    if not current_rates:
        print("Failed to retrieve margin rates. Exiting.")
        return

    print(f"✓ Successfully retrieved rates")
    print()

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
    print(f"✓ Rates saved to {DATA_FILE}")
    print()


if __name__ == "__main__":
    main()
