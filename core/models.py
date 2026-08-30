from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
import random


# ==========================================================
# LEGACY: Vazifa va topshiriq modellari
# Eslatma: hozircha hech bir view bularni to'liq ishlatmaydi —
# create_homework.html'dagi "Student Supervision" bloki hozircha
# statik namuna ma'lumot ko'rsatadi (submissions context uzatilmaydi).
# ==========================================================
class HomeworkTask(models.Model):
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_homeworks')
    topic = models.CharField(max_length=255)
    description = models.TextField()
    classroom = models.CharField(max_length=50)
    student_class = models.CharField(max_length=11, blank=True, null=True)
    book_image = models.ImageField(upload_to='homework_images/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.topic


class StudentTaskSubmission(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Tekshirilmoqda'),
        ('passed', 'Test Yechildi'),
    ]

    homework = models.ForeignKey(HomeworkTask, on_delete=models.CASCADE, related_name='submissions')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='submissions')
    score = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.username} - {self.homework.topic}"


# ==========================================================
# O'QUVCHI PROFILI (TO'LIQ - BARCHA FIELDLAR BILAN)
# ==========================================================
class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='student_profile')
    full_name = models.CharField(max_length=255)
    classroom = models.CharField(max_length=50)  # Masalan: 9-A
    phone = models.CharField(max_length=20, blank=True, null=True)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    nickname = models.CharField(max_length=50, blank=True, null=True, verbose_name="Taxallus")
    score = models.IntegerField(default=0)  # Umumiy reyting bali
    progress_percent = models.IntegerField(default=0)  # O'zlashtirish foizi
    yearly_score = models.PositiveIntegerField(default=0)  # Yillik ball
    bio = models.TextField(max_length=250, blank=True, null=True, verbose_name="Haqida / Bio")
    equipped_title = models.CharField(max_length=255, blank=True, null=True, default='')
    gold_certificates = models.PositiveIntegerField(default=0)  # Oltin sertifikat
    silver_certificates = models.PositiveIntegerField(default=0)  # Kumush sertifikat
    bronze_certificates = models.PositiveIntegerField(default=0)  # Bronza sertifikat

    # Qo'shimcha
    needs_help = models.BooleanField(default=False)  # Qoloq/Yordamga muhtojligi
    iq_score = models.PositiveIntegerField(null=True, blank=True)  # IQ bali

    # ✅ QIDIRUV UCHUN - Profil kodi
    profile_code = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        null=True,
        db_index=True  # Tezroq qidiruv uchun
    )

    class Meta:
        verbose_name = "O'quvchi profili"
        verbose_name_plural = "O'quvchi profillari"

    def save(self, *args, **kwargs):
        """Saqlashda profile_code avtomatik yaratiladi agar mavjud bo'lmasa"""
        if not self.profile_code:
            self.profile_code = ''.join([str(random.randint(0, 9)) for _ in range(12)])
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} ({self.profile_code})"

    @property
    def is_online(self):
        """Foydalanuvchi online-mi? (5 daqiqa ichida faol bo'lsa)"""
        if hasattr(self.user, 'activity'):
            return self.user.activity.is_online
        return False


