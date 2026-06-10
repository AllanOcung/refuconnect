from django.db import migrations


def seed_consent_templates(apps, schema_editor):
    MessageTemplate = apps.get_model("notifications", "MessageTemplate")

    opt_in_templates = [
        ("en", "You have opted in to receive follow-up messages. Reply NO at any time to stop."),
        ("sw", "Umekubaliana kupokea ujumbe wa ufuatiliaji. Jibu NO wakati wowote kuacha."),
        ("lg", "Wakkiridde okufuna obubaka bw'okuddamu. Ddamu NO nga buli lw'oyagala okuvaamu."),
        ("rw", "Wemeye kwakira ubutumwa bw'ibisubizo. Subiza NO igihe icyo aricyo cyose guhagarika."),
        ("ar", "لقد اشتركت في تلقي رسائل المتابعة. رد بـ NO في أي وقت للإلغاء."),
        ("so", "Waxaad aqbashay inaa hesho farriimaha raadraaca. Kala jawaab NO mar kasta si aad uga baxdo."),
        ("fr", "Vous avez accepté de recevoir des messages de suivi. Répondez NON à tout moment pour vous désabonner."),
    ]

    opt_out_templates = [
        ("en", "You have been unsubscribed. You will no longer receive follow-up messages from us."),
        ("sw", "Umejitoa. Hutapokea tena ujumbe wa ufuatiliaji kutoka kwetu."),
        ("lg", "Ovaako. Tolirinda kufuna bubaka bw'okuddamu okuva ewa."),
        ("rw", "Usubisemo. Ntuzakira ubutumwa bw'ibisubizo biva kuri twe."),
        ("ar", "تم إلغاء اشتراكك. لن تتلقى بعد الآن رسائل متابعة منا."),
        ("so", "Waxaa lagaaga tirtiray. Waxba kuma heli doonto farriimaha raadraaca naga."),
        ("fr", "Vous avez été désabonné. Vous ne recevrez plus de messages de suivi de notre part."),
    ]

    for language, body in opt_in_templates:
        MessageTemplate.objects.get_or_create(
            template_key="OPT_IN_CONFIRMATION",
            language=language,
            defaults={"body": body, "is_active": True, "is_system": True},
        )

    for language, body in opt_out_templates:
        MessageTemplate.objects.get_or_create(
            template_key="OPT_OUT_CONFIRMATION",
            language=language,
            defaults={"body": body, "is_active": True, "is_system": True},
        )


def unseed_consent_templates(apps, schema_editor):
    MessageTemplate = apps.get_model("notifications", "MessageTemplate")
    MessageTemplate.objects.filter(
        template_key__in=("OPT_IN_CONFIRMATION", "OPT_OUT_CONFIRMATION"),
        is_system=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0005_fix_userconsent_db_table"),
    ]

    operations = [
        migrations.RunPython(seed_consent_templates, unseed_consent_templates),
    ]
