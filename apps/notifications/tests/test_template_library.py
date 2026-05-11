"""
tests/test_template_library.py
"""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from django.test import TestCase
from apps.notifications.models import MessageTemplate
from apps.notifications.services.template_library import TemplateLibrary
from apps.common.exceptions import TemplateNotFoundError


def make_template(key="TEST_TEMPLATE", language="en", body="Hello {reference_id}", is_system=True):
    return MessageTemplate.objects.create(
        template_key=key, language=language, body=body,
        is_active=True, is_system=is_system,
    )


class TestTemplateLibraryGet(TestCase):
    def setUp(self):
        TemplateLibrary._memory_cache.clear()
        self.template_key = "TEST_TEMPLATE"

    def test_get_returns_correct_template_for_language(self):
        tmpl = make_template(key=self.template_key, language="sw", body="Asante {reference_id}")
        lib = TemplateLibrary()
        result = lib.get(self.template_key, "sw")
        self.assertEqual(result.pk, tmpl.pk)

    def test_get_falls_back_to_english_if_language_not_found(self):
        en_tmpl = make_template(key=self.template_key, language="en", body="Thanks {reference_id}")
        lib = TemplateLibrary()
        result = lib.get(self.template_key, "xx")  # unknown language
        self.assertEqual(result.language, "en")

    def test_get_raises_exception_if_english_also_missing(self):
        lib = TemplateLibrary()
        with self.assertRaises(TemplateNotFoundError):
            lib.get("NONEXISTENT_KEY", "en")

    def test_result_is_cached_after_first_db_query(self):
        make_template(key=self.template_key)
        lib = TemplateLibrary()
        with self.assertNumQueries(1):
            lib.get(self.template_key, "en")
        with self.assertNumQueries(0):
            lib.get(self.template_key, "en")  # served from memory cache

    def test_cache_invalidated_after_template_update(self):
        make_template(key=self.template_key)
        lib = TemplateLibrary()
        lib.get(self.template_key, "en")
        lib.invalidate_cache(self.template_key, "en")
        # Cache should be empty now
        self.assertNotIn(f"tmpl:{self.template_key}:en", lib._memory_cache)

    def test_render_substitutes_all_variables(self):
        tmpl = make_template(key=self.template_key, body="Hi {reference_id} in {location}")
        lib = TemplateLibrary()
        result = lib.render(tmpl, {"reference_id": "RFC-001", "location": "Bidibidi"})
        self.assertEqual(result, "Hi RFC-001 in Bidibidi")

    def test_render_logs_warning_for_unreplaced_variables(self):
        tmpl = make_template(key=self.template_key, body="Hello {reference_id} and {unknown_var}")
        lib = TemplateLibrary()
        with self.assertLogs("apps.notifications.template_library", level="WARNING") as cm:
            lib.render(tmpl, {"reference_id": "RFC-001"})
        self.assertTrue(any("unknown_var" in msg for msg in cm.output))

    def test_system_templates_cannot_be_deleted_via_admin(self):
        tmpl = make_template(key=self.template_key, is_system=True)
        # Simulate the admin delete permission check
        from apps.notifications.admin import MessageTemplateAdmin
        from django.contrib.admin.sites import AdminSite
        ma = MessageTemplateAdmin(MessageTemplate, AdminSite())
        self.assertFalse(ma.has_delete_permission(MagicMock(), tmpl))