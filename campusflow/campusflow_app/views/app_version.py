"""
Mobile app version check (the "Update available" / "Update required" UI state).

  GET /api/app-version/  (public)
  -> {latest_version, min_supported_version, message, android_url, ios_url}

The app compares its own version against these:
  below min_supported_version -> blocking "Update required" screen
  below latest_version        -> dismissible "Update available" banner

Values come from environment variables so a release can be announced (or an
old, broken build forced off) without a backend deploy.
"""

import os

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class AppVersionView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({
            "latest_version": os.environ.get("MOBILE_LATEST_VERSION", "1.0.0"),
            "min_supported_version": os.environ.get("MOBILE_MIN_SUPPORTED_VERSION", "1.0.0"),
            "message": os.environ.get("MOBILE_UPDATE_MESSAGE", ""),
            "android_url": os.environ.get(
                "MOBILE_ANDROID_STORE_URL", ""
            ),
            "ios_url": os.environ.get("MOBILE_IOS_STORE_URL", ""),
        })
