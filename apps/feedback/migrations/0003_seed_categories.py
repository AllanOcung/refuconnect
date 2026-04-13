"""Seed Category lookup table with 11 standard humanitarian categories."""
from django.db import migrations

CATEGORIES = [
    (
        "Food Security",
        "Issues related to food access, nutrition, and food distribution.",
    ),
    (
        "Healthcare",
        "Medical services, health facility access, medicine availability, and health emergencies.",
    ),
    (
        "Shelter & Housing",
        "Accommodation conditions, settlement infrastructure, and non-food item distribution.",
    ),
    (
        "Water & Sanitation",
        "Clean water access, hygiene promotion, and WASH (Water, Sanitation, Hygiene) services.",
    ),
    (
        "Education",
        "School access, learning materials, teacher availability, and child education programs.",
    ),
    (
        "Protection & Safety",
        "Gender-based violence, child protection, physical security concerns, and exploitation reports.",
    ),
    (
        "Livelihoods & Employment",
        "Income generation opportunities, vocational training, and economic empowerment programs.",
    ),
    (
        "Legal Aid & Documentation",
        "Refugee status determination, registration, documentation, and legal rights.",
    ),
    (
        "Psychosocial Support",
        "Mental health services, trauma counselling, and community social support.",
    ),
    (
        "Infrastructure",
        "Roads, electricity, internet connectivity, and general camp or settlement infrastructure.",
    ),
    (
        "General Feedback",
        "Feedback that does not fit into a specific thematic category.",
    ),
]


def seed_categories(apps, schema_editor):
    Category = apps.get_model("feedback", "Category")
    for name, description in CATEGORIES:
        Category.objects.get_or_create(
            category_name=name,
            defaults={"description": description, "is_active": True},
        )


def reverse_seed_categories(apps, schema_editor):
    Category = apps.get_model("feedback", "Category")
    Category.objects.filter(category_name__in=[c[0] for c in CATEGORIES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("feedback", "0002_seed_sentiments"),
    ]

    operations = [
        migrations.RunPython(seed_categories, reverse_seed_categories),
    ]
