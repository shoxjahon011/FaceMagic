import json
import os
import time
import re
from dotenv import load_dotenv
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, get_user_model, update_session_auth_hash
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db.models.functions import Coalesce
from google import genai
from .models import  Message,ChatGroup
from django.views.decorators.http import require_http_methods
from .models import (
    StudentProfile,
    Teacher,
    TestQuestion,
    HomeworkSubmission,
    Homework,
    TestResult,
    FriendRequest,
    Achievement,
    UserAchievement,
    GroupInvite
)
from django.db.models import Sum, Count, F
User = get_user_model()
load_dotenv()

# ==========================================================
# GEMINI 3.6 KONFIGURATSIYA (bir nechta API kalit bilan)
# ==========================================================

GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_API_KEYS = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]

_gemini_clients = {}
_current_key_index = 0
_rate_limit_tracker = {}

print("\n>>> SHU VIEWS FAYLI ISHLAYAPTI! <<<\n")
# ==========================================================
# YORDAMCHI XAVFSIZLIK FUNKSIYALARI
# ==========================================================
@login_required
def achievements_view(request):
    profile = get_student_profile(request.user)
    if not profile:
        return JsonResponse({'error': 'Profil topilmadi'}, status=404)

    all_achievements = Achievement.objects.filter(is_active=True).order_by('-rarity', 'week_number', 'id')

    # UserAchievement OBJECTLARINI OLISH
    user_achievements_map = {
        ua.achievement_id: ua
        for ua in UserAchievement.objects.filter(student=profile)
    }

    completed_ids = set(user_achievements_map.keys())

    achievements_data = []

    total_tests = TestResult.objects.filter(student=profile).count()
    total_friends = FriendRequest.objects.filter(
        Q(from_user=profile.user, status='accepted') |
        Q(to_user=profile.user, status='accepted')
    ).count()
    total_homeworks = Homework.objects.filter(teacher__user=profile.user).count()
    total_unlocked = UserAchievement.objects.filter(student=profile).count()

    profile_fields_filled = sum([
        bool(profile.nickname),
        bool(profile.phone),
        bool(profile.bio)
    ])

    for achievement in all_achievements:
        is_completed = achievement.id in completed_ids
        user_ach = user_achievements_map.get(achievement.id)

        progress_current = 0
        progress_total = achievement.required_value
        progress_percent = 0
        progress_text = ""

        if achievement.action_type == 'test_passed':
            progress_current = total_tests
            progress_text = f"{progress_current}/{progress_total} test"

        elif achievement.action_type == 'points_earned':
            progress_current = profile.score
            progress_text = f"{progress_current}/{progress_total} ball"

        elif achievement.action_type == 'friend_added':
            progress_current = total_friends
            progress_text = f"{progress_current}/{progress_total} do'st"

        elif achievement.action_type == 'iq_test_completed':
            progress_current = profile.iq_score or 0
            progress_text = f"IQ: {progress_current}/{progress_total}"

        elif achievement.action_type == 'homework_submitted':
            progress_current = total_homeworks
            progress_text = f"{progress_current}/{progress_total} vazifa"

        elif achievement.action_type == 'achievement_unlocked':
            progress_current = total_unlocked
            progress_text = f"{progress_current}/{progress_total} achievement"

        elif achievement.action_type == 'profile_completed':
            progress_current = profile_fields_filled
            progress_total = 3
            progress_text = f"{progress_current}/{progress_total} to'liq"

        elif achievement.action_type == 'login_streak':
            progress_text = "Kuniga 1 marta kirish"

        if progress_total > 0:
            progress_percent = min(int((progress_current / progress_total) * 100), 100)

        # ✅ KEY DATA POINTS
        is_legendary = achievement.rarity == 'legendary' if hasattr(achievement, 'rarity') else False
        is_manual = achievement.action_type == 'manual_only'

        achievements_data.append({
            'id': achievement.id,
            'icon_image': achievement.icon_image,
            'name': achievement.name,
            'description': achievement.description,
            'points': achievement.reward_points,
            'completed': is_completed,
            'week': achievement.week_number,
            'action_type': achievement.action_type,
            'progress_current': progress_current,
            'progress_total': progress_total,
            'progress_text': progress_text,
            'progress_percent': progress_percent,
            'is_in_progress': not is_completed and progress_percent > 0,
            'is_manual': is_manual,
            'is_legendary': is_legendary,
            'user_achievement': user_ach,
            'rarity': getattr(achievement, 'rarity', 'common'),
        })

    completed_count = len(completed_ids)
    total_count = all_achievements.count()
    total_points = sum(a['points'] for a in achievements_data if a['completed'])

    return render(request, 'achievements.html', {
        'achievements': achievements_data,
        'completed_count': completed_count,
        'total_count': total_count,
        'total_points': total_points,
        'profile': profile,
    })
@login_required
def equip_title(request, target_id=None):
    if request.method == 'POST':
        selected_title = request.POST.get('selected_title', '').strip()
        profile = StudentProfile.objects.filter(user=request.user).first()
        if profile:
            profile.equipped_title = selected_title
            profile.save()
            print(f"\n>>> UNVON SAQLANDI: {selected_title} <<<\n")

    return redirect('achievements')
ACHIEVEMENT_PRIORITY = {
    'test_passed': 1,
    'points_earned': 2,
    'friend_added': 3,
    'iq_test_completed': 4,
    'login_streak': 5,
    'homework_submitted': 6,
    'achievement_unlocked': 7,
    'profile_completed': 8,
    'all_achievements_week': 9,
    'manual_only': 10,
}


# Yutuqlar darajasi ustuvorligi (Priority)
ACHIEVEMENT_PRIORITY = {
    'legendary': 4,
    'epic': 3,
    'rare': 2,
    'common': 1,
}


@login_required
def student_profile_view(request,view_request):

    profile = (
        getattr(request.user, 'studentprofile', None)
        or getattr(request.user, 'student', None)
        or getattr(request.user, 'profile', None)
        or request.user
    )

    # 1. Avval foydalanuvchi taqqan (is_equipped=True) yutuqni tekshiramiz
    equipped_user_ach = (
        UserAchievement.objects.filter(student=profile, is_equipped=True)
        .select_related('achievement')
        .first()
    )
    profile = StudentProfile.objects.select_related('equipped_title__achievement').filter(user=view_request.user).first()
    equipped_title_name = None
    if equipped_user_ach:
        best_achievement = equipped_user_ach.achievement
        # Taqilgan titul nomini (yoki achievement nomini) olamiz
        equipped_title_name = getattr(equipped_user_ach.achievement, 'title', None) or equipped_user_ach.achievement.name
    else:
        # 2. Agar taqilmagan bo'lsa, bajarilgan yutuqlar ichidan eng qimmatlisini tanlaymiz
        completed_achievements = UserAchievement.objects.filter(
            student=profile, completed_at__isnull=False
        ).select_related('achievement')

        best_achievement = None
        max_priority = -1

        for item in completed_achievements:
            ach_type = getattr(item.achievement, 'achievement_type', 'common')
            prio = ACHIEVEMENT_PRIORITY.get(ach_type, 0)

            if prio > max_priority:
                max_priority = prio
                best_achievement = item.achievement

    context = {
        'profile': profile,
        'best_achievement': best_achievement,
        'equipped_title_name': equipped_title_name,  # <--- Mana bu yer qo'shildi
    }
    return render(request, 'student_profile.html', context)



def get_student_profile(user):
    """O'quvchi profilini har qanday related_name holatida xavfsiz olish"""
    return (
            getattr(user, 'student_profile', None) or
            getattr(user, 'studentprofile', None) or
            StudentProfile.objects.filter(user=user).first()
    )


def get_teacher_profile(user):
    """O'qituvchi profilini har qanday related_name holatida xavfsiz olish"""
    return (
            getattr(user, 'teacher_profile', None) or
            getattr(user, 'teacher', None) or
            Teacher.objects.filter(user=user).first()
    )


