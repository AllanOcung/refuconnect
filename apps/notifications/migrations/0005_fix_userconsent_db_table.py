"""
State-only migration: tell Django the UserConsent table lives at
consent_schema.user_consent (schema-qualified).

The table was created correctly by 0001_initial (CREATE SCHEMA + CREATE TABLE
landed the row in consent_schema.user_consent), but the model's db_table
string was a flat name ("consent_schema_user_consent") that Django could not
resolve.  No physical rename is needed — only the ORM metadata is updated.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0004_add_broadcast_channels"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterModelTable(
                    name="userconsent",
                    table='"consent_schema"."user_consent"',
                ),
            ],
            database_operations=[],  # table already at consent_schema.user_consent
        ),
    ]
