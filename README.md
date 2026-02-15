# Health Skill

Comprehensive fitness and diet tracking with natural language meal logging, workout logging, Fitbit integration, and daily health summaries.

## Features

- **Natural language meal logging** — "I had chicken breast and rice for lunch at 2:30 PM"
- **Natural language workout logging** — "I did 34 situps", "3 sets of bench press at 225 lbs"
- **Automatic macro calculation** — calories, protein, carbs, fat, sodium, fiber from a 450K+ food database
- **Fitbit integration** — automated sync of steps, heart rate, HRV, sleep, weight, body composition, active minutes, and more
- **Daily health summaries** — combined diet + workout + Fitbit report with coaching notes

## Setup

### 1. Configuration

Copy the default config and edit for your environment:

```bash
cp config.default.json config.json
```

Edit `config.json` with your workspace paths:

```json
{
  "WORKSPACE": "/path/to/your/workspace",
  "FITNESS_DIR": "/path/to/your/workspace/fitness",
  "DIET_DIR": "/path/to/your/workspace/diet"
}
```

Alternatively, set environment variables prefixed with `HEALTH_SKILL_`:

```bash
export HEALTH_SKILL_WORKSPACE=/path/to/your/workspace
```

### 2. Food Database

The macro calculator supports **multiple simultaneous data sources**. All enabled sources are queried in parallel and results are merged by relevance. Configure which sources to use via `FOOD_SOURCES` in `config.json`:

```json
{
  "FOOD_SOURCES": ["local_db", "opennutrition", "usda_api"]
}
```

Sources that are unavailable (missing database, no API key) are silently skipped.

#### Source A: ComprehensiveFoodDatabase — `local_db` (450K+ foods, offline)

Pre-built SQLite database with USDA branded, non-branded, and restaurant (MenuStat) data. Automated setup (requires [megatools](https://megatools.megous.com/)):

```bash
sudo apt install megatools   # or: brew install megatools
python3 scripts/import_local_db.py
```

This downloads ~1.4 GB from Mega.nz and extracts the SQLite database. You can also import from a local ZIP:

```bash
python3 scripts/import_local_db.py /path/to/CompFoodCSV.zip
```

#### Source B: OpenNutrition Dataset — `opennutrition` (300K+ foods, offline)

Community-maintained nutrition dataset. One-time import:

```bash
python3 scripts/import_opennutrition.py
```

This downloads and imports the dataset into `data/opennutrition.sqlite`. You can also import from a local TSV file:

```bash
python3 scripts/import_opennutrition.py /path/to/foods.tsv
```

#### Source C: USDA FoodData Central API — `usda_api` (live, requires API key)

Free API key, live queries against USDA database:

1. Register at https://fdc.nal.usda.gov/api-key-signup
2. Set `HEALTH_SKILL_USDA_API_KEY` in `.env` (see `.env.example`)

### 3. Fitbit Integration (Optional)

See [scripts/fitbit-integration/README.md](scripts/fitbit-integration/README.md) for Fitbit setup.

### 4. Directory Structure

Create the data directories referenced in your config:

```bash
mkdir -p /path/to/your/workspace/fitness/fitbit
mkdir -p /path/to/your/workspace/diet/images
mkdir -p /path/to/your/workspace/summaries
```

## Usage

### Log a meal

```bash
python3 scripts/calculate_macros.py "chicken breast and rice for lunch at 2:30 PM"
```

### Log a workout

```bash
python3 scripts/log_workout.py "I did 34 situps"
python3 scripts/log_workout.py "3 sets of 10 bench press at 225 lbs"
python3 scripts/log_workout.py "5k run, 25 minutes"
```

### Generate daily summary

```bash
python3 scripts/generate_daily_summary.py
python3 scripts/regenerate_summary.py 2025-01-15
```

## Testing

```bash
pip install -r requirements.txt
pytest tests/
```

## Project Structure

```
health-skill/
├── config.py                  # Centralized configuration
├── config.default.json        # Default config template
├── SKILL.md                   # AI agent skill definition
├── scripts/
│   ├── calculate_macros.py    # Natural language meal parsing + macro lookup
│   ├── query_food_db.py       # Multi-source food database queries
│   ├── import_local_db.py      # Download + setup ComprehensiveFoodDatabase from Mega
│   ├── import_opennutrition.py # One-time OpenNutrition dataset import
│   ├── log_workout.py         # Natural language workout parsing + logging
│   ├── generate_daily_summary.py  # Daily health report generation
│   ├── regenerate_summary.py  # Regenerate summary for a past date
│   └── fitbit-integration/    # Fitbit API sync (bash)
├── data/                      # Food databases (not in repo)
├── references/                # Macro guidelines, templates
└── tests/                     # Pytest test suite
```

## License

MIT