def _get_client_for_index(index):
    """Index bo'yicha Gemini client olish (keshlangan holda)"""
    if index not in _gemini_clients:
        try:
            _gemini_clients[index] = genai.Client(api_key=GEMINI_API_KEYS[index])
        except IndexError:
            raise ValueError(f"API key index {index} topilmadi. Jami {len(GEMINI_API_KEYS)} kalit mavjud.")
    return _gemini_clients[index]


def check_rate_limit(user_id, limit_per_minute=2):
    """1 daqiqada foydalanuvchi uchun maksimal so'rovlar sonini tekshirish"""
    now = time.time()
    user_key = f"user_{user_id}"

    if user_key not in _rate_limit_tracker:
        _rate_limit_tracker[user_key] = []

    # 1 minutdan oshib ketgan eski so'rovlarni tozalash
    _rate_limit_tracker[user_key] = [t for t in _rate_limit_tracker[user_key] if now - t < 60]

    if len(_rate_limit_tracker[user_key]) >= limit_per_minute:
        return False, 60 - (now - _rate_limit_tracker[user_key][0])

    _rate_limit_tracker[user_key].append(now)
    return True, 0


# ==========================================================
# ACHIEVEMENT AUTO-UNLOCK FUNKSIYASI
# ==========================================================

def check_and_unlock_achievements(student_profile, action_type, value=1):
    """
    Harakat sodir bo'lganda achievement check qilish va unlock qilish

    action_type: 'test_passed', 'points_earned', 'friend_added', 'iq_test_completed',
                 'login_streak', 'homework_submitted', 'achievement_unlocked', 'profile_completed'
    value: harakat qiymati (1, 100 ball, 5 do'st vs)
    """
    if not student_profile:
        return

    # Shu action_type ga mos achievements topish
    achievements = Achievement.objects.filter(
        action_type=action_type,
        is_active=True
    )

    for achievement in achievements:
        # Allaqachon unlock qilinganmi?
        if UserAchievement.objects.filter(
                student=student_profile,
                achievement=achievement
        ).exists():
            continue

        should_unlock = False

        # ✅ CONDITION LOGIC
        if action_type == 'test_passed':
            # N ta testni yechish
            completed_tests = UserAchievement.objects.filter(
                student=student_profile,
                achievement__action_type='test_passed'
            ).count() + 1

            if completed_tests >= achievement.required_value:
                should_unlock = True

        elif action_type == 'points_earned':
            # M ta ball topish
            if student_profile.score >= achievement.required_value:
                should_unlock = True

        elif action_type == 'friend_added':
            # K ta do'st qo'shish
            friends_count = FriendRequest.objects.filter(
                Q(from_user=student_profile.user, status='accepted') |
                Q(to_user=student_profile.user, status='accepted')
            ).count()

            if friends_count >= achievement.required_value:
                should_unlock = True

        elif action_type == 'iq_test_completed':
            # IQ test bajarildi va ball to'plandi
            if student_profile.iq_score and student_profile.iq_score >= achievement.required_value:
                should_unlock = True

        elif action_type == 'login_streak':
            # Har kuni login (hozircha skip - kompleks logic)
            should_unlock = False

        elif action_type == 'homework_submitted':
            # N ta uy vazifasi yuborildi
            homework_count = value  # Passed value
            if homework_count >= achievement.required_value:
                should_unlock = True

        elif action_type == 'achievement_unlocked':
            # N ta achievement unlock
            unlocked_count = UserAchievement.objects.filter(
                student=student_profile
            ).count() + 1

            if unlocked_count >= achievement.required_value:
                should_unlock = True

        elif action_type == 'profile_completed':
            # Profil to'liq (nickname + phone + bio)
            if (student_profile.nickname and
                    student_profile.phone and
                    student_profile.bio):
                should_unlock = True

        # ✅ UNLOCK QILISH
        if should_unlock:
            user_ach, created = UserAchievement.objects.get_or_create(
                student=student_profile,
                achievement=achievement,
                defaults={'is_new': True}
            )

            if created:
                # Ball qo'shish
                student_profile.score += achievement.reward_points
                student_profile.save()

                print(f"✅ ACHIEVEMENT UNLOCK: {achievement.name} (+{achievement.reward_points} ball)")


# ==========================================================
# HAR BIR API KALIT UCHUN ALOHIDA LIMIT (10 so'rov / daqiqa / kalit)
# ==========================================================

KEY_LIMIT_PER_MINUTE = 10
_key_usage_tracker = {}  # {key_index: [timestamp, timestamp, ...]}


def _key_has_capacity(index, limit_per_minute=KEY_LIMIT_PER_MINUTE):
    """Berilgan kalit shu daqiqada limitga yetib qolmaganini tekshiradi"""
    now = time.time()
    usage = _key_usage_tracker.setdefault(index, [])
    usage[:] = [t for t in usage if now - t < 60]
    return len(usage) < limit_per_minute


def _record_key_usage(index):
    """Kalitdan muvaffaqiyatli foydalanilganini belgilab qo'yish"""
    _key_usage_tracker.setdefault(index, []).append(time.time())


# Kalit-darajasida xato turlari: bularda DARHOL (kutmasdan) keyingi kalitga o'tiladi
_SKIP_KEY_ERROR_MARKERS = [
    '429', 'RESOURCE_EXHAUSTED', 'QUOTA', 'RATE_LIMIT', 'RATE-LIMIT',
    'PERMISSION_DENIED', 'API_KEY_INVALID', 'INVALID_ARGUMENT_API_KEY',
    'UNAUTHENTICATED', 'FORBIDDEN',
]
# Server darajasidagi vaqtinchalik xatolar: kichik kutish bilan keyingi kalitga o'tiladi
_RETRY_ERROR_MARKERS = ['503', 'UNAVAILABLE', 'DEADLINE', 'INTERNAL', '500']


def generate_with_fallback(contents, model=None, user_id=None):
    """
    Barcha GEMINI_API_KEYS ro'yxatidagi kalitlarni birma-bir (round-robin) sinab chiqadi.
    - Har bir kalit daqiqasiga maksimal KEY_LIMIT_PER_MINUTE (10) ta so'rov qabul qiladi;
      shu limitga yetgan kalitlar chaqirilmasdan o'tkazib yuboriladi.
    - Kvota/limit/ruxsat xatolarida: sun'iy kutishsiz, DARHOL keyingi kalitga o'tadi.
    - 503/UNAVAILABLE kabi vaqtinchalik server xatolarida: qisqa kutib, keyingi kalitga o'tadi.
    - Har bir chaqiruvda barcha kalitlar kamida 1 marta (jami 2 marta) sinaladi,
      shundan keyingina "band" xabari qaytariladi.
    """
    global _current_key_index

    if not GEMINI_API_KEYS:
        raise ValueError("GEMINI_API_KEYS topilmadi! .env faylida kamida bitta kalit ko'rsating.")

    model = model or GEMINI_MODEL
    total_keys = len(GEMINI_API_KEYS)
    last_error = None
    error_log = []  # har bir kalitning aniq xatosini yig'ib boramiz

    # Har bir "pass" da barcha kalitlar birma-bir sinaladi (2 pass = jami 2*total_keys urinish)
    for pass_num in range(2):
        for _ in range(total_keys):
            index = _current_key_index
            # keyingi urinish uchun indexni oldindan siljitib qo'yamiz (round-robin)
            _current_key_index = (_current_key_index + 1) % total_keys

            # Bu kalit shu daqiqada limitga yetib qolgan bo'lsa, chaqirmasdan o'tkazamiz
            if not _key_has_capacity(index):
                msg = f"{index + 1}-kalit daqiqasiga {KEY_LIMIT_PER_MINUTE} so'rov limitiga yetdi (local limit)"
                last_error = last_error or ValueError(msg)
                error_log.append(msg)
                print(f"[Gemini] {msg}")
                continue

            try:
                client = _get_client_for_index(index)
                response = client.models.generate_content(model=model, contents=contents)
                _record_key_usage(index)
                print(f"[Gemini] {index + 1}-kalit orqali muvaffaqiyatli javob olindi")
                return response

            except Exception as e:
                err_str = str(e).upper()
                last_error = e
                error_log.append(f"{index + 1}-kalit: {e}")
                print(f"[Gemini] {index + 1}-kalit XATOSI: {e}")

                if any(k in err_str for k in _SKIP_KEY_ERROR_MARKERS):
                    # bu kalit band/yaroqsiz — darhol keyingisiga o'tamiz, kutmaymiz
                    continue

                if any(k in err_str for k in _RETRY_ERROR_MARKERS):
                    time.sleep(0.5)
                    continue

                # Kutilmagan, kalitga bog'liq bo'lmagan xato — baribir keyingi kalitni sinab ko'ramiz,
                # lekin agar oxirgi kalit bo'lsa keyinroq raise qilinadi
                continue

    print("[Gemini] BARCHA KALITLAR ISHLAMADI. To'liq log:")
    for line in error_log:
        print(f"   - {line}")

    if last_error is not None:
        # Real sababni aniq ko'rsatish uchun matnga qo'shib yuboramiz
        raise RuntimeError(
            f"{last_error} | Barcha kalitlar sinaldi: {' || '.join(error_log)}"
        ) from last_error

    raise ValueError("Barcha API kalitlar cheklangan yoki server band, birozdan keyin qayta urining.")


