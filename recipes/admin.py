from django.contrib import admin

from .models import Ingredient, PantryItem, PlannedMeal, Recipe, RecipeIngredient, UserPreference, WeeklyMealPlan


class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    extra = 1


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ("title", "prep_minutes", "calories_per_serving", "is_vegetarian", "is_gluten_free")
    list_filter = ("is_vegetarian", "is_vegan", "is_gluten_free", "is_dairy_free", "is_nut_free")
    search_fields = ("title", "description")
    inlines = (RecipeIngredientInline,)


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "unit", "unit_price")
    list_filter = ("category", "contains_gluten", "contains_dairy", "contains_nuts")
    search_fields = ("name",)


admin.site.register(PantryItem)
admin.site.register(UserPreference)
admin.site.register(WeeklyMealPlan)
admin.site.register(PlannedMeal)
