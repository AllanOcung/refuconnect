"""
Views for the notifications app.
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications.models import Notification
from apps.notifications.serializers import (
    NotificationSerializer,
    SendAcknowledgementSerializer,
    SendBroadcastSerializer,
)
from apps.notifications.services.broadcast_manager import create_broadcast
from apps.notifications.services.delivery_tracker import handle_webhook_update
from apps.notifications.tasks import send_notification_task

logger = logging.getLogger(__name__)


class NotificationListView(ListAPIView):
    """
    GET /api/v1/notifications/
    Returns recent notifications (most recent first).
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.select_related(
            "sent_by", "related_feedback"
        ).order_by("-created_at")


class SendAcknowledgementView(APIView):
    """
    POST /api/v1/notifications/acknowledge/
    Sends an acknowledgement notification for a given feedback record.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        from apps.feedback.models import Feedback
        from apps.notifications.models import UserConsent
        from apps.notifications.services.response_composer import compose_acknowledgement

        serializer = SendAcknowledgementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        feedback_id = serializer.validated_data["feedback_id"]
        language = serializer.validated_data["language"]

        try:
            feedback = Feedback.objects.get(pk=feedback_id)
        except Feedback.DoesNotExist:
            return Response({"detail": "Feedback not found."}, status=status.HTTP_404_NOT_FOUND)

        consent = UserConsent.objects.filter(
            anonymous_user_id=feedback.anonymous_user_id, is_active=True
        ).first()

        if not consent:
            return Response(
                {"detail": "No active consent found for this user."},
                status=status.HTTP_404_NOT_FOUND,
            )

        message_body = compose_acknowledgement(feedback, language=language)
        notification = Notification.objects.create(
            user_consent=consent,
            related_feedback=feedback,
            message_type=Notification.MessageType.ACKNOWLEDGEMENT,
            message_body=message_body,
            sent_by=request.user,
            delivery_status=Notification.DeliveryStatus.QUEUED,
        )
        send_notification_task.delay(notification.pk)

        return Response(
            NotificationSerializer(notification).data, status=status.HTTP_201_CREATED
        )


class SendBroadcastView(APIView):
    """
    POST /api/v1/notifications/broadcast/
    Queues broadcast notifications for all consenting users on a given channel.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = SendBroadcastSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        notifications = create_broadcast(
            sender=request.user,
            message=data["message"],
            channel=data["channel"],
            language=data["language"],
            message_type=data["message_type"],
            broadcast_type=data["broadcast_type"],
        )

        for notification in notifications:
            send_notification_task.delay(notification.pk)

        return Response(
            {"queued": len(notifications)},
            status=status.HTTP_202_ACCEPTED,
        )


class DeliveryWebhookView(APIView):
    """
    POST /api/v1/notifications/webhook/delivery/
    Receives delivery status updates from SMS/WhatsApp gateways.
    """

    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        handle_webhook_update(request.data)
        return Response({"detail": "received"}, status=status.HTTP_200_OK)
