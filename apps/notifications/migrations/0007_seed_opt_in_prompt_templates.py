from django.db import migrations


def seed_opt_in_prompt_templates(apps, schema_editor):
    MessageTemplate = apps.get_model("notifications", "MessageTemplate")

    templates = [
        ("en", "Reply YES to receive follow-up messages from us, or NO to decline."),
        ("sw", "Jibu YES kupokea ujumbe wa ufuatiliaji kutoka kwetu, au NO kukataa."),
        ("lg", "Ddamu YES okufuna obubaka bw'okuddamu okuva ewa, oba NO okuggaana."),
        ("rw", "Subiza YES kwakira ubutumwa bw'ibisubizo biva kuri twe, cyangwa NO kwanga."),
        ("ar", "رد بـ YES لتلقي رسائل المتابعة منا، أو NO للرفض."),
        ("so", "Kala jawaab YES si aad u hesho farriimaha raadraaca naga, ama NO si aad u diiday."),
        ("fr", "Répondez OUI pour recevoir des messages de suivi de notre part, ou NON pour refuser."),
    ]

    for language, body in templates:
        MessageTemplate.objects.get_or_create(
            template_key="OPT_IN_PROMPT",
            language=language,
            defaults={"body": body, "is_active": True, "is_system": True},
        )


def unseed_opt_in_prompt_templates(apps, schema_editor):
    MessageTemplate = apps.get_model("notifications", "MessageTemplate")
    MessageTemplate.objects.filter(template_key="OPT_IN_PROMPT", is_system=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0006_seed_consent_templates"),
    ]

    operations = [
        migrations.RunPython(seed_opt_in_prompt_templates, unseed_opt_in_prompt_templates),
    ]
