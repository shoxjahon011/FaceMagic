from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import (
    HomeworkTask,
    StudentTaskSubmission,
    StudentProfile,
    Teacher,
    Homework,
    TestResult,
    UserActivity,
    FriendRequest,
    Achievement,
    UserAchievement
)


# ==========================================================
# 1. O'QUVCHI PROFILLARI ADMINI
# ==========================================================
@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = [
        'full_name',
        'get_username',
        'classroom',
        'phone',
        'profile_code',
        'score',
        'get_is_active',
        'needs_help'
    ]

    list_filter = ['classroom', 'needs_help', 'user__is_active']
    search_fields = ['full_name', 'user__username', 'phone', 'profile_code', 'nickname']
    ordering = ['-score', 'full_name']
    actions = ['activate_students', 'deactivate_students']

    fieldsets = (
        ('Shaxsiy Ma\'lumotlar', {
            'fields': ('user', 'full_name', 'nickname', 'classroom', 'phone', 'avatar', 'bio')
        }),
        ('Statistika va Sertifikatlar', {
            'fields': (
                'score',
                'yearly_score',
                'progress_percent',
                'iq_score',
                'gold_certificates',
                'silver_certificates',
                'bronze_certificates',
                'needs_help'
            )
        }),
        ('Tizim kodi', {
            'fields': ('profile_code',),
        }),
    )

    readonly_fields = ['profile_code']
    list_select_related = ['user']

    @admin.display(description='Login (Username)', ordering='user__username')
    def get_username(self, obj):
        return obj.user.username

    @admin.display(description='Aktivligi', boolean=True)
    def get_is_active(self, obj):
        return obj.user.is_active

    # O'quvchilarni guruhlab aktivlashtirish va deaktivatsiya qilish
    @admin.action(description="Tanlangan o'quvchilarni aktivlashtirish (Tasdiqlash)")
    def activate_students(self, request, queryset):
        updated = 0
        for student in queryset:
            student.user.is_active = True
            student.user.save()
            updated += 1
        self.message_user(request, f"{updated} ta o'quvchi muvaffaqiyatli tasdiqlandi.")

    @admin.action(description="Tanlangan o'quvchilar aktivligini bekor qilish")
    def deactivate_students(self, request, queryset):
        updated = 0
        for student in queryset:
            student.user.is_active = False
            student.user.save()
            updated += 1
        self.message_user(request, f"{updated} ta o'quvchi aktivligi bekor qilindi.")


# ==========================================================
# 2. O'QITUVCHILAR ADMINI (TASDIQLASH FUNKSIYASI BILAN)
# ==========================================================
@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'get_username', 'classroom', 'subject', 'get_is_active']
    list_filter = ['classroom', 'subject', 'user__is_active']
    search_fields = ['full_name', 'user__username', 'subject', 'classroom']
    list_select_related = ['user']
    actions = ['activate_teachers', 'deactivate_teachers']

    @admin.display(description='Login', ordering='user__username')
    def get_username(self, obj):
        return obj.user.username

    @admin.display(description='Aktivligi (Tasdiqlangan)', boolean=True)
    def get_is_active(self, obj):
        return obj.user.is_active

    # O'qituvchilarni guruhlab tasdiqlash uchun Action
    @admin.action(description="Tanlangan o'qituvchilarni tasdiqlash (Aktivlashtirish)")
    def activate_teachers(self, request, queryset):
        updated = 0
        for teacher in queryset:
            teacher.user.is_active = True
            teacher.user.save()
            updated += 1
        self.message_user(request, f"{updated} ta o'qituvchi profilining aktivligi tasdiqlandi.")

    # O'qituvchilar aktivligini o'chirish uchun Action
    @admin.action(description="Tanlangan o'qituvchilar aktivligini bekor qilish")
    def deactivate_teachers(self, request, queryset):
        updated = 0
        for teacher in queryset:
            teacher.user.is_active = False
            teacher.user.save()
            updated += 1
        self.message_user(request, f"{updated} ta o'qituvchining aktivligi bekor qilindi.")


