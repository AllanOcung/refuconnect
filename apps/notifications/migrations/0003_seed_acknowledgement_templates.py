from django.db import migrations


def seed_acknowledgement_templates(apps, schema_editor):
    MessageTemplate = apps.get_model("notifications", "MessageTemplate")

    templates = [
        (
            "en",
            "Thank you for your feedback (Ref: {reference_id}). We have received it and will review it shortly.",
        ),
        (
            "sw",
            "Asante kwa maoni yako (Ref: {reference_id}). Tumeyapokea na tutayapitia hivi karibuni.",
        ),
        (
            "lg",
            "Webale ku ndowooza yo (Ref: {reference_id}). Tugifunye era tugenda okugyetegereza mangu.",
        ),
        (
            "rw",
            "Murakoze kubw'igitekerezo cyanyu (Ref: {reference_id}). Twacyakiriye kandi tuzagisuzuma vuba.",
        ),
        (
            "ar",
            "شكرا لملاحظاتك (Ref: {reference_id}). لقد استلمناها وسنراجعها قريبا.",
        ),
        (
            "so",
            "Waad ku mahadsantahay fariintaada (Ref: {reference_id}). Waan helnay, dhawaan ayaanna dib u eegi doonaa.",
        ),
        (
            "fr",
            "Merci pour votre retour (Ref: {reference_id}). Nous l'avons bien recu et le traiterons bientot.",
        ),
    ]

    for language, body in templates:
        MessageTemplate.objects.get_or_create(
            template_key="ACKNOWLEDGEMENT",
            language=language,
            defaults={
                "body": body,
                "is_active": True,
                "is_system": True,
            },
        )


def unseed_acknowledgement_templates(apps, schema_editor):
    MessageTemplate = apps.get_model("notifications", "MessageTemplate")
    MessageTemplate.objects.filter(template_key="ACKNOWLEDGEMENT", is_system=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0002_broadcast_messagetemplate_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_acknowledgement_templates, unseed_acknowledgement_templates),
    ]
