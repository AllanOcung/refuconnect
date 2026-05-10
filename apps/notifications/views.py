"""
Views for the notifications app.

Endpoints
─────────
Delivery webhooks:
  POST /api/v1/delivery/sms/
  POST /api/v1/delivery/whatsapp/

Targeted responses:
  POST /api/v1/feedback/<id>/respond/
  GET  /api/v1/feedback/<id>/responses/

Broadcasts:
  POST /api/v1/broadcasts/
  GET  /api/v1/broadcasts/
  GET  /api/v1/broadcasts/estimate/
  GET  /api/v1/broadcasts/<id>/
  GET  /api/v1/broadcasts/<id>/progress/
  POST /api/v1/broadcasts/<id>/cancel/

Templates (admin only):
  GET    /api/v1/templates/
  POST   /api/v1/templates/
  GET    /api/v1/templates/keys/
  GET    /api/v1/templates/<id>/
  PATCH  /api/v1/templates/<id>/
  DELETE /api/v1/templates/<id>/

IMPORTANT: Delivery webhook views MUST return HTTP 200 even on errors.
Both Africa's Talking and Meta retry delivery on any non-200 response,
which would cause thousands of duplicate callbacks on a single DB error.
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.dashboard.permissions import IsNGOStaff
from apps.notifications.models import Broadcast, MessageTemplate, Notification
from apps.notifications.serializers import (
    BroadcastCreateSerializer,
    BroadcastDetailSerializer,
    BroadcastEstimateSerializer,
    BroadcastListSerializer,
    BroadcastProgressSerializer,
    FeedbackResponseSerializer,
    MessageTemplateSerializer,
    MessageTemplateUpdateSerializer,
    SendResponseSerializer,
)
from apps.notifications.services.delivery_tracker import DeliveryTracker
from apps.notifications.services.template_library import TemplateLibrary

logger = logging.getLogger("apps.notifications.views")


# ─── Delivery webhooks ────────────────────────────────────────────────────────

class SMSDeliveryWebhookView(APIView):
    """
    POST /api/v1/delivery/sms/
    Africa's Talking delivery report callback.

    ALWAYS returns HTTP 200 — the gateway retries on any other status.
    HMAC signature verification is applied (same as Subsystem 1's SMS webhook).
    No user authentication — called by the AT gateway.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request: Request) -> Response:
        try:
            DeliveryTracker().handle_sms_delivery_callback(request.data)
        except Exception as exc:
            logger.error(
                "SMSDeliveryWebhookView: Unhandled exception — still returning 200: %s", exc
            )
        return Response({"detail": "received"}, status=status.HTTP_200_OK)