# ==========================================================
# 3. STANDART USER ADMINI
# ==========================================================
class StudentProfileInline(admin.StackedInline):
    model = StudentProfile
    can_delete = False
    verbose_name_plural = "O'quvchi Profili"
    readonly_fields = ['profile_code']


class TeacherInline(admin.StackedInline):
    model = Teacher
    can_delete = False
    verbose_name_plural = "O'qituvchi Profili"


admin.site.unregister(User)


@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    inlines = [StudentProfileInline, TeacherInline]
    list_display = ['username', 'email', 'first_name', 'last_name', 'is_staff', 'is_active']


# ==========================================================
# 4. ACHIEVEMENT ADMIN (UPDATED - YANGI FIELDS BILAN)
# ==========================================================
class UserAchievementInline(admin.TabularInline):
    model = UserAchievement
    extra = 0
    readonly_fields = ['student', 'completed_at']
    fields = ['student', 'is_equipped', 'completed_at']


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'rarity',
        'action_type',
        'required_value',
        'reward_points',
        'week_number',
        'is_active'
    ]

    list_filter = ['is_active', 'rarity', 'action_type', 'week_number']
    search_fields = ['name', 'mission_type', 'description']
    ordering = ['-rarity', 'week_number', 'id']
    inlines = [UserAchievementInline]

    fieldsets = (
        ('🎯 Asosiy Ma\'lumot', {
            'fields': ('name', 'description', 'mission_type')
        }),
        ('🖼️ RASM (Icon o\'rniga)', {
            'fields': ('icon_image',),
            'description': 'Achievement rasmi (JPG, PNG, optimal: 100x100px)'
        }),
        ('⚙️ ACTION TRIGGER', {
            'fields': ('action_type', 'required_value'),
            'description': 'action_type: qaysi harakat buni unlock qiladi? required_value: masalan 5 ta test = 5, 100 ball = 100'
        }),
        ('💎 RARITY (Qimmat)', {
            'fields': ('rarity',),
            'description': 'Achievement qiymati - qanchaga qimmat? (common/rare/epic/legendary)'
        }),
        ('🏆 Reward', {
            'fields': ('reward_points', 'week_number')
        }),
        ('📊 Status', {
            'fields': ('is_active',),
        }),
    )

    readonly_fields = ['mission_type']


# ==========================================================
# 5. USER ACHIEVEMENT ADMIN
# ==========================================================
@admin.register(UserAchievement)
class UserAchievementAdmin(admin.ModelAdmin):
    list_display = ['student', 'achievement', 'completed_at', 'is_equipped', 'is_new']
    list_filter = ['completed_at', 'is_new', 'is_equipped', 'achievement__rarity']
    search_fields = ['student__full_name', 'achievement__name']
    readonly_fields = ['completed_at']

    fieldsets = (
        ('Ma\'lumot', {
            'fields': ('student', 'achievement', 'is_new')
        }),
        ('👑 TITUL SYSTEM', {
            'fields': ('is_equipped',),
            'description': 'Titul taqilgan-mi? (Faol titul)'
        }),
        ('Vaqt', {
            'fields': ('completed_at',),
            'classes': ('collapse',)
        }),
    )


# ==========================================================
# 6. QOLGAN MODELLAR
# ==========================================================
@admin.register(TestResult)
class TestResultAdmin(admin.ModelAdmin):
    list_display = ['student', 'subject', 'tier', 'correct', 'total', 'created_at']
    list_filter = ['tier', 'created_at']
    search_fields = ['student__full_name', 'subject']


@admin.register(FriendRequest)
class FriendRequestAdmin(admin.ModelAdmin):
    list_display = ['from_user', 'to_user', 'status', 'created_at']
    list_filter = ['status']


@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ['user', 'last_seen', 'is_online']


@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = ['topic', 'teacher', 'created_at']