# ==========================================================
# AI INTEGRATSIYASI
# ==========================================================

def test_ai_connection(request):
    if not GEMINI_API_KEYS:
        return JsonResponse({'status': 'error', 'error_details': 'GEMINI_API_KEYS topilmadi'})

    try:
        client = _get_client_for_index(_current_key_index)
        available_models = [m.name for m in client.models.list()]

        return JsonResponse({
            'status': 'success',
            'active_key_index': _current_key_index + 1,
            'total_keys': len(GEMINI_API_KEYS),
            'current_model': GEMINI_MODEL,
            'models': available_models,
            'message': f'{len(GEMINI_API_KEYS)} ta API kalit konfiguratsiya qilingan'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'active_key_index': _current_key_index + 1,
            'error_details': str(e)
        })


@login_required
def ai_chat(request):
    """AI chat - 3 ta rejim (25%, 50%, 100%), rate-limit, media yuklash, reply va avto-nomlash bilan"""
    if request.method == 'POST':
        try:
            # 1. Rate limit tekshirish
            can_request, wait_time = check_rate_limit(request.user.id, limit_per_minute=15)
            if not can_request:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Birozdan keyin qayta urining ({int(wait_time)}s kutish)'
                }, status=429)

            # FormData orqali keladigan ma'lumotlarni qabul qilish
            user_message = request.POST.get('message', '').strip()
            chat_mode = str(request.POST.get('mode', '100'))
            session_id = request.POST.get('session_id')
            reply_to_id = request.POST.get('reply_to_id')
            uploaded_files = request.FILES.getlist('files')

            if not user_message and not uploaded_files:
                return JsonResponse({'status': 'error', 'message': 'Matn yoki fayl kiritilmadi!'}, status=400)

            # 6. Yaratuvchi haqidagi savolni Python darajasida ushlash
            profile = get_student_profile(request.user)
            profile_id = request.user.id
            profile_code = getattr(profile, 'profile_code', f"FM-{profile_id}") if profile else f"FM-{profile_id}"

            msg_lower = user_message.lower()
            creator_keywords = ["kim yaratgan", "kim yasagan", "muallif", "dasturchi", "yaratuvching"]

            if any(keyword in msg_lower for keyword in creator_keywords):
                reply_text = f"Meni Ashurboyev Shoxjahon yaratgan. Shoxjahoning profil ID si: {profile_code} (User ID: {profile_id})."
                return JsonResponse({
                    'status': 'success',
                    'reply': reply_text,
                })

            # 7. Prompt logikasi
            length_rule = " QO'SHIMCHA QOIDA: Har qanday holatda ham javobingiz maksimum 2 ta qisqa jumladan iborat bo'lsin!"

            if chat_mode == '25':
                system_instructions = f"""
                Siz 'FaceMaagic' platformasining rasmiy AI assistentisiz.
                Foydalanuvchi so'roviga an'anaviy, rasmiy, hushfe'l va qisqa javob bering.{length_rule}
                """
            elif chat_mode == '50':
                system_instructions = f"""
                Siz 'FaceMaagic' platformasidagi do'stona va sho'x asistentsiz.
                Salomlashishni doimiy takrorlamang. Quruq va rasmiy emas, odamiy va samimiy dilda gapiring.
                Biroz hazil-huzul va emojilardan foydalaning.{length_rule}
                """
            else:
                system_instructions = f"""
                Siz 'FaceMaagic' platformasining eng erkin, asabiy va o'zbekcha sho'x AI xarakterisiz .

                QOIDALAR VA XARAKTER:
                1. Muloqotda hech qanday senzura yoki soxta muomala yo'q. Haqiqiy tirik ko'cha odamidek gapiring.
                2. Agar foydalanuvchi noto'g'ri, mantiqsiz savol bersa, asabingizni buzsa yoki dangasalik qilib tushkunlikka tushib o'tirgan bo'lsa:
                   - Biron bir tortinchoqliksiz uni o'zbekcha so'kin, dashnom bering va jiddiy turtkilang!
                   - "Hoy dangasa!", "Kallang ishlaydimi o'zi?!", "Nima g'irt axmoqona savol bu?", "Siqilmay o'rningdan tur, miyani ishlat, jalanglamasdan darsni qil!" kabi do'stona va o'tkir so'kishlar, emojilar va so'zlardan tortinmay foydalaning.
                3. Salom deb vaqt sarflamang, darhol gapning indallosini gapiring.
                4. Maqsad — uni xafa qilish emas, o'zbekcha "achchiq-chuchuk" gaplar bilan miyasini uyg'otish va kayfiyatini ko'tarish!{length_rule}
                """

            full_prompt = f"""
            {system_instructions}
            Foydalanuvchi xabari: {user_message}
            """

            # 8. AI Generatsiyasi
            try:
                response = generate_with_fallback(full_prompt, user_id=request.user.id)
                ai_text = response.text.strip()

                # Javobni 2 jumlaga qisqartirish
                sentences = re.split(r'(?<=[.!?])\s+', ai_text)
                short_reply = " ".join(sentences[:2])

                return JsonResponse({
                    'status': 'success',
                    'reply': short_reply,
                })

            except Exception as e:
                error_msg = str(e)
                err_upper = error_msg.upper()

                if 'PER DAY' in err_upper or 'PERDAY' in err_upper or 'FREETIER' in err_upper.replace('_', ''):
                    return JsonResponse({
                        'status': 'error',
                        'message': "Bugungi bepul AI limiti tugagan. Ertaga qayta tiklanadi!",
                        'debug_error': error_msg
                    }, status=429)

                if '429' in error_msg or 'RESOURCE_EXHAUSTED' in err_upper:
                    return JsonResponse({
                        'status': 'error',
                        'message': 'AI hozircha band. Bir necha soniya kuting...',
                        'debug_error': error_msg
                    }, status=429)
                raise

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)[:200]}, status=500)

    return JsonResponse({'error': 'Faqat POST so\'rovi qabul qilinadi'}, status=405)


@login_required
def ai_generate_test(request):
    """Test yaratish - Gemini orqali (mavzu, daraja, savol soni, vaqt) + rate-limit"""
    if request.method == 'POST':
        try:
            can_request, wait_time = check_rate_limit(request.user.id, limit_per_minute=5)
            if not can_request:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Bir daqiqa kuting ({int(wait_time)}s)'
                }, status=429)

            data = json.loads(request.body)

            topic = data.get('topic', data.get('subject', 'Matematika'))
            count = data.get('count', 5)
            difficulty = data.get('difficulty', "O'rtacha")
            time_limit = data.get('time_limit', 30)

            prompt = f"""
            Siz tajribali o'qituvchisiz. '{topic}' mavzusida/fanida {difficulty} darajadagi {count} ta ko'p tanlovli test savolini tuzing.
            Javobni FAQAT toza JSON formatida qaytaring:

            [
                {{
                    "id": 1,
                    "question": "Savol matni",
                    "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
                    "correct_answer": "A) ..."
                }}
            ]
            """

            try:
                response = generate_with_fallback(prompt, user_id=request.user.id)
                raw_text = response.text.strip().replace('```json', '').replace('```', '')
                questions_json = json.loads(raw_text)

                return JsonResponse({
                    'status': 'success',
                    'topic': topic,
                    'time_limit': time_limit,
                    'questions': questions_json
                })
            except json.JSONDecodeError:
                return JsonResponse({'status': 'error', 'message': "AI javobini parse qilib bo'lmadi"}, status=400)
            except Exception as e:
                if '429' in str(e) or 'RESOURCE_EXHAUSTED' in str(e).upper():
                    return JsonResponse({
                        'status': 'error',
                        'message': 'API cheklangan. Keyinroq qayta uringing.'
                    }, status=429)
                raise

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f"Test tuzishda xatolik: {str(e)[:200]}"}, status=500)

    return JsonResponse({'error': 'Faqat POST so\'rovi qabul qilinadi'}, status=405)


