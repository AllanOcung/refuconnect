"""
C-22: TemplateLibrary
=====================
Service class that retrieves, renders, and manages message templates.
Uses a two-level cache: in-memory Python dict (TTL=300s) backed by Redis.

Build order note: Build this first — every other service depends on it.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

from django.core.cache import cache

from apps.common.exceptions import TemplateNotFoundError
from apps.notifications.models import MessageTemplate

logger = logging.getLogger("apps.notifications.template_library")

_CACHE_TTL = 300  # seconds


class TemplateLibrary:
    """
    Retrieves and renders multilingual MessageTemplate records.

    In-memory cache is a class-level dict so it is shared across all instances
    within the same worker process. Redis provides cross-worker persistence.
    """

    # Class-level in-memory cache: key -> (MessageTemplate, expiry_timestamp)
    _memory_cache: dict[str, tuple[MessageTemplate, float]] = {}

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get(self, template_key: str, language: str) -> MessageTemplate:
        """
        Retrieve a MessageTemplate by key and language.

        Lookup order:
          1. In-memory cache (TTL=300s)
          2. Redis cache (TTL=300s)
          3. Database query
          4. Fall back to English if requested language not found
          5. Raise TemplateNotFoundError if English is also missing
        """
        cache_key = f"tmpl:{template_key}:{language}"

        # 1. In-memory
        template = self._get_from_memory(cache_key)
        if template is not None:
            return template

        # 2. Redis
        template = self._get_from_redis(cache_key)
        if template is not None:
            self._store_in_memory(cache_key, template)
            return template

        # 3. Database
        template = self._get_from_db(template_key, language)
        if template is not None:
            self._store_in_memory(cache_key, template)
            self._store_in_redis(cache_key, template)
            return template

        # 4. Fallback to English
        if language != "en":
            logger.warning(
                "TemplateLibrary: template '%s' not found for language '%s', "
                "falling back to English.",
                template_key,
                language,
            )
            return self.get(template_key, "en")

        # 5. Not found at all
        raise TemplateNotFoundError(
            f"Template '{template_key}' not found for language '{language}' "
            f"or fallback 'en'."
        )

    def render(self, template: MessageTemplate, variables: dict) -> str:
        """
        Replace {variable} placeholders in template body with provided values.
        Logs a warning if any placeholders remain unreplaced after substitution.
        """
        result = template.body
        for key, value in variables.items():
            result = result.replace(f"{{{key}}}", str(value))

        unreplaced = re.findall(r"\{[a-z_]+\}", result)
        if unreplaced:
            logger.warning(
                "TemplateLibrary: Unreplaced variables in template '%s': %s",
                template.template_key,
                unreplaced,
            )
        return result

    def get_and_render(
        self, template_key: str, language: str, variables: dict
    ) -> str:
        """
        Convenience method: get() then render().
        Used by MessageRouter for acknowledgements and ConsentManager confirmations.
        """
        template = self.get(template_key, language)
        return self.render(template, variables)

    def invalidate_cache(
        self,
        template_key: Optional[str] = None,
        language: Optional[str] = None,
    ) -> None:
        """
        Invalidate cached templates.

        - Both args: invalidate that specific entry.
        - Only template_key: invalidate all languages for that key.
        - Neither: invalidate all template caches.

        Called by admin CRUD views after any template write operation.
        """
        if template_key and language:
            self._evict(f"tmpl:{template_key}:{language}")
        elif template_key:
            keys_to_evict = [
                k for k in list(self._memory_cache.keys())
                if k.startswith(f"tmpl:{template_key}:")
            ]
            for k in keys_to_evict:
                self._evict(k)
            # Also clear Redis for all languages (use a prefix scan)
            for lang in MessageTemplate.SUPPORTED_LANGUAGES:
                cache.delete(f"tmpl:{template_key}:{lang}")
        else:
            # Nuke everything template-related from memory and Redis
            keys_to_evict = [
                k for k in list(self._memory_cache.keys())
                if k.startswith("tmpl:")
            ]
            for k in keys_to_evict:
                self._evict(k)
            # Redis: clear all template keys for all known keys × languages
            for tmpl in MessageTemplate.STANDARD_KEYS:
                for lang in MessageTemplate.SUPPORTED_LANGUAGES:
                    cache.delete(f"tmpl:{tmpl}:{lang}")

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _get_from_memory(self, cache_key: str) -> Optional[MessageTemplate]:
        entry = self._memory_cache.get(cache_key)
        if entry is None:
            return None
        template, expiry = entry
        if time.monotonic() > expiry:
            del self._memory_cache[cache_key]
            return None
        return template

    def _store_in_memory(self, cache_key: str, template: MessageTemplate) -> None:
        self._memory_cache[cache_key] = (template, time.monotonic() + _CACHE_TTL)

    def _get_from_redis(self, cache_key: str) -> Optional[MessageTemplate]:
        try:
            pk = cache.get(cache_key)
            if pk is None:
                return None
            return MessageTemplate.objects.filter(pk=pk, is_active=True).first()
        except Exception as exc:
            logger.warning("TemplateLibrary: Redis get failed for '%s': %s", cache_key, exc)
            return None

    def _store_in_redis(self, cache_key: str, template: MessageTemplate) -> None:
        try:
            cache.set(cache_key, template.pk, timeout=_CACHE_TTL)
        except Exception as exc:
            logger.warning("TemplateLibrary: Redis set failed for '%s': %s", cache_key, exc)

    def _get_from_db(
        self, template_key: str, language: str
    ) -> Optional[MessageTemplate]:
        try:
            return MessageTemplate.objects.get(
                template_key=template_key,
                language=language,
                is_active=True,
            )
        except MessageTemplate.DoesNotExist:
            return None
        except Exception as exc:
            logger.error(
                "TemplateLibrary: DB query failed for '%s'/'%s': %s",
                template_key,
                language,
                exc,
            )
            return None

    def _evict(self, cache_key: str) -> None:
        self._memory_cache.pop(cache_key, None)
        try:
            cache.delete(cache_key)
        except Exception as exc:
            logger.warning("TemplateLibrary: Redis delete failed for '%s': %s", cache_key, exc)