# ==========================================================
# O'QITUVCHI PROFILI
# ==========================================================
class Teacher(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=150)
    nickname = models.CharField(max_length=50, blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    avatar = models.ImageField(upload_to='teacher_avatars/', null=True, blank=True)
    classroom = models.CharField(max_length=20, blank=True, null=True)
    subject = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        verbose_name = "O'qituvchi"
        verbose_name_plural = "O'qituvchilar"

    def __str__(self):
        return f"{self.full_name} ({self.subject})"

class TestQuestion(models.Model):
    homework = models.ForeignKey(
        'Homework', on_delete=models.CASCADE, related_name='test_questions', null=True, blank=True
    )
    question_text = models.TextField("Savol matni")
    option_a = models.CharField("A variant", max_length=255)
    option_b = models.CharField("B variant", max_length=255)
    option_c = models.CharField("C variant", max_length=255, blank=True, null=True)
    option_d = models.CharField("D variant", max_length=255, blank=True, null=True)
    correct_answer = models.CharField("To'g'ri javob (masalan: A)", max_length=10)

    class Meta:
        verbose_name = "Test savoli"
        verbose_name_plural = "Test savollari"

    def __str__(self):
        return f"{self.question_text[:30]}..."

class Homework(models.Model):
    topic = models.CharField(max_length=255, verbose_name="Vazifa nomi")
    description = models.TextField(verbose_name="Vazifa sharti")
    subject = models.CharField(max_length=100, verbose_name="Fan")
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_homeworks", verbose_name="O'qituvchi")
    file = models.FileField(upload_to='homeworks/', blank=True, null=True, verbose_name="Biriktirilgan fayl")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Yaratilgan vaqti")
    deadline = models.DateTimeField(verbose_name="Topshirish muddati")

    def __str__(self):
        return f"{self.title} ({self.subject})"

class HomeworkSubmission(models.Model):
    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name="submissions", verbose_name="Uyga vazifa")
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="my_submissions", verbose_name="O'quvchi")
    answer_text = models.TextField(blank=True, null=True, verbose_name="O'quvchi javobi")
    file = models.FileField(upload_to='submissions/', blank=True, null=True, verbose_name="Javob fayli")
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name="Topshirilgan vaqti")
    score = models.IntegerField(blank=True, null=True, verbose_name="Baho")
    feedback = models.TextField(blank=True, null=True, verbose_name="O'qituvchi izohi")

    def __str__(self):
        return f"{self.student.username} - {self.homework.title}"
# ==========================================================
# TEST NATIJALARI JURNALI
# ==========================================================
class TestResult(models.Model):
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE, related_name='test_results'
    )
    subject = models.CharField("Fan/Mavzu", max_length=150, blank=True)
    tier = models.CharField("Daraja", max_length=30, blank=True)
    correct = models.PositiveIntegerField("To'g'ri javoblar", default=0)
    total = models.PositiveIntegerField("Jami savollar", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Test natijasi"
        verbose_name_plural = "Test natijalari"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student.full_name} — {self.subject} ({self.correct}/{self.total})"


# ==========================================================
# DO'STLIK VE FAOLLIK TIZIMI
# ==========================================================
class UserActivity(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='activity')
    last_seen = models.DateTimeField(default=timezone.now)

    ONLINE_THRESHOLD_SECONDS = 300  # 5 daqiqa

    @property
    def is_online(self):
        return (timezone.now() - self.last_seen).total_seconds() < self.ONLINE_THRESHOLD_SECONDS

    def __str__(self):
        return f"{self.user.username} — {'online' if self.is_online else 'offline'}"


class FriendRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Kutilmoqda'),
        ('accepted', 'Qabul qilingan'),
        ('rejected', 'Rad etilgan'),
    ]

    from_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_friend_requests')
    to_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_friend_requests')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('from_user', 'to_user')
        verbose_name = "Do'stlik so'rovi"
        verbose_name_plural = "Do'stlik so'rovlari"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.from_user.username} → {self.to_user.username} ({self.status})"


