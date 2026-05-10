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


def make_template(key="ACKNOWLEDGEMENT", language="en", body="Hello {reference_id}", is_system=True):
    return MessageTemplate.objects.create(
        template_key=key, language=language, body=body,
        is_active=True, is_system=is_system,
    )


class TestTemplateLibraryGet(TestCase):
    def setUp(self):
        TemplateLibrary._memory_cache.clear()

    def test_get_returns_correct_template_for_language(self):
        tmpl = make_template(language="sw", body="Asante {reference_id}")
        lib = TemplateLibrary()
        result = lib.get("ACKNOWLEDGEMENT", "sw")
        self.assertEqual(result.pk, tmpl.pk)

    def test_get_falls_back_to_english_if_language_not_found(self):
        en_tmpl = make_template(language="en", body="Thanks {reference_id}")
        lib = TemplateLibrary()
        result = lib.get("ACKNOWLEDGEMENT", "xx")  # unknown language
        self.assertEqual(result.language, "en")

    def test_get_raises_exception_if_english_also_missing(self):
        lib = TemplateLibrary()
        with self.assertRaises(TemplateNotFoundError):
            lib.get("NONEXISTENT_KEY", "en")

    def test_result_is_cached_after_first_db_query(self):
        make_template()
        lib = TemplateLibrary()
        with self.assertNumQueries(1):
            lib.get("ACKNOWLEDGEMENT", "en")
        with self.assertNumQueries(0):
            lib.get("ACKNOWLEDGEMENT", "en")  # served from memory cache

    def test_cache_invalidated_after_template_update(self):
        make_template()
        lib = TemplateLibrary()
        lib.get("ACKNOWLEDGEMENT", "en")
        lib.invalidate_cache("ACKNOWLEDGEMENT", "en")
        # Cache should be empty now
        self.assertNotIn("tmpl:ACKNOWLEDGEMENT:en", lib._memory_cache)

    def test_render_substitutes_all_variables(self):
        tmpl = make_template(body="Hi {reference_id} in {location}")
        lib = TemplateLibrary()
        result = lib.render(tmpl, {"reference_id": "RFC-001", "location": "Bidibidi"})
        self.assertEqual(result, "Hi RFC-001 in Bidibidi")

    def test_render_logs_warning_for_unreplaced_variables(self):
        tmpl = make_template(body="Hello {reference_id} and {unknown_var}")
        lib = TemplateLibrary()
        with self.assertLogs("apps.notifications.template_library", level="WARNING") as cm:
            lib.render(tmpl, {"reference_id": "RFC-001"})
        self.assertTrue(any("unknown_var" in msg for msg in cm.output))

    def test_system_templates_cannot_be_deleted_via_admin(self):
        tmpl = make_template(is_system=True)
        # Simulate the admin delete permission check
        from apps.notifications.admin import MessageTemplateAdmin
        from django.contrib.admin.sites import AdminSite
        ma = MessageTemplateAdmin(MessageTemplate, AdminSite())
        self.assertFalse(ma.has_delete_permission(MagicMock(), tmpl))