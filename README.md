# PantryPilot

PantryPilot is a full-stack Django meal-planning application that turns pantry inventory, dietary restrictions, allergies, nutrition goals, and a weekly budget into a practical menu. Discovery ranks recipes by pantry coverage and constraint fit; the weekly planner then consumes pantry quantities and estimates only the ingredients that still need to be purchased.

## Features

- Account-backed pantry inventory with normalized ingredient quantities and estimated values
- Dietary preferences (vegetarian and vegan), common allergy exclusions, and arbitrary ingredient exclusions
- Per-meal calorie and protein goals, a weekly shopping budget, and configurable meal count
- Searchable recipe discovery ranked by pantry overlap, nutrition fit, and remaining purchase cost
- Persisted weekly plans with per-meal pantry coverage, cost estimates, and nutrition summaries
- Normalized recipe ingredients plus a human-readable ingredient list
- Idempotent demo catalog and account for local evaluation
- Responsive Bootstrap 5 UI and Django admin support

## Local setup

Python 3.12 is recommended.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Open <http://127.0.0.1:8000>. The seed command creates a local demo account:

- Username: `demo`
- Password: `PantryPilot123!`

The command is idempotent, so it is safe to rerun while developing. Create a superuser with `python manage.py createsuperuser` to edit ingredient pricing and allergen metadata through `/admin/`.

Pipenv users can instead run `pipenv install --dev` and prefix management commands with `pipenv run`.

## Architecture

The project remains a conventional server-rendered Django application:

- `recipes/models.py` contains recipes, normalized ingredients, pantry inventory, one-to-one user preferences, and persisted weekly plans.
- `recipes/services.py` isolates ranking and planning domain logic from HTTP views. It accepts model-backed inputs and plain pantry snapshots, making the core behavior straightforward to test.
- `recipes/forms.py` enforces input bounds and creates normalized recipe lines through an inline formset.
- `recipes/views.py` handles authentication-aware discovery and the pantry → constraints → generated-plan workflow.
- `recipes/management/commands/seed_demo.py` supplies realistic local data without changing the committed database.

All application queries use Django's ORM and are backend-agnostic. SQLite remains the default for zero-configuration local and test use. `DJANGO_DB_PATH` lets deployments place the database on persistent storage; a PostgreSQL deployment can replace the `DATABASES` setting without changing application code.

### Planner design

The planner uses a deterministic, bounded beam search instead of OR-Tools. OR-Tools would add a large native dependency for a problem that is currently small (at most 14 meal slots), while deterministic search keeps installation and SQLite-based evaluation reliable.

Hard constraints:

1. Vegetarian/vegan requirements and allergen or explicit ingredient exclusions
2. A calorie ceiling of 125% of the user's per-meal target
3. The weekly purchase budget
4. Pantry quantities consumed across the whole plan, with missing quantities priced per canonical unit
5. At most two appearances of a recipe for baseline variety

Within the feasible set, the scoring function favors pantry coverage, low missing cost, protein-target coverage, and variety. Stable recipe ordering and deterministic tie-breaking make identical inputs produce identical plans. If no feasible plan exists, the UI reports whether compatible recipe variety or budget is the limiting constraint rather than silently relaxing a hard rule.

Ingredient prices and nutrition values are planning estimates, not purchasing or medical advice. Pantry stock is modeled in each ingredient's canonical unit; package sizes and store-specific pricing are intentionally outside the current scope.

## Configuration

Copy `.env.example` values into your runtime environment (Django does not read the file automatically):

| Variable | Purpose | Default |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | Signing secret; required to override in production | local-only key |
| `DJANGO_DEBUG` | `true` or `false` | `true` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated host names | localhost/test hosts |
| `DJANGO_DB_PATH` | SQLite database path | `db.sqlite3` |

The remaining `DJANGO_SECURE_*`, cookie, and forwarded-protocol variables in `.env.example` opt into Django's HTTPS deployment protections. Only trust `X-Forwarded-Proto` when your own reverse proxy overwrites that header.

Before deployment, set a strong secret, disable debug mode, configure allowed hosts, run `python manage.py collectstatic`, and run `python manage.py check --deploy` against the production environment.

## Verification

```bash
python manage.py test
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py collectstatic --noinput
```

The automated suite covers allergen and ingredient exclusions, pantry overlap math, purchase costs, budget infeasibility, calorie filtering, determinism, repeat limits, plan persistence, validation bounds, authentication, pantry ownership, recipe creation, and the main web planning flow.
