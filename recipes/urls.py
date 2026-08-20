# recipes/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('', views.recipe_list, name='recipe_list'),
    path('recipe/<int:id>/', views.recipe_detail, name='recipe_detail'),
    path('add/', views.add_recipe, name='add_recipe'),
    path('signup/', views.signup, name='signup'),
    path('pantry/', views.pantry, name='pantry'),
    path('pantry/<int:item_id>/delete/', views.pantry_delete, name='pantry_delete'),
    path('preferences/', views.preferences, name='preferences'),
    path('plan/', views.meal_plan, name='meal_plan'),
    path('plan/<slug:week_start>/', views.meal_plan_week, name='meal_plan_week'),
]