# ============================================
# ACHIEVEMENTS / YUTUQLAR TIZIMI
# ============================================
class Achievement(models.Model):
    ACTION_TYPES = [
        ('test_passed', 'Test Yechildi'),
        ('points_earned', 'Ball Topildi'),
        ('friend_added', 'Do\'st Qo\'shildi'),
        ('iq_test_completed', 'IQ Testi Bajarildi'),
        ('login_streak', 'Davomiy Kirish'),
        ('homework_submitted', 'Uy Vazifasi Yuborildi'),
        ('achievement_unlocked', 'Boshqa Achievement Unlock'),
        ('profile_completed', 'Profil To\'liq Qilindi'),
        ('all_achievements_week', 'Haftaning Barcha Missionlari'),
        ('manual_only', 'Olish Imkonsiz / Manual'),
    ]

    RARITY_CHOICES = [
        ('common', 'Common'),
        ('rare', 'Rare'),
        ('epic', 'Epic'),
        ('legendary', 'Legendary'),
    ]

    mission_type = models.CharField(max_length=100)
    name = models.CharField(max_length=255)
    description = models.TextField()

    icon_image = models.ImageField(
        upload_to='achievements/',
        null=True,
        blank=False,
        help_text="Achievement rasmi (JPG, PNG, optimal: 100x100px)"
    )

    reward_points = models.IntegerField(default=10)
    week_number = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    action_type = models.CharField(
        max_length=50,
        choices=ACTION_TYPES,
        default='test_passed',
        help_text="Qaysi harakat buni unlock qiladi?"
    )

    required_value = models.IntegerField(
        default=1,
        help_text="5 ta test yechish = 5, 100 ball = 100"
    )

    rarity = models.CharField(
        max_length=20,
        choices=RARITY_CHOICES,
        default='common',
        help_text="Achievement qiymati - qanchaga qimmat?"
    )

    class Meta:
        ordering = ['-rarity', 'week_number', 'id']
        verbose_name = "Achievement"
        verbose_name_plural = "Achievements"

    def __str__(self):
        return f"{self.name} ({self.get_rarity_display()})"

    def is_legendary(self):
        return self.rarity == 'legendary'

    def is_manual_only(self):
        return self.action_type == 'manual_only'


class UserAchievement(models.Model):
    student = models.ForeignKey(
        'StudentProfile',
        on_delete=models.CASCADE,
        related_name='achievements'
    )
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE)
    completed_at = models.DateTimeField(auto_now_add=True)
    is_new = models.BooleanField(default=True)

    is_equipped = models.BooleanField(
        default=False,
        help_text="Titul taqilgan-mi?"
    )

    class Meta:
        unique_together = ('student', 'achievement')
        ordering = ['-completed_at']
        verbose_name = "User Achievement"
        verbose_name_plural = "User Achievements"

    def __str__(self):
        return f"{self.student.full_name} - {self.achievement.name}"

    def save(self, *args, **kwargs):
        if self.is_equipped:
            UserAchievement.objects.filter(
                student=self.student,
                is_equipped=True
            ).exclude(id=self.id).update(is_equipped=False)
        super().save(*args, **kwargs)


# ============================================
# GURUH TIZIMI VE TAKLIFLAR
# ============================================
class GroupInvite(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Kutilmoqda'),
        ('accepted', 'Qabul qilindi'),
        ('rejected', 'Rad etildi'),
    )
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_group_invites')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_group_invites')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Guruh taklifi"
        verbose_name_plural = "Guruh takliflari"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.sender.username} → {self.receiver.username} ({self.status})"


class Friend(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Kutilmoqda'),
        ('accepted', 'Qabul qilingan'),
    )
    user1 = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='friends_initiated'
    )
    user2 = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='friends_received'
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user1', 'user2')

    def __str__(self):
        return f'{self.user1.username} <-> {self.user2.username} ({self.status})'


class Message(models.Model):
    sender = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='sent_messages'
    )
    receiver = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='received_messages',
        null=True,
        blank=True,
    )
    group = models.ForeignKey(
        'ChatGroup',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='messages',
    )
    text = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='chat_images/', blank=True, null=True)
    video = models.FileField(upload_to='chat_videos/', blank=True, null=True)
    reply_to = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replies',
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.sender.username}: {self.text[:20] if self.text else "Media"}'


class ChatGroup(models.Model):
    name = models.CharField(
        max_length=100, unique=True
    )
    members = models.ManyToManyField(
        User, related_name='chat_groups'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


@receiver(post_save, sender=StudentProfile)
def ensure_profile_code(sender, instance, created, **kwargs):
    """Profile yaratilganda profile_code yo'q bo'lsa uni ta'minlash"""
    if created and not instance.profile_code:
        instance.profile_code = ''.join([str(random.randint(0, 9)) for _ in range(12)])
        instance.save()