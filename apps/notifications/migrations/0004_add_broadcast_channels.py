from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0003_seed_acknowledgement_templates"),
    ]

    operations = [
        migrations.AddField(
            model_name="broadcast",
            name="channels",
            field=models.JSONField(
                default=list,
                help_text=(
                    "List of channels to send on, e.g. ['SMS', 'WhatsApp']. "
                    "Recipients are sent on their preferred channel if it appears here, "
                    "otherwise on the first channel in this list."
                ),
            ),
        ),
    ]
