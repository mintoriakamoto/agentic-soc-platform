from rest_framework import serializers

from .models import Playbook


class PlaybookSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source="user.username", read_only=True, default="")
    case_title = serializers.CharField(source="case.title", read_only=True)
    case_id = serializers.UUIDField(source="case.id", read_only=True)
    case_readable_id = serializers.CharField(source="case.case_id", read_only=True)

    class Meta:
        model = Playbook
        fields = "__all__"
        # started_at is the reaper's lease stamp: a client that could write it could keep an
        # abandoned run alive forever, or fail a live one.
        read_only_fields = ("id", "playbook_id", "created_at", "updated_at", "started_at")