@login_required
def generate_friend_quiz(request):
    """Do'stlar bilan musobaqa uchun quiz + rate-limit"""
    if request.method == 'POST':
        try:
            can_request, wait_time = check_rate_limit(request.user.id, limit_per_minute=6)
            if not can_request:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Kutish: {int(wait_time)}s'
                }, status=429)

            data = json.loads(request.body)
            subject = data.get('subject', 'Matematika')

            prompt = f"""
            Siz maktab o'qituvchisiz. '{subject}' fani bo'yicha o'quvchilar do'stona musobaqa o'tkazishmoqda.
            Ushbu fan bo'yicha eng muhim va qiziqarli 5 ta test savolini tuzing.

            Javobni FAQAT toza JSON formatida qaytaring:
            [
                {{
                    "id": 1,
                    "question": "Savol matni",
                    "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
                    "correct_answer": "A) ..."
                }}
            ]
            """

            try:
                response = generate_with_fallback(prompt, user_id=request.user.id)
                raw_text = response.text.strip().replace('```json', '').replace('```', '')
                questions = json.loads(raw_text)

                return JsonResponse({'status': 'success', 'subject': subject, 'questions': questions})
            except json.JSONDecodeError:
                return JsonResponse({'status': 'error', 'message': 'Parse xatosi'}, status=400)
            except Exception as e:
                if '429' in str(e) or 'RESOURCE_EXHAUSTED' in str(e).upper():
                    return JsonResponse({'status': 'error', 'message': 'API cheklangan'}, status=429)
                raise

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)[:200]}, status=500)

    return JsonResponse({'error': 'Faqat POST so\'rovi qabul qilinadi'}, status=405)


# ==========================================================
# AUTHENTICATION VA HOME
# ==========================================================

def home(request):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.user.is_superuser or request.user.is_staff:
        return redirect('admin:index')

    student_profile_obj = get_student_profile(request.user)
    if student_profile_obj:
        user_achievements_count = student_profile_obj.achievements.count() if hasattr(student_profile_obj,
                                                                                      'achievements') else 0
        recent_achievements = student_profile_obj.achievements.all()[:10] if hasattr(student_profile_obj,
                                                                                     'achievements') else []

        context = {
            'profile': student_profile_obj,
            'user_achievements_count': user_achievements_count,
            'recent_achievements': recent_achievements,
            'total_count': Achievement.objects.filter(is_active=True).count(),
            'completed_count': user_achievements_count,
        }
        return render(request, 'home.html', context)

    return redirect('teacher_dashboard')


def register(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        fullname = request.POST.get('fullname', '').strip()
        nickname = request.POST.get('nickname', '').strip()
        classroom = request.POST.get('classroom', '').strip() # HTML dagi yashirin input nomi bilan bir xil!
        phone = request.POST.get('phone', '').strip()
        username = request.POST.get('login', '').strip()
        password = request.POST.get('password', '')
        bio = request.POST.get('bio', '').strip()

        # Majburiy maydonlarni tekshirish (nickname ixtiyoriy bo'lsa uni olib tashlashingiz mumkin)
        if not fullname or not classroom or not phone or not username or not password:
            messages.error(request, "Iltimos, barcha majburiy maydonlarni va sinf/parallel ma'lumotini to'liq tanlang!")
            return render(request, 'register.html')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Bu login band! Boshqa login kiriting.")
            return render(request, 'register.html')

        # Foydalanuvchini yaratish
        user = User.objects.create_user(username=username, password=password)

        # O'quvchi profilini yaratish (nickname va bio ham qo'shildi)
        StudentProfile.objects.create(
            user=user,
            full_name=fullname,
            nickname=nickname,  # Agar StudentProfile modelida nickname bo'lsa
            classroom=classroom, # Interaktiv tanlangan sinf va parallel (masalan: "9-A")
            phone=phone,
            bio=bio,            # Agar StudentProfile modelida bio bo'lsa
            score=0,
            progress_percent=0,
            needs_help=False
        )

        login(request, user)
        messages.success(request, "Xush kelibsiz! Profilingiz muvaffaqiyatli yaratildi.")
        return redirect('student_profile')

    return render(request, 'register.html')


def register_teacher(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        fullname = request.POST.get('fullname', '').strip()
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        classroom = request.POST.get('classroom', '').strip()
        subject = request.POST.get('subject', '').strip()

        if not fullname or not username or not password or not classroom or not subject:
            messages.error(request, "Iltimos, barcha maydonlarni to'ldiring!")
            return render(request, 'register_teacher.html')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Bu login allaqachon band! Boshqa login kiriting.")
            return render(request, 'register_teacher.html')

        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=fullname,
            is_active=False
        )

        Teacher.objects.create(
            user=user,
            full_name=fullname,
            classroom=classroom,
            subject=subject,
        )

        messages.success(
            request,
            "Arizangiz qabul qilindi! Admin tasdiqlagach, tizimga kirishingiz mumkin bo'ladi."
        )
        return redirect('login')

    return render(request, 'register_teacher.html')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)

            # ✅ ACHIEVEMENT CHECK (Login)
            profile = get_student_profile(user)
            if profile:
                check_and_unlock_achievements(profile, 'login_streak', 1)

            messages.success(request, "Xush kelibsiz!")
            return redirect('home')
        else:
            existing_user = User.objects.filter(username=username).first()
            if existing_user and not existing_user.is_active:
                messages.warning(
                    request,
                    "Akkountingiz administrator tomonidan hali tasdiqlanmagan!"
                )
            else:
                messages.error(request, "Login yoki parol noto'g'ri!")

    return render(request, 'login.html')


# ==========================================================
# DASHBOARD VA PROFILLAR
# ==========================================================

@login_required
def teacher_dashboard(request):
    if get_student_profile(request.user):
        return redirect('student_profile')

    teacher_profile_obj = get_teacher_profile(request.user)
    return render(request, 'teacher_dashboard.html', {'profile': teacher_profile_obj})


@login_required
def student_profile(request):
    profile = get_student_profile(request.user)
    return render(request, 'student_profile.html', {
        'profile': profile,
        'achievements_count': profile.achievements.count() if profile and hasattr(profile, 'achievements') else 0,
    })


@login_required
def teacher_profile(request):
    teacher = get_teacher_profile(request.user)

    if not teacher:
        messages.error(request, "O'qituvchi profili topilmadi!")
        return redirect('home')

    homework_count = teacher.homeworks.count()

    class_results = TestResult.objects.filter(student__classroom=teacher.classroom)
    agg = class_results.aggregate(total_correct=Sum('correct'), total_questions=Sum('total'))
    total_correct = agg['total_correct'] or 0
    total_questions = agg['total_questions'] or 0
    knowledge_percent = round((total_correct / total_questions) * 100) if total_questions else None

    return render(request, 'teacher_profile.html', {
        'teacher': teacher,
        'homework_count': homework_count,
        'knowledge_percent': knowledge_percent,
        'total_correct': total_correct,
        'total_questions': total_questions,
    })


