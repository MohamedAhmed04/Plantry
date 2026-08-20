from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .forms import MealPlanGenerationForm, PreferenceForm
from .models import Ingredient, PantryItem, Recipe, RecipeIngredient, UserPreference, WeeklyMealPlan
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


class FormValidationTests(TestCase):
    def test_week_must_start_on_monday(self):
        form = MealPlanGenerationForm({"week_start": "2026-08-25"})
        self.assertFalse(form.is_valid())
        self.assertIn("must be a Monday", form.errors["week_start"][0])

    def test_budget_and_meal_count_have_bounds(self):
        form = PreferenceForm({
            "weekly_budget": "0", "meals_per_week": 15,
            "meal_calorie_target": 600, "meal_protein_target": 25,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("weekly_budget", form.errors)
        self.assertIn("meals_per_week", form.errors)


class WebFlowTests(RecipeFactoryMixin, TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("webuser", password="testpass123")
        self.preference = UserPreference.objects.create(user=self.user, weekly_budget=20, meals_per_week=3)
        self.rice = Ingredient.objects.create(name="Rice", category="Pantry", unit_price=Decimal("0.01"))
        for i in range(3):
            self.make_recipe(f"Web recipe {i}", self.rice, protein=25 + i)

    def test_discovery_is_public_and_contains_ranked_recipes(self):
        response = self.client.get(reverse("recipe_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Web recipe 0")
        self.assertContains(response, "0% pantry match")

    def test_signup_creates_preferences_and_logs_user_in(self):
        response = self.client.post(reverse("signup"), {"username": "newcook", "password1": "Longpass-2468", "password2": "Longpass-2468"})
        self.assertRedirects(response, reverse("pantry"))
        user = get_user_model().objects.get(username="newcook")
        self.assertTrue(UserPreference.objects.filter(user=user).exists())
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.id)

    def test_pantry_add_updates_existing_row_and_delete_is_user_scoped(self):
        self.client.force_login(self.user)
        self.client.post(reverse("pantry"), {"ingredient": self.rice.id, "quantity": "200"})
        self.client.post(reverse("pantry"), {"ingredient": self.rice.id, "quantity": "300"})
        item = PantryItem.objects.get(user=self.user, ingredient=self.rice)
        self.assertEqual(item.quantity, Decimal("300"))
        other = get_user_model().objects.create_user("other")
        other_item = PantryItem.objects.create(user=other, ingredient=self.rice, quantity=1)
        response = self.client.post(reverse("pantry_delete", args=[other_item.id]))
        self.assertEqual(response.status_code, 404)

    def test_preferences_and_plan_generation_flow(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("preferences"), {
            "weekly_budget": "25", "meals_per_week": "3", "meal_calorie_target": "600",
            "meal_protein_target": "25", "vegetarian": "on",
        })
        self.assertRedirects(response, reverse("preferences"))
        response = self.client.post(reverse("meal_plan"), {"week_start": "2026-08-24"})
        plan = WeeklyMealPlan.objects.get(user=self.user)
        self.assertRedirects(response, reverse("meal_plan_week", kwargs={"week_start": "2026-08-24"}))
        page = self.client.get(reverse("meal_plan_week", kwargs={"week_start": plan.week_start.isoformat()}))
        self.assertContains(page, "Shopping estimate")
        self.assertContains(page, "Meals planned")

    def test_recipe_creation_requires_login_and_normalized_line(self):
        self.assertRedirects(self.client.get(reverse("add_recipe")), f"{reverse('login')}?next={reverse('add_recipe')}")
        self.client.force_login(self.user)
        data = {
            "title": "New recipe", "description": "A useful recipe", "ingredients": "Rice",
            "instructions": "Cook it", "prep_minutes": 10, "servings": 2,
            "calories_per_serving": 400, "protein_grams": 20, "carbs_grams": 50,
            "fat_grams": 10, "is_vegetarian": "on", "is_vegan": "on",
            "is_gluten_free": "on", "is_dairy_free": "on", "is_nut_free": "on",
            "ingredient_lines-TOTAL_FORMS": "4", "ingredient_lines-INITIAL_FORMS": "0",
            "ingredient_lines-MIN_NUM_FORMS": "1", "ingredient_lines-MAX_NUM_FORMS": "1000",
            "ingredient_lines-0-ingredient": self.rice.id, "ingredient_lines-0-quantity": "100",
            "ingredient_lines-0-note": "dry",
        }
        response = self.client.post(reverse("add_recipe"), data)
        recipe = Recipe.objects.get(title="New recipe")
        self.assertRedirects(response, recipe.get_absolute_url())
        self.assertEqual(recipe.ingredient_lines.count(), 1)
