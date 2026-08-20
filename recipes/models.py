from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse


class Ingredient(models.Model):
    class Unit(models.TextChoices):
        GRAM = "g", "grams"
        MILLILITER = "ml", "milliliters"
        ITEM = "item", "items"
        TABLESPOON = "tbsp", "tablespoons"

    name = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=60, blank=True)
    unit = models.CharField(max_length=12, choices=Unit.choices, default=Unit.GRAM)
    unit_price = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("0.0000"), help_text="Estimated price per canonical unit.")
    contains_gluten = models.BooleanField(default=False)
    contains_dairy = models.BooleanField(default=False)
    contains_nuts = models.BooleanField(default=False)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Recipe(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(help_text="A short description of the recipe")
    ingredients = models.TextField(help_text="Human-readable ingredient list", blank=True)
    instructions = models.TextField(help_text="Step-by-step instructions")
    image_url = models.URLField(blank=True, null=True, help_text="URL of an image for the recipe")
    prep_minutes = models.PositiveSmallIntegerField(default=30)
    servings = models.PositiveSmallIntegerField(default=4, validators=[MinValueValidator(1)])
    calories_per_serving = models.PositiveSmallIntegerField(default=500)
    protein_grams = models.DecimalField(max_digits=6, decimal_places=1, default=Decimal("20.0"))
    carbs_grams = models.DecimalField(max_digits=6, decimal_places=1, default=Decimal("40.0"))
    fat_grams = models.DecimalField(max_digits=6, decimal_places=1, default=Decimal("15.0"))
    is_vegetarian = models.BooleanField(default=False)
    is_vegan = models.BooleanField(default=False)
    is_gluten_free = models.BooleanField(default=False)
    is_dairy_free = models.BooleanField(default=False)
    is_nut_free = models.BooleanField(default=True)
    normalized_ingredients = models.ManyToManyField(Ingredient, through="RecipeIngredient", related_name="recipes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("title",)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("recipe_detail", args=[str(self.id)])

    @property
    def estimated_cost(self):
        total = sum((line.quantity * line.ingredient.unit_price for line in self.ingredient_lines.select_related("ingredient")), Decimal("0.00"))
        return total.quantize(Decimal("0.01"))

    @property
    def cost_per_serving(self):
        return (self.estimated_cost / self.servings).quantize(Decimal("0.01"))

    @property
    def dietary_labels(self):
        labels = []
        if self.is_vegan:
            labels.append("Vegan")
        elif self.is_vegetarian:
            labels.append("Vegetarian")
        if self.is_gluten_free:
            labels.append("Gluten-free")
        if self.is_dairy_free:
            labels.append("Dairy-free")
        if self.is_nut_free:
            labels.append("Nut-free")
        return labels


class RecipeIngredient(models.Model):
    recipe = models.ForeignKey(Recipe, related_name="ingredient_lines", on_delete=models.CASCADE)
    ingredient = models.ForeignKey(Ingredient, related_name="recipe_lines", on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=9, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))], help_text="Quantity for the full recipe in the ingredient's canonical unit.")
    note = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ("id",)
        constraints = [models.UniqueConstraint(fields=("recipe", "ingredient"), name="unique_recipe_ingredient")]

    def __str__(self):
        return f"{self.quantity} {self.ingredient.unit} {self.ingredient}"


class UserPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, related_name="meal_preferences", on_delete=models.CASCADE)
    weekly_budget = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("70.00"), validators=[MinValueValidator(Decimal("1.00"))])
    meals_per_week = models.PositiveSmallIntegerField(default=7, validators=[MinValueValidator(1), MaxValueValidator(14)])
    meal_calorie_target = models.PositiveSmallIntegerField(default=600, validators=[MinValueValidator(100), MaxValueValidator(2000)])
    meal_protein_target = models.PositiveSmallIntegerField(default=25, validators=[MinValueValidator(0), MaxValueValidator(200)])
    vegetarian = models.BooleanField(default=False)
    vegan = models.BooleanField(default=False)
    gluten_allergy = models.BooleanField(default=False)
    dairy_allergy = models.BooleanField(default=False)
    nut_allergy = models.BooleanField(default=False)
    excluded_ingredients = models.ManyToManyField(Ingredient, blank=True, related_name="excluded_by")

    def __str__(self):
        return f"Preferences for {self.user}"

    def save(self, *args, **kwargs):
        if self.vegan:
            self.vegetarian = True
        super().save(*args, **kwargs)


class PantryItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="pantry_items", on_delete=models.CASCADE)
    ingredient = models.ForeignKey(Ingredient, related_name="pantry_items", on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=9, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("ingredient__name",)
        constraints = [models.UniqueConstraint(fields=("user", "ingredient"), name="unique_user_pantry_item")]

    def __str__(self):
        return f"{self.ingredient}: {self.quantity} {self.ingredient.unit}"


class WeeklyMealPlan(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="meal_plans", on_delete=models.CASCADE)
    week_start = models.DateField()
    budget_limit = models.DecimalField(max_digits=8, decimal_places=2)
    estimated_cost = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    average_pantry_overlap = models.PositiveSmallIntegerField(default=0)
    generated_at = models.DateTimeField(auto_now=True)
    solver_summary = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-week_start", "-generated_at")
        constraints = [models.UniqueConstraint(fields=("user", "week_start"), name="unique_user_plan_week")]

    def __str__(self):
        return f"{self.user}'s plan for {self.week_start}"


class PlannedMeal(models.Model):
    class Slot(models.TextChoices):
        LUNCH = "lunch", "Lunch"
        DINNER = "dinner", "Dinner"

    plan = models.ForeignKey(WeeklyMealPlan, related_name="meals", on_delete=models.CASCADE)
    day_index = models.PositiveSmallIntegerField(validators=[MaxValueValidator(6)])
    slot = models.CharField(max_length=10, choices=Slot.choices, default=Slot.DINNER)
    recipe = models.ForeignKey(Recipe, related_name="planned_meals", on_delete=models.PROTECT)
    estimated_cost = models.DecimalField(max_digits=8, decimal_places=2)
    pantry_overlap = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("day_index", "slot")
        constraints = [models.UniqueConstraint(fields=("plan", "day_index", "slot"), name="unique_plan_day_slot")]

    def __str__(self):
        return f"{self.get_slot_display()} day {self.day_index + 1}: {self.recipe}"
