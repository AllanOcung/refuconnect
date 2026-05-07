from __future__ import annotations

from rest_framework.permissions import BasePermission

from apps.dashboard.models import User


class IsAdministrator(BasePermission):
    """Only active Administrator users can access this endpoint."""

    message = "You must be an active Administrator to perform this action."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.role == User.Role.ADMINISTRATOR
            and user.status == User.Status.ACTIVE
        )


class IsNGOStaff(BasePermission):
    """Active Administrator and NGO_Staff users can access this endpoint."""

    message = "You must be active NGO Staff or an Administrator."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.role in (User.Role.ADMINISTRATOR, User.Role.NGO_STAFF)
            and user.status == User.Status.ACTIVE
        )


class IsActiveUser(BasePermission):
    """Any authenticated active user can access this endpoint."""

    message = "Your account must be active to access this endpoint."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.status == User.Status.ACTIVE)


class IsOwnerOrAdministrator(BasePermission):
    """Object-level permission for owned resources."""

    message = "You do not have permission to access this resource."

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.role == User.Role.ADMINISTRATOR and user.status == User.Status.ACTIVE:
            return True
        owner = getattr(obj, "user", None) or getattr(obj, "created_by", None)
        return owner == user and user.status == User.Status.ACTIVE