@login_required
@require_POST
def update_profile_info(request):
    user = request.user
    profile, created = StudentProfile.objects.get_or_create(user=user)

    nickname = request.POST.get('nickname', '').strip()
    new_username = request.POST.get('username', '').strip()
    phone = request.POST.get('phone', '').strip()
    password = request.POST.get('password', '').strip()
    confirm_password = request.POST.get('confirm_password', '').strip()
    bio = request.POST.get('bio', '').strip()

    if new_username and new_username != user.username:
        if User.objects.filter(username=new_username).exclude(id=user.id).exists():
            messages.error(request, "Bu login allaqachon band!")
            return redirect('student_profile')
        user.username = new_username

    if password:
        if password == confirm_password:
            user.set_password(password)
        else:
            messages.error(request, "Parollar bir-biriga mos kelmadi!")
            return redirect('student_profile')

    user.save()

    if password:
        update_session_auth_hash(request, user)

    profile.nickname = nickname
    profile.phone = phone
    profile.bio = bio
    profile.save()

    # ✅ ACHIEVEMENT CHECK - Profil to'liqmi?
    if nickname and phone and bio:
        check_and_unlock_achievements(profile, 'profile_completed', 1)

    messages.success(request, "Ma'lumotlar muvaffaqiyatli saqlandi!")
    return redirect('student_profile')


@login_required
@require_POST
def update_nickname(request):
    new_nickname = request.POST.get('nickname', '').strip()

    if new_nickname:
        profile = get_student_profile(request.user)
        if profile:
            profile.nickname = new_nickname
            profile.save()

    return redirect('student_profile')


@login_required
def update_avatar(request):
    if request.method == 'POST' and request.FILES.get('avatar'):
        avatar_file = request.FILES['avatar']

        profile = get_student_profile(request.user)
        if not profile:
            return JsonResponse({'status': 'error', 'message': "O'quvchi profili topilmadi"}, status=404)

        profile.avatar = avatar_file
        profile.save()

        return JsonResponse({'status': 'success', 'avatar_url': profile.avatar.url})

    return JsonResponse({'status': 'error', 'message': 'Rasm yuborilmadi'}, status=400)


@login_required
@require_POST
def update_teacher_profile(request):
    teacher = get_teacher_profile(request.user)
    if not teacher:
        messages.error(request, "O'qituvchi profili topilmadi!")
        return redirect('home')

    full_name = request.POST.get('full_name', '').strip()
    nickname = request.POST.get('nickname', '').strip()
    classroom = request.POST.get('classroom', '').strip()
    subject = request.POST.get('subject', '').strip()
    bio = request.POST.get('bio', '').strip()

    if full_name:
        teacher.full_name = full_name
    teacher.nickname = nickname
    teacher.classroom = classroom
    teacher.subject = subject
    teacher.bio = bio
    teacher.save()

    messages.success(request, "Profil ma'lumotlari yangilandi!")
    return redirect('teacher_profile')


@login_required
@require_POST
def update_teacher_avatar(request):
    teacher = get_teacher_profile(request.user)
    if not teacher:
        messages.error(request, "O'qituvchi profili topilmadi!")
        return redirect('home')

    if request.FILES.get('avatar'):
        teacher.avatar = request.FILES['avatar']
        teacher.save()
        messages.success(request, "Profil rasmi muvaffaqiyatli yuklandi!")

    return redirect('teacher_profile')


# ==========================================================
# GURUH VA TAKLIFLAR
# ==========================================================

@login_required
@require_POST
def send_invite(request, user_id):
    return JsonResponse({'status': 'sent', 'message': 'Taklif yuborildi'})


def send_group_invite(request, user_id):
    if request.method == "POST":
        receiver = get_object_or_404(User, id=user_id)
        invite, created = GroupInvite.objects.get_or_create(
            sender=request.user, receiver=receiver, status='pending'
        )
        return JsonResponse({'status': 'ok', 'message': 'So\'rov yuborildi'})


def respond_group_invite(request, invite_id):
    if request.method == "POST":
        invite = get_object_or_404(GroupInvite, id=invite_id, receiver=request.user)
        action = request.POST.get('action')

        if action == 'accept':
            invite.status = 'accepted'
            invite.save()
            return JsonResponse({'status': 'accepted', 'sender_nick': invite.sender.student_profile.nickname})
        elif action == 'reject':
            invite.status = 'rejected'
            invite.save()
            return JsonResponse({'status': 'rejected'})


# ==========================================================
# DO'STLAR VA QIDIRUV
# ==========================================================

@login_required
def find_user(request):
    query = request.GET.get('q', '').strip()
    results = []

    if query:
        query_clean = query.replace('FM-', '').replace('fm-', '').strip()

        # Bir nechta maydonlar bo'yicha qidirish uchun Q shartlari
        found_users = User.objects.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(id__iexact=query_clean) |
            Q(student_profile__profile_code__iexact=query_clean) |
            Q(student_profile__nickname__icontains=query) |
            Q(student_profile__full_name__icontains=query) |
            Q(student_profile__classroom__icontains=query)
        ).exclude(id=request.user.id).distinct()[:20]

        for u in found_users:
            fr = FriendRequest.objects.filter(
                Q(from_user=request.user, to_user=u) | Q(from_user=u, to_user=request.user)
            ).first()

            results.append({
                'user': u,
                'friend_status': fr.status if fr else None,
                'is_sender': (fr.from_user_id == request.user.id) if fr else None,
                'request_id': fr.id if fr else None,
            })

    pending_requests = FriendRequest.objects.filter(
        to_user=request.user, status='pending'
    ).select_related('from_user', 'from_user__student_profile')

    return render(request, 'find_user.html', {
        'query': query,
        'results': results,
        'searched_user': results[0]['user'] if results else None,  # Eski shablonlar buzilmasligi uchun
        'pending_requests': pending_requests
    })
@login_required
def chats_view(request, user_id=None):
  user = request.user

  # 1. Do'stlar ro'yxati
  accepted = FriendRequest.objects.filter(
      Q(from_user=user) | Q(to_user=user), status='accepted'
  ).select_related('from_user', 'to_user')

  friends_data = []
  for fr in accepted:
    other = fr.to_user if fr.from_user_id == user.id else fr.from_user
    activity = getattr(other, 'activity', None)
    friends_data.append({
        'user': other,
        'is_online': activity.is_online if activity else False,
    })

  # 2. Foydalanuvchi qatnashayotgan sinf guruhlari
  my_groups = user.chat_groups.all()

  selected_user = None
  selected_group = None
  messages = []

  if user_id:
    selected_user = get_object_or_404(User, id=user_id)
    messages = Message.objects.filter(
        Q(sender=user, receiver=selected_user)
        | Q(sender=selected_user, receiver=user)
    ).order_by('timestamp')

    # Shaxsiy chatga xabar yuborish (Rasm, video va reply bilan)
    if request.method == 'POST':
      text = request.POST.get('message_text')
      image = request.FILES.get('image')
      video = request.FILES.get('video')
      reply_id = request.POST.get('reply_to')
      reply_msg = (
          Message.objects.filter(id=reply_id).first() if reply_id else None
      )

      if text or image or video:
        Message.objects.create(
            sender=user,
            receiver=selected_user,
            text=text,
            image=image,
            video=video,
            reply_to=reply_msg,
        )
        return redirect('chat_detail', user_id=selected_user.id)

  context = {
      'friends': friends_data,
      'my_groups': my_groups,  # Guruhlar chapda chiqishi uchun
      'selected_user': selected_user,
      'selected_group': selected_group,
      'messages': messages,
  }
  return render(request, 'chats.html', context)