class WhatsAppDeliveryWebhookView(APIView):
    """
    POST /api/v1/delivery/whatsapp/
    Meta WhatsApp status update callback.

    Status payloads are routed here from Subsystem 1's WhatsAppWebhookView.
    ALWAYS returns HTTP 200.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request: Request) -> Response:
        try:
            # Meta embeds status updates in entry[].changes[].value.statuses[]
            entries = request.data.get("entry", [])
            for entry in entries:
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for status_obj in value.get("statuses", []):
                        DeliveryTracker().handle_whatsapp_status_callback(status_obj)
        except Exception as exc:
            logger.error(
                "WhatsAppDeliveryWebhookView: Unhandled exception — still returning 200: %s", exc
            )
        return Response({"detail": "received"}, status=status.HTTP_200_OK)


# ─── Targeted responses ───────────────────────────────────────────────────────

class SendResponseView(APIView):
    """POST /api/v1/feedback/<feedback_id>/respond/"""

    permission_classes = [IsNGOStaff]

    def post(self, request: Request, feedback_id: int) -> Response:
        from apps.notifications.services.response_composer import (
            FeedbackNotFoundError,
            ResponseComposer,
        )
        from apps.common.exceptions import ConsentNotFoundError

        serializer = SendResponseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = ResponseComposer().send_response(
                feedback_id=feedback_id,
                message_body=serializer.validated_data["message_body"],
                language_override=serializer.validated_data.get("language_override"),
                user=request.user,
            )
        except FeedbackNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except ConsentNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        # Build response with message_preview
        notification = Notification.objects.get(pk=result["notification_id"])
        return Response(
            {
                "status": result["status"],
                "notification_id": result["notification_id"],
                "delivery_language": notification.delivery_language,
                "message_preview": notification.content[:100],
            },
            status=status.HTTP_200_OK,
        )


class FeedbackResponseListView(ListAPIView):
    """GET /api/v1/feedback/<feedback_id>/responses/"""

    serializer_class = FeedbackResponseSerializer
    permission_classes = [IsNGOStaff]

    def get_queryset(self):
        feedback_id = self.kwargs["feedback_id"]
        return Notification.objects.filter(
            feedback_id=feedback_id,
            message_type=Notification.MessageType.TARGETED_RESPONSE,
        ).select_related("sent_by_user").order_by("-notification_id")


# ─── Broadcasts ───────────────────────────────────────────────────────────────

class BroadcastListCreateView(APIView):
    """
    GET  /api/v1/broadcasts/  — paginated list
    POST /api/v1/broadcasts/  — create and optionally dispatch a broadcast
    """
    permission_classes = [IsNGOStaff]

    def get(self, request: Request) -> Response:
        broadcasts = Broadcast.objects.select_related("created_by").order_by("-created_at")
        serializer = BroadcastListSerializer(broadcasts, many=True)
        return Response(serializer.data)

    def post(self, request: Request) -> Response:
        from apps.notifications.services.broadcast_manager import (
            BroadcastManager,
            NoBroadcastRecipientsError,
        )

        serializer = BroadcastCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            broadcast = BroadcastManager().create_broadcast(
                message_type=data["message_type"],
                body_en=data["body_en"],
                target_type=data["target_type"],
                target_params=data["target_params"],
                channels=data["channels"],
                languages=data["languages"],
                schedule_at=data.get("schedule_at"),
                user=request.user,
            )
        except NoBroadcastRecipientsError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "broadcast_id": broadcast.broadcast_id,
                "status": broadcast.status,
                "total_recipients": broadcast.total_recipients,
                "message": f"Broadcast is being sent to {broadcast.total_recipients} opted-in recipients.",
            },
            status=status.HTTP_201_CREATED,
        )


class BroadcastEstimateView(APIView):
    """GET /api/v1/broadcasts/estimate/ — pre-flight recipient count"""

    permission_classes = [IsNGOStaff]

    def post(self, request: Request) -> Response:
        from apps.notifications.services.broadcast_manager import BroadcastManager

        serializer = BroadcastEstimateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        count = BroadcastManager().estimate_recipients(
            target_type=data["target_type"],
            target_params=data["target_params"],
        )
        return Response({"estimated_recipients": count})


class BroadcastDetailView(APIView):
    """GET /api/v1/broadcasts/<broadcast_id>/"""

    permission_classes = [IsNGOStaff]

    def get(self, request: Request, broadcast_id: int) -> Response:
        try:
            broadcast = Broadcast.objects.select_related("created_by", "target_category").get(
                broadcast_id=broadcast_id
            )
        except Broadcast.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(BroadcastDetailSerializer(broadcast).data)


class BroadcastProgressView(APIView):
    """GET /api/v1/broadcasts/<broadcast_id>/progress/ — live polling"""

    permission_classes = [IsNGOStaff]

    def get(self, request: Request, broadcast_id: int) -> Response:
        try:
            broadcast = Broadcast.objects.get(broadcast_id=broadcast_id)
        except Broadcast.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(BroadcastProgressSerializer(broadcast).data)


class BroadcastCancelView(APIView):
    """POST /api/v1/broadcasts/<broadcast_id>/cancel/"""

    permission_classes = [IsNGOStaff]

    def post(self, request: Request, broadcast_id: int) -> Response:
        try:
            broadcast = Broadcast.objects.get(broadcast_id=broadcast_id)
        except Broadcast.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if broadcast.status != Broadcast.Status.SCHEDULED:
            return Response(
                {"detail": f"Cannot cancel a broadcast with status '{broadcast.status}'. "
                           f"Only 'Scheduled' broadcasts can be cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        broadcast.status = Broadcast.Status.FAILED
        broadcast.save(update_fields=["status"])
        return Response({"detail": "Broadcast cancelled.", "broadcast_id": broadcast_id})


# ─── Message templates (admin only) ───────────────────────────────────────────

class TemplateListCreateView(APIView):
    """
    GET  /api/v1/templates/
    POST /api/v1/templates/
    Admin only.
    """
    permission_classes = [IsNGOStaff]

    def get(self, request: Request) -> Response:
        templates = MessageTemplate.objects.all().order_by("template_key", "language")
        return Response(MessageTemplateSerializer(templates, many=True).data)

    def post(self, request: Request) -> Response:
        serializer = MessageTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        template = serializer.save(created_by=request.user)
        TemplateLibrary().invalidate_cache(template.template_key, template.language)
        return Response(
            MessageTemplateSerializer(template).data, status=status.HTTP_201_CREATED
        )


class TemplateKeyListView(APIView):
    """GET /api/v1/templates/keys/ — distinct template_key values for dropdown"""

    permission_classes = [IsNGOStaff]

    def get(self, request: Request) -> Response:
        keys = (
            MessageTemplate.objects.values_list("template_key", flat=True)
            .distinct()
            .order_by("template_key")
        )
        return Response({"keys": list(keys)})


class TemplateDetailView(APIView):
    """
    GET    /api/v1/templates/<template_id>/
    PATCH  /api/v1/templates/<template_id>/
    DELETE /api/v1/templates/<template_id>/
    """
    permission_classes = [IsNGOStaff]

    def _get_template(self, template_id: int):
        try:
            return MessageTemplate.objects.get(pk=template_id)
        except MessageTemplate.DoesNotExist:
            return None

    def get(self, request: Request, template_id: int) -> Response:
        template = self._get_template(template_id)
        if template is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(MessageTemplateSerializer(template).data)

    def patch(self, request: Request, template_id: int) -> Response:
        template = self._get_template(template_id)
        if template is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = MessageTemplateUpdateSerializer(template, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        TemplateLibrary().invalidate_cache(template.template_key, template.language)
        return Response(MessageTemplateSerializer(template).data)

    def delete(self, request: Request, template_id: int) -> Response:
        template = self._get_template(template_id)
        if template is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if template.is_system:
            return Response(
                {"detail": "System templates cannot be deleted. You may deactivate them via PATCH."},
                status=status.HTTP_403_FORBIDDEN,
            )

        TemplateLibrary().invalidate_cache(template.template_key, template.language)
        template.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)