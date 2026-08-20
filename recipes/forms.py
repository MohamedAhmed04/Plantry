from datetime import date, timedelta

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.forms import inlineformset_factory

from .models import Recipe, RecipeIngredient, UserPreference


class BootstrapFormMixin:
    def _bootstrap(self):
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            elif isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs["class"] = "form-control"


class SignUpForm(BootstrapFormMixin, UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bootstrap()


class RecipeForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Recipe
        fields = [
            "title", "description", "ingredients", "instructions", "image_url",
            "prep_minutes", "servings", "calories_per_serving", "protein_grams",
            "carbs_grams", "fat_grams", "is_vegetarian", "is_vegan",
            "is_gluten_free", "is_dairy_free", "is_nut_free",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "ingredients": forms.Textarea(attrs={"rows": 5}),
            "instructions": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bootstrap()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_vegan"):
            cleaned["is_vegetarian"] = True
            cleaned["is_dairy_free"] = True
        return cleaned


class RecipeIngredientForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = RecipeIngredient
        fields = ("ingredient", "quantity", "note")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bootstrap()


RecipeIngredientFormSet = inlineformset_factory(
    Recipe, RecipeIngredient, form=RecipeIngredientForm, extra=4,
    min_num=1, validate_min=True, can_delete=True,
)


class PantryItemForm(BootstrapFormMixin, forms.Form):
    ingredient = forms.ModelChoiceField(queryset=None)
    quantity = forms.DecimalField(min_value=0.01, max_digits=9, decimal_places=2)

    def __init__(self, *args, **kwargs):
        from .models import Ingredient

        super().__init__(*args, **kwargs)
        self.fields["ingredient"].queryset = Ingredient.objects.all()
        self._bootstrap()


class PreferenceForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = [
            "weekly_budget", "meals_per_week", "meal_calorie_target", "meal_protein_target",
            "vegetarian", "vegan", "gluten_allergy", "dairy_allergy", "nut_allergy",
            "excluded_ingredients",
        ]
        widgets = {"excluded_ingredients": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bootstrap()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("vegan"):
            cleaned["vegetarian"] = True
        return cleaned


class RecipeFilterForm(BootstrapFormMixin, forms.Form):
    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Recipe or ingredient"}))
    min_overlap = forms.IntegerField(required=False, min_value=0, max_value=100, label="Minimum pantry match %")
    max_missing_cost = forms.DecimalField(required=False, min_value=0, max_digits=8, decimal_places=2, label="Maximum to buy / serving")
    compatible_only = forms.BooleanField(required=False, initial=True, label="Only recipes matching my constraints")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bootstrap()


def next_monday():
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)


class MealPlanGenerationForm(BootstrapFormMixin, forms.Form):
    week_start = forms.DateField(initial=next_monday, widget=forms.DateInput(attrs={"type": "date"}), help_text="Choose the Monday for this plan.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bootstrap()

    def clean_week_start(self):
        value = self.cleaned_data["week_start"]
        if value.weekday() != 0:
            raise forms.ValidationError("Week start must be a Monday.")
        return value