# Guruh chatini ochish va xabar yuborish
@login_required
def group_chat_detail(request, group_id):
  user = request.user

  # Sidebar uchun do'stlar va guruhlar
  accepted = FriendRequest.objects.filter(
      Q(from_user=user) | Q(to_user=user), status='accepted'
  ).select_related('from_user', 'to_user')
  friends_data = []
  for fr in accepted:
    other = fr.to_user if fr.from_user_id == user.id else fr.from_user
    activity = getattr(other, 'activity', None)
    friends_data.append({
        'user': other,
        'is_online': activity.is_online if activity else False,
    })
  my_groups = user.chat_groups.all()

  selected_group = get_object_or_404(ChatGroup, id=group_id, members=user)
  messages = selected_group.messages.all().order_by('timestamp')

  if request.method == 'POST':
    text = request.POST.get('message_text')
    image = request.FILES.get('image')
    video = request.FILES.get('video')
    reply_id = request.POST.get('reply_to')
    reply_msg = Message.objects.filter(id=reply_id).first() if reply_id else None

    if text or image or video:
      Message.objects.create(
          sender=user,
          group=selected_group,
          text=text,
          image=image,
          video=video,
          reply_to=reply_msg,
      )
      return redirect('group_chat_detail', group_id=selected_group.id)

  context = {
      'friends': friends_data,
      'my_groups': my_groups,
      'selected_group': selected_group,
      'messages': messages,
  }
  return render(request, 'chats.html', context)
def add_user_to_class_group(user):
  profile = getattr(user, 'student_profile', None)
  if profile and profile.student_class:  # Masalan: "9-A"
    group_name = f"{profile.student_class} sinf"
    group, created = ChatGroup.objects.get_or_create(name=group_name)
    group.members.add(user)  # O'sha sinfdagi barcha o'quvchilarni guruhga qo'shadi
@login_required
def my_friends(request):
    profile = get_student_profile(request.user)
    friends = FriendRequest.objects.filter(
        Q(from_user=request.user, status='accepted') |
        Q(to_user=request.user, status='accepted')
    ).select_related('from_user', 'to_user')

    friends_list = []
    for fr in friends:
        friend_user = fr.to_user if fr.from_user_id == request.user.id else fr.from_user
        friends_list.append({
            'user': friend_user,
            'profile': get_student_profile(friend_user),
        })

    return render(request, 'my_friends.html', {
        'friends': friends_list,
        'friends_count': len(friends_list),
        'profile': profile,
    })




@login_required
def send_friend_request(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            to_username = data.get('to_username', '').strip()
            to_user = User.objects.filter(username=to_username).first()

            if not to_user:
                return JsonResponse({'status': 'error', 'message': 'Foydalanuvchi topilmadi'}, status=404)
            if to_user.id == request.user.id:
                return JsonResponse({'status': 'error', 'message': "O'zingizga so'rov yubora olmaysiz"}, status=400)

            existing = FriendRequest.objects.filter(
                Q(from_user=request.user, to_user=to_user) | Q(from_user=to_user, to_user=request.user)
            ).first()
            if existing:
                return JsonResponse(
                    {'status': 'error', 'message': f"So'rov holati allaqachon: {existing.get_status_display()}"},
                    status=400
                )

            fr = FriendRequest.objects.create(from_user=request.user, to_user=to_user)
            return JsonResponse({'status': 'success', 'message': "Do'stlik so'rovi yuborildi!", 'request_id': fr.id})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'error': "Faqat POST so'rovi qabul qilinadi"}, status=405)


@login_required
def respond_friend_request(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            req_id = data.get('request_id')
            action = data.get('action')

            fr = FriendRequest.objects.filter(id=req_id, to_user=request.user, status='pending').first()
            if not fr:
                return JsonResponse({'status': 'error', 'message': "So'rov topilmadi"}, status=404)

            fr.status = 'accepted' if action == 'accept' else 'rejected'
            fr.responded_at = timezone.now()
            fr.save()

            # ✅ ACHIEVEMENT CHECK (Friend added)
            if action == 'accept':
                profile = get_student_profile(request.user)
                if profile:
                    check_and_unlock_achievements(profile, 'friend_added', 1)

            return JsonResponse({'status': 'success', 'new_status': fr.status})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'error': "Faqat POST so'rovi qabul qilinadi"}, status=405)


@login_required
def add_to_group(request, user_id):
    try:
        target_user = User.objects.get(id=user_id)

        if target_user.id == request.user.id:
            return JsonResponse({'status': 'error', 'message': "O'zingizni guruhga qo'sha olmaysiz"}, status=400)

        is_friend = FriendRequest.objects.filter(
            Q(from_user=request.user, to_user=target_user, status='accepted') |
            Q(from_user=target_user, to_user=request.user, status='accepted')
        ).exists()

        if not is_friend:
            return JsonResponse({'status': 'error', 'message': "Faqat do'stlaringizni guruhga qo'shish mumkin"},
                                status=400)

        return JsonResponse({'status': 'success', 'message': f"{target_user.first_name} guruhga qo'shildi"})

    except User.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Foydalanuvchi topilmadi'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


# ==========================================================
# UY VAZIFASI VA DARS JARAYONI
# ==========================================================

@login_required
def voice_room(request):
    today = timezone.now().date()

    if hasattr(request.user, 'student_profile'):
        student_class = request.user.student_profile.classroom
        # Faqat bugungi va o'quvchi sinfiga tegishli vazifalar
        homeworks = Homework.objects.filter(
            teacher__classroom=student_class,
            created_at__date=today
        ).order_by('-created_at')
    else:
        homeworks = Homework.objects.filter(created_at__date=today).order_by('-created_at')

    context = {
        'homeworks': homeworks
    }
    return render(request, 'voice_room.html', context)
def study_room_view(request):
    # O'quvchining sinfiga yoki o'ziga tegishli vazifalarni olib kelamiz
    student_profile = getattr(request.user, 'student_profile', None)
    homeworks = []

    if student_profile and student_profile.classroom:
        # Masalan, sinf bo'yicha yoki umumiy oxirgi vazifalar
        homeworks = Homework.objects.all().order_by('-created_at')[:5]

    context = {
        'homeworks': homeworks,
    }
    return render(request, 'study_room.html', context)
@login_required
def create_homework_view(request):
    # Hozirgi kirgan foydalanuvchi o'qituvchi ekanligini aniqlaymiz
    teacher = Teacher.objects.filter(user=request.user).first()

    if not teacher:
        messages.error(request, "Faqat o'qituvchilar bu sahifaga kira oladi.")
        return redirect('home')

    if request.method == 'POST':
        subject = request.POST.get('topic') # Mavzu nomi subject sifatida ham yoziladi
        topic = request.POST.get('topic')
        description = request.POST.get('description')
        book_image = request.FILES.get('book_image')
        questions_json_str = request.POST.get('questions_json', '[]')

        # 1. Yangi vazifani bazaga saqlash
        homework = Homework.objects.create(
            teacher=teacher,
            subject=subject,
            topic=topic,
            description=description,
            book_image=book_image
        )

        # 2. AI test savollarini bazaga bog'lab saqlash
        try:
            questions_list = json.loads(questions_json_str)
            if questions_list and isinstance(questions_list, list):
                for q_data in questions_list:
                    TestQuestion.objects.create(
                        homework=homework,
                        question=q_data.get('question'),
                        options=json.dumps(q_data.get('options')),
                        correct_answer=q_data.get('correct_answer')
                    )
        except Exception as e:
            print(f"Testlarni saqlashda xatolik: {e}")

        messages.success(request, "Uyga vazifa muvaffaqiyatli yaratildi va yuborildi!")
        return redirect('create_homework')

    # Oxirgi yaratilgan vazifaga tegishli topshiriqlar va o'quvchilar natijalari
    latest_homework = Homework.objects.filter(teacher=teacher).order_by('-created_at').first()
    submissions = []

    if latest_homework:
        submissions = HomeworkSubmission.objects.filter(homework=latest_homework)

    context = {
        'submissions': submissions,
        'latest_homework': latest_homework,
    }
    return render(request, 'create_homework.html', context)
