"""
DRF permission classes for the dashboard app.
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission

from apps.dashboard.models import User


class IsAdministrator(BasePermission):
    """Allow access only to users with the Administrator role."""

    message = "You must be an Administrator to perform this action."

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == User.Role.ADMINISTRATOR
        )


class IsNGOStaff(BasePermission):
    """Allow access to NGO Staff and Administrators."""

    message = "You must be NGO Staff or an Administrator."

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in (User.Role.ADMINISTRATOR, User.Role.NGO_STAFF)
        )


class IsOwnerOrAdministrator(BasePermission):
    """Object-level: allow access to the object owner or an Administrator."""

    message = "You do not have permission to access this resource."

    def has_object_permission(self, request, view, obj) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.role == User.Role.ADMINISTRATOR:
            return True
        # obj is expected to have a user/owner FK
        owner = getattr(obj, "user", None) or getattr(obj, "created_by", None)
        return owner == request.user
