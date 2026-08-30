# ============================================================
# GEMINI 503 / 429 UCHUN BARQAROR FALLBACK KODI
# ============================================================
# views.py dagi `import time` qatorining yoniga qo‘shing:
import random


# .env faylida quyidagicha yozish mumkin:
# GEMINI_MODELS=gemini-3.6-flash,gemini-2.5-flash
# Agar faqat bitta model ishlatsangiz, GEMINI_MODEL yetarli bo‘ladi.
GEMINI_MODELS = [
    model_name.strip()
    for model_name in os.getenv("GEMINI_MODELS", "").split(",")
    if model_name.strip()
]

if not GEMINI_MODELS:
    GEMINI_MODELS = [GEMINI_MODEL]


TRANSIENT_GEMINI_ERRORS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "RESOURCE_EXHAUSTED",
    "UNAVAILABLE",
    "OVERLOADED",
    "HIGH DEMAND",
    "TEMPORARILY UNAVAILABLE",
)


def is_transient_gemini_error(error):
    """Vaqtinchalik API xatosini aniqlaydi."""
    error_text = str(error).upper()
    return any(code in error_text for code in TRANSIENT_GEMINI_ERRORS)


def generate_with_fallback(contents, model=None):
    """
    Gemini so‘rovi uchun:

    1. Har bir API keyni navbat bilan sinaydi.
    2. 503/429 kabi vaqtinchalik xatolarda 3 marta qayta urinadi.
    3. Har bir key uchun zaxira modellarni sinaydi.
    4. Keyingi urinishlar orasida exponential backoff ishlatadi.

    `model` berilsa faqat shu model ishlatiladi.
    """
    global _current_key_index

    if not GEMINI_API_KEYS:
        raise ValueError(
            "GEMINI_API_KEYS topilmadi! .env faylida kamida bitta kalit yozing."
        )

    models_to_try = [model] if model else GEMINI_MODELS
    models_to_try = [name for name in models_to_try if name]

    if not models_to_try:
        models_to_try = [GEMINI_MODEL]

    last_error = None
    total_keys = len(GEMINI_API_KEYS)
    max_attempts_per_model = 3

    for key_offset in range(total_keys):
        key_index = (_current_key_index + key_offset) % total_keys
        client = _get_client_for_index(key_index)

        for model_name in models_to_try:
            for attempt in range(max_attempts_per_model):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=contents,
                    )

                    # Muvaffaqiyatli key keyingi so‘rov uchun ishlatiladi.
                    _current_key_index = key_index
                    return response

                except Exception as error:
                    last_error = error

                    # 503/429 bo‘lmasa, masalan noto‘g‘ri model nomi bo‘lsa,
                    # shu modelni kutmasdan keyingi modelga o‘tamiz.
                    if not is_transient_gemini_error(error):
                        print(
                            f"Gemini model xatosi: {model_name}. "
                            "Keyingi model sinab ko‘rilmoqda."
                        )
                        break

                    wait_seconds = min(2 ** attempt + random.uniform(0, 0.5), 8)
                    print(
                        f"Gemini vaqtinchalik xatosi ({model_name}, "
                        f"{key_index + 1}-kalit). "
                        f"{wait_seconds:.1f} soniyadan keyin qayta uriniladi..."
                    )
                    time.sleep(wait_seconds)

        # Ushbu key ishlamasa, navbatdagi API keyga o‘tiladi.
        _current_key_index = (key_index + 1) % total_keys

    raise RuntimeError(
        "Gemini hozircha javob bermayapti. 503 yuqori yuklama xatosi vaqtinchalik "
        "bo‘lishi mumkin. Bir necha soniyadan keyin qayta urinib ko‘ring. "
        f"Oxirgi xato: {last_error}"
    ) from last_error


# ============================================================
# ai_generate_test ICHIDAGI EXCEPTION QISMI
# ============================================================
# Mavjud ai_generate_test funksiyangizni to‘liq almashtirmang.
# Faqat uning `except Exception as e:` qismini quyidagicha qoldiring:
#
# except Exception as e:
#     return JsonResponse({
#         'status': 'error',
#         'message': f"Test tuzishda xatolik: {str(e)}"
#     }, status=503 if '503' in str(e) or 'UNAVAILABLE' in str(e).upper() else 500)