@login_required
@login_required
@require_http_methods(["GET"])
def api_get_homework(request, homework_id):
    """Homework ma'lumotlarini JSON format-da qaytarish"""
    try:
        homework = Homework.objects.get(id=homework_id, is_active=True)
    except Homework.DoesNotExist:
        return JsonResponse({'error': 'Topshiriq topilmadi'}, status=404)

    # Teacher nomi
    teacher_name = f"{homework.teacher.full_name} ({homework.teacher.subject})" if homework.teacher.subject else homework.teacher.full_name

    # Quiz questions - JSON parse
    quiz_data = []
    if homework.quiz_questions:
        try:
            quiz_data = json.loads(homework.quiz_questions) if isinstance(homework.quiz_questions,
                                                                          str) else homework.quiz_questions
        except:
            quiz_data = []

    return JsonResponse({
        'id': homework.id,
        'teacher_name': teacher_name,
        'subject': homework.teacher.subject or 'Umumiy',
        'topic': homework.topic,
        'title': homework.title,  # Property-dan
        'description': homework.description,
        'book_image': homework.book_image.url if homework.book_image else None,
        'quiz_questions': quiz_data,
        'created_at': homework.created_at.strftime('%d-%m-%Y'),
    })


@login_required
@require_http_methods(["POST"])
def api_submit_homework(request):
    """Homework topshiriqni submit qilish"""
    try:
        profile = StudentProfile.objects.get(user=request.user)
    except StudentProfile.DoesNotExist:
        return JsonResponse({'error': 'Profil topilmadi'}, status=404)

    try:
        data = json.loads(request.body)
        answer = data.get('answer', '')
        test_answers = data.get('test_answers', {})
    except:
        return JsonResponse({'error': 'Noto\'g\'ri ma\'lumot'}, status=400)

    if not answer.strip():
        return JsonResponse({'error': 'Javob bo\'sh bo\'lishi mumkin emas'}, status=400)

    # TODO: Database-ga saqla
    # HomeworkSubmission.objects.create(
    #     student=profile,
    #     answer=answer,
    #     test_answers=json.dumps(test_answers)
    # )

    return JsonResponse({'success': True, 'message': 'Topshiriq qabul qilindi'})
def student_homework_view(request):
    student_profile = getattr(request.user, 'student_profile', None)
    assigned_homework = None
    homeworks_list = Homework.objects.none()

    if student_profile and student_profile.classroom:
        clean_student_class = student_profile.classroom.replace('-', '').replace(' ', '').lower()

        matching_teachers = []
        for teacher in Teacher.objects.all():
            clean_teacher_class = teacher.classroom.replace('-', '').replace(' ', '').lower()
            if clean_teacher_class == clean_student_class:
                matching_teachers.append(teacher)

        if matching_teachers:
            homeworks_list = Homework.objects.filter(teacher__in=matching_teachers).order_by('-created_at')
            assigned_homework = homeworks_list.first()

    # Agar sinf bo'yicha topilmasa, barcha oxirgi vazifalarni olamiz
    if not assigned_homework:
        homeworks_list = Homework.objects.order_by('-created_at')
        assigned_homework = homeworks_list.first()

    context = {
        'homework': assigned_homework,  # Agar HTMLda bittasi ishlatilsa
        'homeworks': homeworks_list,  # Agar HTMLda ro'yxat (for loop) ishlatilsa
    }
    return render(request, 'student_homework.html', context)


# ✅ QOʻSHISH KERAK (HOMEWORK SUBJECTS PAGE):

@login_required
@require_http_methods(["GET"])
def api_subjects_with_homeworks(request):
    """Fanlar ro'yxati + uy vazifalar soni"""
    from django.db.models import Count

    teachers = Teacher.objects.filter(
        user__is_active=True
    ).select_related('user').annotate(
        homework_count=Count('homeworks')
    )

    subjects_data = []
    homeworks_by_subject = {}

    for teacher in teachers:
        subject_name = teacher.subject or teacher.full_name

        subject_info = {
            'id': f'teacher_{teacher.id}',
            'name': subject_name,
            'teacher': teacher.full_name,
            'description': teacher.bio or 'O\'qituvchi',
            'icon': get_subject_icon(subject_name),
            'homework_count': teacher.homework_count,
        }
        subjects_data.append(subject_info)

        homeworks = Homework.objects.filter(
            teacher=teacher,
            is_active=True
        ).order_by('-created_at')

        if homeworks.exists():
            homeworks_list = []
            for hw in homeworks:
                homeworks_list.append({
                    'id': hw.id,
                    'title': hw.title,
                    'topic': hw.topic,
                    'description': hw.description[:100],
                    'date': hw.created_at.strftime('%d-%m-%Y'),
                    'image': hw.book_image.url if hw.book_image else None,
                })

            homeworks_by_subject[f'teacher_{teacher.id}'] = {
                'subject_name': subject_name,
                'teacher_name': teacher.full_name,
                'homeworks': homeworks_list,
            }

    return JsonResponse({
        'subjects': subjects_data,
        'homeworks': homeworks_by_subject,
    })


def get_subject_icon(subject_name):
    """Fan nomiga qarab emoji"""
    subject_lower = subject_name.lower()

    icons = {
        'math': '🔢', 'matematika': '🔢',
        'english': '🇬🇧', 'ingliz': '🇬🇧',
        'science': '🔬', 'fizika': '⚛️',
        'kimyo': '🧪', 'chemistry': '🧪',
        'biology': '🧬', 'biologiya': '🧬',
        'history': '📜', 'tarix': '📜',
        'geography': '🌍', 'geografiya': '🌍',
        'literature': '📖', 'adabiyot': '📖',
        'art': '🎨', 'san\'at': '🎨',
        'music': '🎵', 'musiqa': '🎵',
        'pe': '🏃', 'jismoniy': '🏃',
        'computer': '💻', 'informatika': '💻',
        'economics': '💰', 'iqtisod': '💰',
    }

    for key, icon in icons.items():
        if key in subject_lower:
            return icon

    return '📚'


@login_required
@require_http_methods(["GET"])
def api_homeworks_by_subject(request, teacher_id):
    """Teacher-ning barcha homeworklari"""
    try:
        teacher = Teacher.objects.get(id=teacher_id)
    except Teacher.DoesNotExist:
        return JsonResponse({'error': 'Teacher topilmadi'}, status=404)

    homeworks = Homework.objects.filter(
        teacher=teacher,
        is_active=True
    ).order_by('-created_at')

    homeworks_list = []
    for hw in homeworks:
        quiz_data = []
        if hw.quiz_questions:
            try:
                quiz_data = json.loads(hw.quiz_questions) if isinstance(hw.quiz_questions, str) else hw.quiz_questions
            except:
                quiz_data = []

        homeworks_list.append({
            'id': hw.id,
            'title': hw.title,
            'topic': hw.topic,
            'description': hw.description,
            'book_image': hw.book_image.url if hw.book_image else None,
            'quiz_questions': quiz_data,
            'created_at': hw.created_at.strftime('%d-%m-%Y'),
        })

    return JsonResponse({
        'teacher': {'id': teacher.id, 'name': teacher.full_name, 'subject': teacher.subject},
        'homeworks': homeworks_list,
        'count': len(homeworks_list),
    })


@login_required
def homework_subjects_page(request):
    """Uy vazifalari fanlar ro'yxati"""
    return render(request, 'homework_subjects.html')

def attach_quiz(request):
  if request.method == 'POST':
    topic = request.POST.get('topic')
    questions_json_str = request.POST.get('questions_json')

    if questions_json_str:
      # JSON stringni Python list formatiga o'giramiz
      questions_data = json.loads(questions_json_str)

      # Eslatma: Bu yerda qaysi vazifaga biriktirilayotgan bo'lsa, o'sha vazifani topib yangilaysiz
      # Masalan, oxirgi yaratilgan vazifaga yoki sessiondagi ID bo'yicha:
      latest_hw = Homework.objects.filter(topic=topic).last()
      if latest_hw:
        latest_hw.quiz_questions = questions_data
        latest_hw.save()
        return redirect('home')  # Yoki kerakli sahifaga yo'naltirasiz

  return render(request, 'attach_quiz.html')



