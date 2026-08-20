from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from .forms import (
    MealPlanGenerationForm,
    PantryItemForm,
    PreferenceForm,
    RecipeFilterForm,
    RecipeForm,
    RecipeIngredientFormSet,
    SignUpForm,
)
from .models import PantryItem, Recipe, UserPreference, WeeklyMealPlan
from .services import PlanningError, generate_plan, pantry_snapshot, rank_recipes, recipe_metrics


def _preferences_for(request):
    if request.user.is_authenticated:
        return UserPreference.objects.get_or_create(user=request.user)[0]
    preferences = UserPreference()
    preferences._excluded_ids = set()
    return preferences


def recipe_list(request):
    recipes = Recipe.objects.prefetch_related("ingredient_lines__ingredient")
    data = request.GET if request.GET else {"compatible_only": "on"}
    form = RecipeFilterForm(data)
    preferences = _preferences_for(request)
    pantry = pantry_snapshot(request.user) if request.user.is_authenticated else {}
    if form.is_valid() and form.cleaned_data["q"]:
        query = form.cleaned_data["q"]
        recipes = recipes.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(normalized_ingredients__name__icontains=query)).distinct()
    ranked = rank_recipes(recipes, preferences, pantry)
    if form.is_valid():
        minimum = form.cleaned_data.get("min_overlap")
        maximum = form.cleaned_data.get("max_missing_cost")
        if form.cleaned_data.get("compatible_only"):
            ranked = [item for item in ranked if item["compatible"]]
        if minimum is not None:
            ranked = [item for item in ranked if item["pantry_overlap"] >= minimum]
        if maximum is not None:
            ranked = [item for item in ranked if item["missing_cost"] <= maximum]
    return render(request, "recipes/recipe_list.html", {"ranked_recipes": ranked, "filter_form": form})


def recipe_detail(request, id):
    recipe = get_object_or_404(Recipe.objects.prefetch_related("ingredient_lines__ingredient"), id=id)
    pantry = pantry_snapshot(request.user) if request.user.is_authenticated else {}
    return render(request, "recipes/recipe_detail.html", {"recipe": recipe, "metrics": recipe_metrics(recipe, pantry)})


@login_required
@transaction.atomic
def add_recipe(request):
    recipe = Recipe()
    if request.method == "POST":
        form = RecipeForm(request.POST, instance=recipe)
        formset = RecipeIngredientFormSet(request.POST, instance=recipe)
        if form.is_valid() and formset.is_valid():
            recipe = form.save()
            formset.instance = recipe
            formset.save()
            messages.success(request, "Recipe added to the discovery catalog.")
            return redirect(recipe.get_absolute_url())
    else:
        form = RecipeForm(instance=recipe)
        formset = RecipeIngredientFormSet(instance=recipe)
    return render(request, "recipes/add_recipe.html", {"form": form, "formset": formset})


def signup(request):
    if request.user.is_authenticated:
        return redirect("recipe_list")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        UserPreference.objects.create(user=user)
        login(request, user)
        messages.success(request, "Welcome! Add your pantry to unlock personalized ranking.")
        return redirect("pantry")
    return render(request, "registration/signup.html", {"form": form})


@login_required
def pantry(request):
    if request.method == "POST":
        form = PantryItemForm(request.POST)
        if form.is_valid():
            item, created = PantryItem.objects.update_or_create(
                user=request.user,
                ingredient=form.cleaned_data["ingredient"],
                defaults={"quantity": form.cleaned_data["quantity"]},
            )
            messages.success(request, f"{'Added' if created else 'Updated'} {item.ingredient.name}.")
            return redirect("pantry")
    else:
        form = PantryItemForm()
    items = request.user.pantry_items.select_related("ingredient")
    pantry_value = sum((item.quantity * item.ingredient.unit_price for item in items), Decimal("0")).quantize(Decimal("0.01"))
    return render(request, "recipes/pantry.html", {"form": form, "items": items, "pantry_value": pantry_value})


@login_required
def pantry_delete(request, item_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    item = get_object_or_404(PantryItem, id=item_id, user=request.user)
    name = item.ingredient.name
    item.delete()
    messages.info(request, f"Removed {name} from your pantry.")
    return redirect("pantry")


@login_required
def preferences(request):
    instance, _ = UserPreference.objects.get_or_create(user=request.user)
    form = PreferenceForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Planning constraints saved.")
        return redirect("preferences")
    return render(request, "recipes/preferences.html", {"form": form})


@login_required
def meal_plan(request):
    form = MealPlanGenerationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            plan = generate_plan(request.user, form.cleaned_data["week_start"])
        except PlanningError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Your constraint-aware plan is ready.")
            return redirect("meal_plan_week", week_start=plan.week_start.isoformat())
    plan = request.user.meal_plans.prefetch_related("meals__recipe").first()
    return _render_plan(request, form, plan)


@login_required
def meal_plan_week(request, week_start):
    plan = get_object_or_404(WeeklyMealPlan.objects.prefetch_related("meals__recipe"), user=request.user, week_start=week_start)
    return _render_plan(request, MealPlanGenerationForm(initial={"week_start": plan.week_start}), plan)


def _render_plan(request, form, plan):
    days = []
    if plan:
        meals = list(plan.meals.select_related("recipe").order_by("day_index", "-slot"))
        for index in range(7):
            days.append({"date": plan.week_start + timedelta(days=index), "meals": [meal for meal in meals if meal.day_index == index]})
    return render(request, "recipes/meal_plan.html", {"form": form, "plan": plan, "days": days})
