import os
import json
from django.core.management.base import BaseCommand
from django.conf import settings
from core.models import Achievement
from google import genai


class Command(BaseCommand):
    help = 'Gemini orqali 100 ta achievement/mission yaratadi'

    def handle(self, *args, **options):
        # Avval tekshirish - achievement allaqachon bormi?
        if Achievement.objects.exists():
            self.stdout.write(self.style.WARNING('⚠️ Achievement-lar allaqachon mavjud!'))
            return

        api_key = os.getenv('GEMINI_API_KEYS', '').split(',')[0].strip()
        if not api_key:
            self.stdout.write(self.style.ERROR('❌ GEMINI_API_KEYS topilmadi!'))
            return

        client = genai.Client(api_key=api_key)

        prompt = """
        Maktab o'quvchilari uchun 100 ta achievement/mission yaratish kerak.
        JSON formatida faqat va faqat, boshqa hech narsa yozma:

        [
            {
                "mission_type": "first_test",
                "name": "Birinchi Testni Yechish",
                "description": "Birinchi marta testni yechib tugatishingiz",
                "icon": "🧪",
                "points": 10,
                "week": 1
            },
            ...
            (bu misoldir, 100 ta o'zgina mission qo'shish kerak)
        ]

        Shartlar:
        - Har hafta 2 ta yangi mission qo'shiladi (50 hafta = 100 missiya)
        - Icon - faqat emoji (🏆, 🎯, 📚, 💯, etc)
        - Points: 5-50 orasida random
        - Turli turi bo'lsin: Test, Ball, Do'st, IQ, Kirish, Reading, etc
        - Uz tilidagi name va description
        - mission_type: snake_case format

        FAQAT JSON, boshqa hech nima yozma!
        """

        try:
            self.stdout.write('⏳ Gemini-dan missionlar yaratilmoqda...')
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt
            )

            # JSON ni parse qilish
            raw_text = response.text.strip().replace('```json', '').replace('```', '')
            achievements_data = json.loads(raw_text)

            # Database-ga saqlash
            created_count = 0
            for data in achievements_data:
                achievement, created = Achievement.objects.get_or_create(
                    mission_type=data.get('mission_type', ''),
                    defaults={
                        'name': data.get('name', 'Unknown'),
                        'description': data.get('description', ''),
                        'icon': data.get('icon', '🏆'),
                        'reward_points': data.get('points', 10),
                        'week_number': data.get('week', 1),
                    }
                )
                if created:
                    created_count += 1

            self.stdout.write(self.style.SUCCESS(f'✅ {created_count} ta achievement yaratildi!'))

        except json.JSONDecodeError as e:
            self.stdout.write(self.style.ERROR(f'❌ JSON parse xatosi: {e}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Xatolik: {e}'))