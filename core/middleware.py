from django.utils import timezone
from django.db import OperationalError
from .models import UserActivity


class UpdateLastActivityMiddleware:
    """Har bir kirgan (login qilgan) foydalanuvchi so'rov yuborganda
    UserActivity.last_seen ni yangilaydi — shu orqali 'onlayn' holati aniqlanadi."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Media, Static va AJAX so'rovlarida bazani keraksiz yuklamaslik
        path = request.path_info
        skip_paths = ('/media/', '/static/', '/favicon.ico')

        if not path.startswith(skip_paths) and getattr(request, 'user', None) and request.user.is_authenticated:
            try:
                UserActivity.objects.update_or_create(
                    user=request.user,
                    defaults={'last_seen': timezone.now()}
                )
            except OperationalError:
                # Agar baza baribir qisqa muddatga qulflansa, server 500 xatosi bermasdan davom etadi
                pass

        response = self.get_response(request)
        return response