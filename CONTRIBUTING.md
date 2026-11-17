# Contributing to AgriSense AI

Thanks for helping! Bug reports, data corrections and improvements are all welcome.

## Set up

```bash
git clone https://github.com/Prasanna-1166/AgriSense-AI.git && cd AgriSense-AI
python3.12 -m venv venv && source venv/bin/activate     # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest tests -q                                # everything should pass
python app.py                                            # http://127.0.0.1:5000
```

## The one rule: no unsourced agricultural data

AgriSense shows seed rates, fertilizer doses, durations, costs and prices **only** when they trace to a
named, dated source (ICAR institutes, state agricultural universities, government departments, official
statistics). If you cannot source a value, leave it `UNAVAILABLE` — never estimate, average across
"similar" crops, or copy from a blog. To add or correct data, edit `config/crop_agronomy_data.py`
(the single source of truth) and include the source URL and year in your pull request.

## Guidelines

- Keep it simple: prefer the existing structure and avoid new dependencies.
- Add or update tests for behaviour you change; the suite must pass (`pytest`) — CI runs it on every PR.
- Do not change the pinned `scikit-learn` version without retraining the models in `models/`.
- Never commit secrets (`.env` is ignored; `.env.example` holds placeholders only).
- Do not retrain or replace the ML models in a drive-by change; open an issue first.