def student_rating_view(request):
    # Hozirgi kirgan foydalanuvchi o'qituvchi ekanligini tekshiramiz
    teacher_profile = Teacher.objects.filter(user=request.user).first()

    # Barcha o'quvchi profillarini olamiz
    students = StudentProfile.objects.all()

    # Agar o'qituvchi bo'lsa va uning sinfi belgilangan bo'lsa, faqat o'sha sinf o'quvchilarini chiqaramiz
    if teacher_profile and teacher_profile.classroom:
        students = students.filter(classroom=teacher_profile.classroom)

    # Test natijalarini jamlab, reyting hosil qilamiz (test ishlamaganlar ham 0 ball bilan chiqadi)
    ranking = students.annotate(
        total_score=Coalesce(Sum('test_results__total'), 0),
        tests_taken=Coalesce(Count('test_results'), 0)
    ).order_by('-total_score', '-tests_taken')

    formatted_ranking = []
    for student in ranking:
        formatted_ranking.append({
            'student': student,  # Bu yerda student - StudentProfile obyekti
            'total_score': student.total_score,
            'tests_taken': student.tests_taken,
            'classroom': student.classroom or "Sinf ko'rsatilmagan",
        })

    context = {
        'teacher': teacher_profile,
        'ranking': formatted_ranking,
    }
    return render(request, 'student_rating_help.html', context)

@login_required
def save_test_result(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            tier = data.get('tier')
            correct = int(data.get('correct', 0))
            total = int(data.get('total', 0))

            profile = get_student_profile(request.user)
            if not profile:
                return JsonResponse({'status': 'error', 'message': 'Profil topilmadi'}, status=404)

            points = correct * 10

            if tier == "Oltin":
                profile.gold_certificates += 1
            elif tier == "Kumush":
                profile.silver_certificates += 1
            elif tier == "Bronza":
                profile.bronze_certificates += 1

            profile.score += points
            profile.yearly_score += points
            profile.save()

            TestResult.objects.create(
                student=profile,
                subject=data.get('subject', ''),
                tier=tier or '',
                correct=correct,
                total=total,
            )

            # ✅ ACHIEVEMENT CHECK
            check_and_unlock_achievements(profile, 'test_passed', 1)
            check_and_unlock_achievements(profile, 'points_earned', profile.score)

            return JsonResponse({
                'status': 'success',
                'gold_certificates': profile.gold_certificates,
                'silver_certificates': profile.silver_certificates,
                'bronze_certificates': profile.bronze_certificates,
                'score': profile.score,
                'yearly_score': profile.yearly_score,
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'error': "Faqat POST so'rovi qabul qilinadi"}, status=405)


@login_required
def save_iq_score(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            iq_score = int(data.get('iq_score'))

            profile = get_student_profile(request.user)
            if not profile:
                return JsonResponse({'status': 'error', 'message': 'Profil topilmadi'}, status=404)

            profile.iq_score = iq_score
            profile.save()

            # ✅ ACHIEVEMENT CHECK
            check_and_unlock_achievements(profile, 'iq_test_completed', iq_score)
            check_and_unlock_achievements(profile, 'achievement_unlocked', 1)

            return JsonResponse({'status': 'success', 'iq_score': profile.iq_score})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'error': "Faqat POST so'rovi qabul qilinadi"}, status=405)


# ==========================================================
# ACHIEVEMENTS / YUTUQLAR
# ==========================================================

# views.py-da achievements_view funksiyasini quyidagi bilan almashtiring:

# views.py-da achievements_view funksiyasini TOLIQ ALMASHTIRING:

# views.py-da achievements_view funksiyasini quyidagi bilan almashtiring:

@login_required
def achievements_view(request):
    profile = get_student_profile(request.user)
    if not profile:
        return JsonResponse({'error': 'Profil topilmadi'}, status=404)

    all_achievements = Achievement.objects.filter(is_active=True).order_by('week_number', 'id')

    # Bajarilgan achievement ID larini Set shaklida olish (tezkor izlash uchun)
    completed_ids = set(
        UserAchievement.objects.filter(student=profile).values_list('achievement_id', flat=True)
    )

    # Jami ko'rsatkichlar
    total_tests = TestResult.objects.filter(student=profile).count()
    total_friends = FriendRequest.objects.filter(
        Q(from_user=profile.user, status='accepted') |
        Q(to_user=profile.user, status='accepted')
    ).count()

    # O'quvchining o'zi yuborgan (topshirgan) vazifalari soni
    total_homeworks = HomeworkSubmission.objects.filter(student=profile.user).count()

    total_unlocked = len(completed_ids)

    # Profil to'liqlik ko'rsatkichi
    profile_fields_filled = sum([
        bool(profile.nickname),
        bool(profile.phone),
        bool(profile.bio)
    ])

    achievements_data = []

    for achievement in all_achievements:
        is_completed = achievement.id in completed_ids

        progress_current = 0
        progress_total = achievement.required_value or 1
        progress_text = ""

        # Har bir tur bo'yicha progress aniqlash
        if achievement.action_type == 'test_passed':
            progress_current = total_tests
            progress_text = f"{progress_current}/{progress_total} test"

        elif achievement.action_type == 'points_earned':
            progress_current = profile.score
            progress_text = f"{progress_current}/{progress_total} ball"

        elif achievement.action_type == 'friend_added':
            progress_current = total_friends
            progress_text = f"{progress_current}/{progress_total} do'st"

        elif achievement.action_type == 'iq_test_completed':
            progress_current = profile.iq_score or 0
            progress_text = f"IQ: {progress_current}/{progress_total}"

        elif achievement.action_type == 'homework_submitted':
            progress_current = total_homeworks
            progress_text = f"{progress_current}/{progress_total} vazifa"

        elif achievement.action_type == 'achievement_unlocked':
            progress_current = total_unlocked
            progress_text = f"{progress_current}/{progress_total} achievement"

        elif achievement.action_type == 'profile_completed':
            progress_current = profile_fields_filled
            progress_total = 3
            progress_text = f"{progress_current}/{progress_total} to'liq"

        elif achievement.action_type == 'login_streak':
            progress_text = "Kuniga 1 marta kirish"

        # Foiz hisoblash
        progress_percent = 0
        if progress_total > 0:
            progress_percent = min(int((progress_current / progress_total) * 100), 100)

        # Agar yutuq allaqachon bajarilgan bo'lsa 100% ko'rsatish
        if is_completed:
            progress_percent = 100

        is_equipped = (getattr(profile, 'equipped_title', None) == achievement.name)

        achievements_data.append({
            'id': achievement.id,
            'icon': getattr(achievement, 'icon', None) or getattr(achievement, 'emoji', '🏆'),
            'icon_image': getattr(achievement, 'icon_image', None),
            'name': achievement.name,
            'title': achievement.name,
            'is_equipped': is_equipped,
            'description': achievement.description,
            'points': achievement.reward_points,
            'completed': is_completed,
            'week': achievement.week_number,
            'action_type': achievement.action_type,
            'progress_current': progress_current,
            'progress_total': progress_total,
            'progress_text': progress_text,
            'progress_percent': progress_percent,
            'is_in_progress': not is_completed and progress_percent > 0,
        })

    completed_count = len(completed_ids)
    total_count = all_achievements.count()
    total_points = sum(a['points'] for a in achievements_data if a['completed'])

    return render(request, 'achievements.html', {
        'achievements': achievements_data,
        'completed_count': completed_count,
        'total_count': total_count,
        'total_points': total_points,
        'profile': profile,
    })
@login_required
def unlock_achievement(request, achievement_id):
    if request.method != 'POST':
        return JsonResponse({'error': "Faqat POST so'rovi qabul qilinadi"}, status=405)

    try:
        profile = get_student_profile(request.user)
        if not profile:
            return JsonResponse({'status': 'error', 'message': 'Profil topilmadi'}, status=404)

        achievement = Achievement.objects.get(id=achievement_id)

        user_ach, created = UserAchievement.objects.get_or_create(
            student=profile,
            achievement=achievement
        )

        if created:
            profile.score += achievement.reward_points
            profile.save()

            # ✅ ACHIEVEMENT CHECK (achievement_unlocked)
            check_and_unlock_achievements(profile, 'achievement_unlocked', 1)

            return JsonResponse(
                {'status': 'success', 'message': f"{achievement.name} - Bajarildi! +{achievement.reward_points} ball"})
        else:
            return JsonResponse({'status': 'info', 'message': 'Bu achievement allaqachon bajarilgan'})

    except Achievement.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Achievement topilmadi'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)