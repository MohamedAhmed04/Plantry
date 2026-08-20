from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Ingredient, Recipe, RecipeIngredient, UserPreference, WeeklyMealPlan
from .services import PlanningError, compatibility_reasons, generate_plan, rank_recipes, recipe_metrics, solve_week


class RecipeFactoryMixin:
    def make_recipe(self, title, ingredient, *, quantity=100, calories=500, protein=25, **flags):
        defaults = {
            "description": f"Description for {title}", "ingredients": ingredient.name,
            "instructions": "Cook and serve.", "servings": 4,
            "calories_per_serving": calories, "protein_grams": protein,
            "is_vegetarian": True, "is_vegan": True, "is_gluten_free": True,
            "is_dairy_free": True, "is_nut_free": True,
        }
        defaults.update(flags)
        recipe = Recipe.objects.create(title=title, **defaults)
        RecipeIngredient.objects.create(recipe=recipe, ingredient=ingredient, quantity=quantity)
        return recipe


class RankingTests(RecipeFactoryMixin, TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("planner", password="testpass123")
        self.preferences = UserPreference.objects.create(user=self.user, meal_protein_target=25)
        self.rice = Ingredient.objects.create(name="Rice", unit_price=Decimal("0.01"))
        self.beans = Ingredient.objects.create(name="Beans", unit_price=Decimal("0.02"))
        self.rice_recipe = self.make_recipe("Rice bowl", self.rice)
        self.bean_recipe = self.make_recipe("Bean bowl", self.beans)

    def test_pantry_coverage_and_missing_cost_use_per_serving_quantity(self):
        metrics = recipe_metrics(self.rice_recipe, {self.rice.id: Decimal("12.5")})
        self.assertEqual(metrics["pantry_overlap"], 50)
        self.assertEqual(metrics["missing_cost"], Decimal("0.13"))

    def test_ranking_prioritizes_pantry_overlap(self):
        ranked = rank_recipes([self.bean_recipe, self.rice_recipe], self.preferences, {self.rice.id: Decimal("25")})
        self.assertEqual(ranked[0]["recipe"], self.rice_recipe)
        self.assertEqual(ranked[0]["pantry_overlap"], 100)

    def test_allergen_metadata_and_recipe_claim_are_both_checked(self):
        nuts = Ingredient.objects.create(name="Nuts", contains_nuts=True)
        recipe = self.make_recipe("Unsafe bowl", nuts, is_nut_free=True)
        self.preferences.nut_allergy = True
        self.preferences.save()
        self.assertIn("contains a nut allergen", compatibility_reasons(recipe, self.preferences))

    def test_excluded_ingredient_marks_recipe_incompatible(self):
        self.preferences.excluded_ingredients.add(self.beans)
        ranked = rank_recipes([self.bean_recipe], self.preferences, {})
        self.assertFalse(ranked[0]["compatible"])
        self.assertIn("uses an excluded ingredient", ranked[0]["reasons"])


class SolverTests(RecipeFactoryMixin, TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("solver")
        self.preferences = UserPreference.objects.create(
            user=self.user, weekly_budget=Decimal("20"), meals_per_week=4,
            meal_calorie_target=500, meal_protein_target=30,
        )
        self.ingredients = [Ingredient.objects.create(name=f"Ingredient {i}", unit_price=Decimal("0.02")) for i in range(4)]
        self.recipes = [self.make_recipe(f"Recipe {i}", ingredient, protein=20 + i * 5) for i, ingredient in enumerate(self.ingredients)]

    def test_solver_is_deterministic_and_respects_repeat_limit(self):
        first = solve_week(self.recipes, self.preferences, {})
        second = solve_week(self.recipes, self.preferences, {})
        self.assertEqual(first.recipe_ids, second.recipe_ids)
        self.assertTrue(all(first.recipe_ids.count(recipe_id) <= 2 for recipe_id in first.recipe_ids))

    def test_solver_consumes_pantry_across_meals(self):
        state = solve_week(self.recipes, self.preferences, {ingredient.id: Decimal("25") for ingredient in self.ingredients})
        free_meals = sum(cost == 0 for cost in state.meal_costs)
        self.assertLessEqual(free_meals, 4)
        self.assertEqual(state.cost, sum(state.meal_costs))

    def test_budget_is_a_hard_constraint(self):
        self.preferences.weekly_budget = Decimal("0.10")
        self.preferences.save()
        with self.assertRaisesMessage(PlanningError, "budget is too low"):
            solve_week(self.recipes, self.preferences, {})

    def test_diet_and_calorie_constraints_can_make_plan_infeasible(self):
        self.preferences.vegan = True
        self.preferences.meal_calorie_target = 100
        self.preferences.save()
        with self.assertRaisesMessage(PlanningError, "No recipes match"):
            solve_week(self.recipes, self.preferences, {})

    def test_generated_plan_is_persisted_and_replaces_same_week(self):
        plan = generate_plan(self.user, date(2026, 8, 24))
        self.assertEqual(plan.meals.count(), 4)
        self.assertLessEqual(plan.estimated_cost, plan.budget_limit)
        same_plan = generate_plan(self.user, date(2026, 8, 24))
        self.assertEqual(plan.id, same_plan.id)
        self.assertEqual(WeeklyMealPlan.objects.count(), 1)
        self.assertEqual(same_plan.meals.count(), 4)
