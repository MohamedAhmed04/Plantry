"""Deterministic recipe-ranking and weekly-planning domain services."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from .models import PlannedMeal, Recipe, UserPreference, WeeklyMealPlan


CENT = Decimal("0.01")


class PlanningError(ValueError):
    """Raised when no plan can satisfy all hard constraints."""


def compatibility_reasons(recipe, preferences):
    reasons = []
    if preferences.vegan and not recipe.is_vegan:
        reasons.append("not vegan")
    elif preferences.vegetarian and not recipe.is_vegetarian:
        reasons.append("not vegetarian")
    if preferences.gluten_allergy and not recipe.is_gluten_free:
        reasons.append("contains gluten")
    if preferences.dairy_allergy and not recipe.is_dairy_free:
        reasons.append("contains dairy")
    if preferences.nut_allergy and not recipe.is_nut_free:
        reasons.append("contains nuts")

    lines = list(recipe.ingredient_lines.all())
    excluded_ids = getattr(preferences, "_excluded_ids", None)
    if excluded_ids is None:
        excluded_ids = set(preferences.excluded_ingredients.values_list("id", flat=True))
    if any(line.ingredient_id in excluded_ids for line in lines):
        reasons.append("uses an excluded ingredient")
    if preferences.gluten_allergy and any(line.ingredient.contains_gluten for line in lines):
        reasons.append("contains a gluten allergen")
    if preferences.dairy_allergy and any(line.ingredient.contains_dairy for line in lines):
        reasons.append("contains a dairy allergen")
    if preferences.nut_allergy and any(line.ingredient.contains_nuts for line in lines):
        reasons.append("contains a nut allergen")
    return list(dict.fromkeys(reasons))


def pantry_snapshot(user):
    return {item.ingredient_id: Decimal(item.quantity) for item in user.pantry_items.select_related("ingredient")}


def _requirements(recipe):
    servings = Decimal(recipe.servings)
    return {
        line.ingredient_id: (Decimal(line.quantity) / servings, line.ingredient.unit_price)
        for line in recipe.ingredient_lines.all()
    }


def recipe_metrics(recipe, pantry):
    requirements = _requirements(recipe)
    if not requirements:
        return {"pantry_overlap": 0, "missing_cost": Decimal("0.00"), "requirements": {}}
    coverage = []
    missing_cost = Decimal("0")
    for ingredient_id, (needed, price) in requirements.items():
        available = pantry.get(ingredient_id, Decimal("0"))
        coverage.append(min(available / needed, Decimal("1")) if needed else Decimal("1"))
        missing_cost += max(needed - available, Decimal("0")) * price
    overlap = int((sum(coverage, Decimal("0")) / len(coverage) * 100).quantize(Decimal("1")))
    return {
        "pantry_overlap": overlap,
        "missing_cost": missing_cost.quantize(CENT, rounding=ROUND_HALF_UP),
        "requirements": requirements,
    }


def rank_recipes(recipes, preferences, pantry):
    if not hasattr(preferences, "_excluded_ids"):
        preferences._excluded_ids = set(preferences.excluded_ingredients.values_list("id", flat=True))
    ranked = []
    for recipe in recipes:
        reasons = compatibility_reasons(recipe, preferences)
        metrics = recipe_metrics(recipe, pantry)
        protein_bonus = min(Decimal(recipe.protein_grams) / max(Decimal(preferences.meal_protein_target), 1), 1)
        calorie_gap = abs(recipe.calories_per_serving - preferences.meal_calorie_target)
        score = (
            Decimal(metrics["pantry_overlap"]) * Decimal("0.7")
            + protein_bonus * Decimal("20")
            + max(Decimal("0"), Decimal("10") - Decimal(calorie_gap) / Decimal("50"))
            - metrics["missing_cost"]
        )
        ranked.append({"recipe": recipe, **metrics, "compatible": not reasons, "reasons": reasons, "score": score.quantize(Decimal("0.1"))})
    return sorted(ranked, key=lambda item: (not item["compatible"], -item["score"], item["recipe"].title))


@dataclass
class _State:
    recipe_ids: tuple
    pantry: dict
    cost: Decimal
    overlaps: tuple
    meal_costs: tuple
    protein_shortfall: Decimal


def _state_score(state):
    repeats = len(state.recipe_ids) - len(set(state.recipe_ids))
    overlap_reward = Decimal(sum(state.overlaps)) / Decimal("100")
    return state.cost + state.protein_shortfall * Decimal("0.18") + Decimal(repeats * 2) - overlap_reward


def solve_week(recipes, preferences, pantry, beam_width=400):
    """Find a reproducible plan satisfying all hard constraints.

    Hard constraints: dietary/allergy exclusions, a calorie ceiling of 125% of the
    target, weekly budget, normalized ingredient consumption, and at most two uses
    of a recipe. Protein, pantry overlap, purchase cost, and variety are optimized.
    """
    if not hasattr(preferences, "_excluded_ids"):
        preferences._excluded_ids = set(preferences.excluded_ingredients.values_list("id", flat=True))
    compatible = []
    calorie_ceiling = int(preferences.meal_calorie_target * 1.25)
    for recipe in recipes:
        if not compatibility_reasons(recipe, preferences) and recipe.calories_per_serving <= calorie_ceiling:
            compatible.append(recipe)
    compatible.sort(key=lambda recipe: recipe.id)
    if not compatible:
        raise PlanningError("No recipes match your dietary and calorie constraints.")
    if len(compatible) * 2 < preferences.meals_per_week:
        raise PlanningError("Not enough compatible recipes to build a varied week (maximum two repeats each).")

    states = [_State((), dict(pantry), Decimal("0"), (), (), Decimal("0"))]
    for _ in range(preferences.meals_per_week):
        expanded = []
        for state in states:
            for recipe in compatible:
                if state.recipe_ids.count(recipe.id) >= 2:
                    continue
                metrics = recipe_metrics(recipe, state.pantry)
                new_cost = state.cost + metrics["missing_cost"]
                if new_cost > preferences.weekly_budget:
                    continue
                remaining = dict(state.pantry)
                for ingredient_id, (needed, _price) in metrics["requirements"].items():
                    remaining[ingredient_id] = max(remaining.get(ingredient_id, Decimal("0")) - needed, Decimal("0"))
                shortfall = max(Decimal(preferences.meal_protein_target) - recipe.protein_grams, Decimal("0"))
                expanded.append(_State(state.recipe_ids + (recipe.id,), remaining, new_cost, state.overlaps + (metrics["pantry_overlap"],), state.meal_costs + (metrics["missing_cost"],), state.protein_shortfall + shortfall))
        if not expanded:
            raise PlanningError("Your weekly budget is too low for a complete plan with the current pantry.")
        states = sorted(expanded, key=lambda state: (_state_score(state), state.recipe_ids))[:beam_width]
    return states[0]


@transaction.atomic
def generate_plan(user, week_start):
    preferences, _ = UserPreference.objects.get_or_create(user=user)
    recipes = list(Recipe.objects.prefetch_related("ingredient_lines__ingredient"))
    state = solve_week(recipes, preferences, pantry_snapshot(user))
    recipes_by_id = {recipe.id: recipe for recipe in recipes}
    plan, _ = WeeklyMealPlan.objects.update_or_create(
        user=user,
        week_start=week_start,
        defaults={
            "budget_limit": preferences.weekly_budget,
            "estimated_cost": state.cost.quantize(CENT),
            "average_pantry_overlap": round(sum(state.overlaps) / len(state.overlaps)),
            "solver_summary": {"algorithm": "deterministic beam search", "protein_shortfall_grams": float(state.protein_shortfall), "meals": len(state.recipe_ids)},
        },
    )
    plan.meals.all().delete()
    for index, recipe_id in enumerate(state.recipe_ids):
        PlannedMeal.objects.create(
            plan=plan,
            day_index=index % 7,
            slot=PlannedMeal.Slot.DINNER if index < 7 else PlannedMeal.Slot.LUNCH,
            recipe=recipes_by_id[recipe_id],
            estimated_cost=state.meal_costs[index],
            pantry_overlap=state.overlaps[index],
        )
    return plan
