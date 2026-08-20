from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from recipes.models import Ingredient, PantryItem, Recipe, RecipeIngredient, UserPreference


class Command(BaseCommand):
    help = "Load an idempotent recipe catalog and optional demo account."

    @transaction.atomic
    def handle(self, *args, **options):
        ingredients = {}
        source = [
            ("Avocado", "Produce", "item", ".90", False, False, False),
            ("Bell pepper", "Produce", "item", "1.10", False, False, False),
            ("Black beans", "Pantry", "g", ".004", False, False, False),
            ("Broccoli", "Produce", "g", ".006", False, False, False),
            ("Chicken breast", "Protein", "g", ".014", False, False, False),
            ("Chickpeas", "Pantry", "g", ".004", False, False, False),
            ("Coconut milk", "Pantry", "ml", ".006", False, False, False),
            ("Corn tortillas", "Bakery", "item", ".30", False, False, False),
            ("Eggs", "Protein", "item", ".35", False, False, False),
            ("Greek yogurt", "Dairy", "g", ".009", False, True, False),
            ("Lemon", "Produce", "item", ".65", False, False, False),
            ("Lentils", "Pantry", "g", ".004", False, False, False),
            ("Olive oil", "Pantry", "tbsp", ".22", False, False, False),
            ("Pasta", "Pantry", "g", ".005", True, False, False),
            ("Peanut butter", "Pantry", "g", ".012", False, False, True),
            ("Quinoa", "Pantry", "g", ".009", False, False, False),
            ("Rice", "Pantry", "g", ".004", False, False, False),
            ("Salmon", "Protein", "g", ".026", False, False, False),
            ("Spinach", "Produce", "g", ".012", False, False, False),
            ("Sweet potato", "Produce", "g", ".004", False, False, False),
            ("Tofu", "Protein", "g", ".008", False, False, False),
            ("Tomato", "Produce", "g", ".006", False, False, False),
        ]
        for name, category, unit, price, gluten, dairy, nuts in source:
            ingredient, _ = Ingredient.objects.update_or_create(
                name=name,
                defaults={"category": category, "unit": unit, "unit_price": Decimal(price), "contains_gluten": gluten, "contains_dairy": dairy, "contains_nuts": nuts},
            )
            ingredients[name] = ingredient

        recipes = [
            {"title": "Lemony chickpea quinoa", "description": "Bright herbs, crisp vegetables, and a lemony quinoa base.", "prep_minutes": 25, "calories": 510, "protein": "20", "carbs": "74", "fat": "15", "flags": (True, True, True, True, True), "lines": [("Quinoa", 240), ("Chickpeas", 320), ("Spinach", 120), ("Lemon", 1), ("Olive oil", 2)]},
            {"title": "Crispy tofu rice bowl", "description": "Golden tofu and broccoli over rice with a punchy citrus finish.", "prep_minutes": 35, "calories": 590, "protein": "29", "carbs": "78", "fat": "19", "flags": (True, True, True, True, True), "lines": [("Tofu", 500), ("Rice", 260), ("Broccoli", 360), ("Lemon", 1), ("Olive oil", 2)]},
            {"title": "Smoky black bean tacos", "description": "Weeknight tacos layered with smoky beans, peppers, and avocado.", "prep_minutes": 20, "calories": 540, "protein": "21", "carbs": "79", "fat": "17", "flags": (True, True, True, True, True), "lines": [("Black beans", 420), ("Corn tortillas", 8), ("Bell pepper", 2), ("Avocado", 1), ("Tomato", 200)]},
            {"title": "Red lentil coconut curry", "description": "A deeply comforting pantry curry with spinach and coconut milk.", "prep_minutes": 40, "calories": 570, "protein": "24", "carbs": "73", "fat": "20", "flags": (True, True, True, True, True), "lines": [("Lentils", 320), ("Coconut milk", 400), ("Spinach", 160), ("Rice", 240), ("Tomato", 300)]},
            {"title": "Herby chicken grain bowl", "description": "Lean chicken, quinoa, greens, and cool lemon yogurt.", "prep_minutes": 35, "calories": 620, "protein": "48", "carbs": "57", "fat": "20", "flags": (False, False, True, False, True), "lines": [("Chicken breast", 600), ("Quinoa", 240), ("Spinach", 120), ("Greek yogurt", 180), ("Lemon", 1)]},
            {"title": "Salmon & sweet potato traybake", "description": "A hands-off traybake with flaky salmon and caramelized vegetables.", "prep_minutes": 45, "calories": 640, "protein": "42", "carbs": "52", "fat": "27", "flags": (False, False, True, True, True), "lines": [("Salmon", 600), ("Sweet potato", 700), ("Broccoli", 360), ("Olive oil", 2)]},
            {"title": "Tomato spinach pasta", "description": "Silky tomato pasta finished with plenty of wilted spinach.", "prep_minutes": 25, "calories": 580, "protein": "22", "carbs": "92", "fat": "13", "flags": (True, True, False, True, True), "lines": [("Pasta", 400), ("Tomato", 500), ("Spinach", 160), ("Olive oil", 3)]},
            {"title": "Peanut tofu crunch bowl", "description": "Creamy peanut tofu with crisp peppers and fluffy rice.", "prep_minutes": 30, "calories": 650, "protein": "31", "carbs": "76", "fat": "27", "flags": (True, True, True, True, False), "lines": [("Tofu", 500), ("Peanut butter", 100), ("Rice", 260), ("Bell pepper", 2)]},
            {"title": "Green vegetable frittata", "description": "Protein-rich eggs baked with broccoli, spinach, and peppers.", "prep_minutes": 30, "calories": 430, "protein": "30", "carbs": "18", "fat": "26", "flags": (True, False, True, True, True), "lines": [("Eggs", 8), ("Broccoli", 250), ("Spinach", 120), ("Bell pepper", 1)]},
        ]
        for data in recipes:
            vegetarian, vegan, gluten_free, dairy_free, nut_free = data["flags"]
            recipe, _ = Recipe.objects.update_or_create(
                title=data["title"],
                defaults={
                    "description": data["description"],
                    "ingredients": "\n".join(f"{quantity} {ingredients[name].unit} {name}" for name, quantity in data["lines"]),
                    "instructions": "Prepare all ingredients.\nCook the grains or protein until tender.\nCombine, season to taste, and serve warm.",
                    "prep_minutes": data["prep_minutes"], "servings": 4,
                    "calories_per_serving": data["calories"], "protein_grams": Decimal(data["protein"]),
                    "carbs_grams": Decimal(data["carbs"]), "fat_grams": Decimal(data["fat"]),
                    "is_vegetarian": vegetarian, "is_vegan": vegan, "is_gluten_free": gluten_free,
                    "is_dairy_free": dairy_free, "is_nut_free": nut_free,
                },
            )
            recipe.ingredient_lines.all().delete()
            RecipeIngredient.objects.bulk_create([RecipeIngredient(recipe=recipe, ingredient=ingredients[name], quantity=quantity) for name, quantity in data["lines"]])

        User = get_user_model()
        user, created = User.objects.get_or_create(username="demo")
        if created:
            user.set_password("Plantry123!")
            user.save()
        preference, _ = UserPreference.objects.get_or_create(user=user)
        preference.weekly_budget = Decimal("55.00")
        preference.meals_per_week = 7
        preference.meal_calorie_target = 600
        preference.meal_protein_target = 25
        preference.save()
        for name, quantity in (("Rice", 500), ("Chickpeas", 400), ("Spinach", 200), ("Olive oil", 8), ("Lemon", 2), ("Black beans", 300)):
            PantryItem.objects.update_or_create(user=user, ingredient=ingredients[name], defaults={"quantity": quantity})
        self.stdout.write(self.style.SUCCESS(f"Loaded {len(ingredients)} ingredients, {len(recipes)} recipes, and demo user."))
