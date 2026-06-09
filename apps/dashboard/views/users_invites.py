"""
Admin endpoints for the invitation lifecycle:

- Resend an existing invitation (mint a fresh token).
- Revoke a pending invitation (suspend + invalidate token).
- Bulk-invite from a list of {full_name, email, role, organisation?} rows.
"""
from __future__ import annotations

import secrets
from typing import Iterable

from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.audit import AuditAction, log_audit_event
from apps.dashboard.models import User
from apps.dashboard.permissions import IsAdministrator
from apps.dashboard.services.emails import send_invitation_email
from apps.dashboard.views.mixins import AuditLogMixin
from apps.dashboard.views.users import INVITE_TOKEN_TTL_SECONDS


def _mint_invite_token(user: User) -> tuple[str, str]:
    """Generate a fresh invite token, store it under both keys, return (token, url)."""
    token = secrets.token_urlsafe(32)
    cache.set(f"invite:{token}", user.user_id, timeout=INVITE_TOKEN_TTL_SECONDS)
    cache.set(f"pending_invite:{user.user_id}", token, timeout=INVITE_TOKEN_TTL_SECONDS)
    invite_url = f"{settings.DASHBOARD_URL.rstrip('/')}/accept-invite?token={token}"
    return token, invite_url


def _invalidate_invite_token(user_id: int) -> None:
    """Remove the user's outstanding invite token from cache (both directions)."""
    existing = cache.get(f"pending_invite:{user_id}")
    if existing:
        cache.delete(f"invite:{existing}")
    cache.delete(f"pending_invite:{user_id}")


class UserResendInviteView(AuditLogMixin, APIView):
    permission_classes = [IsAuthenticated, IsAdministrator]

    def post(self, request: Request, user_id: int) -> Response:
        try:
            user = User.objects.get(user_id=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        if user.status != User.Status.PENDING_VERIFICATION:
            return Response(
                {"detail": "Only pending users can have their invitation resent."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _invalidate_invite_token(user.user_id)
        token, invite_url = _mint_invite_token(user)
        send_invitation_email(user=user, inviter=request.user, token=token)
        log_audit_event(
            request.user,
            AuditAction.INVITE_RESENT,
            target_user=user,
            request=request,
        )
        return Response({"invite_url": invite_url}, status=status.HTTP_200_OK)


class UserRevokeInviteView(AuditLogMixin, APIView):
    permission_classes = [IsAuthenticated, IsAdministrator]

    def post(self, request: Request, user_id: int) -> Response:
        try:
            user = User.objects.get(user_id=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        if user.status != User.Status.PENDING_VERIFICATION:
            return Response(
                {"detail": "Only pending users can have their invitation revoked."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _invalidate_invite_token(user.user_id)
        old_status = user.status
        user.status = User.Status.SUSPENDED
        user.save(update_fields=["status"])
        log_audit_event(
            request.user,
            AuditAction.INVITE_REVOKED,
            field_changed="status",
            old_value=old_status,
            new_value=str(user.status),
            target_user=user,
            request=request,
        )
        return Response({"detail": "Invitation revoked."}, status=status.HTTP_200_OK)


def _validate_bulk_row(row: dict) -> tuple[dict | None, str | None]:
    """Return (cleaned_row, error_message). One of the two is None."""
    if not isinstance(row, dict):
        return None, "Row must be an object."
    email = (row.get("email") or "").strip().lower()
    full_name = (row.get("full_name") or "").strip()
    role = (row.get("role") or "").strip() or User.Role.NGO_STAFF
    if not email or "@" not in email:
        return None, "Invalid email."
    if not full_name:
        return None, "Full name is required."
    if role not in dict(User.Role.choices):
        return None, f"Unknown role '{role}'."
    return (
        {
            "email": email,
            "full_name": full_name,
            "role": role,
            "organisation": (row.get("organisation") or "").strip(),
        },
        None,
    )


class UserBulkInviteView(AuditLogMixin, APIView):
    permission_classes = [IsAuthenticated, IsAdministrator]

    def post(self, request: Request) -> Response:
        rows = request.data.get("rows") if isinstance(request.data, dict) else None
        if not isinstance(rows, list) or not rows:
            return Response(
                {"detail": "Request must include a non-empty 'rows' array."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created: list[dict] = []
        errors: list[dict] = []

        for row in rows:
            clean, err = _validate_bulk_row(row)
            if err:
                errors.append({"email": (row.get("email") if isinstance(row, dict) else None), "error": err})
                continue
            assert clean is not None
            if User.objects.filter(email__iexact=clean["email"]).exists():
                errors.append({"email": clean["email"], "error": "User already exists."})
                continue

            user = User.objects.create_user(
                password=secrets.token_urlsafe(32),
                status=User.Status.PENDING_VERIFICATION,
                invited_by=request.user,
                full_name=clean["full_name"],
                email=clean["email"],
                role=clean["role"],
                organisation=clean["organisation"],
            )
            token, invite_url = _mint_invite_token(user)
            send_invitation_email(user=user, inviter=request.user, token=token)
            log_audit_event(
                request.user,
                AuditAction.USER_CREATED,
                target_user=user,
                request=request,
            )
            created.append(
                {"email": user.email, "user_id": user.user_id, "invite_url": invite_url}
            )

        log_audit_event(
            request.user,
            AuditAction.BULK_INVITE_CREATED,
            new_value=f"created={len(created)} errors={len(errors)}",
            request=request,
        )
        return Response(
            {"created": created, "errors": errors},
            status=status.HTTP_200_OK if created else status.HTTP_400_BAD_REQUEST,
        )
