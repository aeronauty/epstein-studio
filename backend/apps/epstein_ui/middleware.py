import re
import secrets

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.db.utils import OperationalError, ProgrammingError
from django.shortcuts import render


MOBILE_KEYWORDS = ("mobile", "android", "iphone", "ipad", "ipod")
USER_HASH_COOKIE = "epstein_user_hash"
USER_HASH_RE = re.compile(r"^[a-f0-9]{16}$")


class MobileBlockMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ""
        if path.startswith("/static/") or path.startswith("/media/"):
            return self.get_response(request)
        ua = (request.META.get("HTTP_USER_AGENT") or "").lower()
        if ua and any(keyword in ua for keyword in MOBILE_KEYWORDS):
            return render(request, "epstein_ui/mobile_block.html", status=403)
        return self.get_response(request)


class PersistentUserHashMiddleware:
    """Auto-login middleware using a persistent anonymous user hash cookie."""

    def __init__(self, get_response):
        self.get_response = get_response

    def _generate_username(self) -> str:
        return secrets.token_hex(8)

    def _resolve_user(self, cookie_hash: str):
        if cookie_hash and USER_HASH_RE.fullmatch(cookie_hash):
            user = User.objects.filter(username=cookie_hash).first()
            if user:
                return user, cookie_hash
            user = User(username=cookie_hash)
            user.set_unusable_password()
            user.save()
            return user, cookie_hash

        username = self._generate_username()
        while User.objects.filter(username=username).exists():
            username = self._generate_username()
        user = User(username=username)
        user.set_unusable_password()
        user.save()
        return user, username

    def __call__(self, request):
        path = request.path or ""
        if path.startswith("/static/") or path.startswith("/media/") or path.startswith("/admin/"):
            return self.get_response(request)

        cookie_hash = (request.COOKIES.get(USER_HASH_COOKIE) or "").strip().lower()
        resolved_hash = cookie_hash

        if not request.user.is_authenticated:
            try:
                user, resolved_hash = self._resolve_user(cookie_hash)
            except (OperationalError, ProgrammingError):
                return self.get_response(request)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")

        response = self.get_response(request)
        if not USER_HASH_RE.fullmatch(resolved_hash):
            resolved_hash = request.user.username if request.user.is_authenticated else ""
        if resolved_hash and request.COOKIES.get(USER_HASH_COOKIE) != resolved_hash:
            response.set_cookie(
                USER_HASH_COOKIE,
                resolved_hash,
                max_age=365 * 24 * 60 * 60,
                httponly=True,
                samesite="Lax",
                secure=not settings.DEBUG,
            )
        return response
