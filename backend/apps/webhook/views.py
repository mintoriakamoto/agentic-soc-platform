import hmac
import logging

from django.conf import settings
from pydantic import ValidationError
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.webhook.service import (
    WebhookRedisError,
    handle_kibana_webhook,
    handle_splunk_webhook,
)

logger = logging.getLogger(__name__)
INVALID_WEBHOOK_PAYLOAD_DETAIL = "Invalid webhook payload."
WEBHOOK_STREAM_UNAVAILABLE_DETAIL = "Webhook stream service is unavailable."
WEBHOOK_FORBIDDEN_DETAIL = "Invalid webhook token."
WEBHOOK_TOKEN_HEADER = "HTTP_X_ASP_WEBHOOK_TOKEN"


class SharedTokenWebhookView(APIView):
    """Base view for inbound alert webhooks.

    These endpoints write attacker-supplied data into a Redis stream that the module worker turns
    into Cases, so they are gated on a shared token whenever ASP_WEBHOOK_TOKEN is configured.
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def rejected_response(self, request):
        expected = getattr(settings, "WEBHOOK_SHARED_TOKEN", "")
        if not expected:
            return None
        presented = request.META.get(WEBHOOK_TOKEN_HEADER, "")
        if hmac.compare_digest(presented, expected):
            return None
        logger.warning("Rejected webhook with missing or invalid token: path=%s", request.path)
        return Response({"detail": WEBHOOK_FORBIDDEN_DETAIL}, status=status.HTTP_403_FORBIDDEN)


class SplunkWebhookView(SharedTokenWebhookView):
    def post(self, request):
        if rejected := self.rejected_response(request):
            return rejected
        try:
            result = handle_splunk_webhook(request.data)
        except (ValidationError, ValueError):
            logger.info("Invalid Splunk webhook payload", exc_info=True)
            return Response({"detail": INVALID_WEBHOOK_PAYLOAD_DETAIL}, status=status.HTTP_400_BAD_REQUEST)
        except WebhookRedisError:
            logger.exception("Failed to process Splunk webhook")
            return Response({"detail": WEBHOOK_STREAM_UNAVAILABLE_DETAIL}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(result.model_dump(), status=status.HTTP_200_OK)


class KibanaWebhookView(SharedTokenWebhookView):
    def post(self, request):
        if rejected := self.rejected_response(request):
            return rejected
        try:
            result = handle_kibana_webhook(request.data)
        except (ValidationError, ValueError):
            logger.info("Invalid Kibana webhook payload", exc_info=True)
            return Response({"detail": INVALID_WEBHOOK_PAYLOAD_DETAIL}, status=status.HTTP_400_BAD_REQUEST)
        except WebhookRedisError:
            logger.exception("Failed to process Kibana webhook")
            return Response({"detail": WEBHOOK_STREAM_UNAVAILABLE_DETAIL}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(result.model_dump(), status=status.HTTP_200_OK)
