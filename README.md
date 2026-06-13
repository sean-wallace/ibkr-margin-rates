# margin-rates

Tracks USD and CAD margin rates on Interactive Brokers over time.

Scrapes the IBKR margin rates page, saves new observations to `margin_rates_history.jsonl`, and regenerates `docs/index.html` when rates change. A GitHub Actions workflow runs this daily and commits any changes, so the chart stays current without manual intervention.

## Usage

```
uv run python main.py
```

## GitHub Pages

Enable Pages in repo settings (Deploy from branch → main → /docs) and the chart will be live at `https://<username>.github.io/<repo>/`.

The Actions workflow only commits when rates actually change, so git history reflects real rate movements rather than daily noise.
