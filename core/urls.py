from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from . import views
from .views import update_avatar
from django.contrib.auth.views import LogoutView

urlpatterns = [
    # Bosh va Login sahifalari
    path('', views.login_view, name='login'),
    path('api/update-avatar/', update_avatar, name='update_avatar'),
    path('home/', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('register-teacher/', views.register_teacher, name='register_teacher'),
    path('find-user/', views.find_user, name='find_user'),
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),

    # Dashboards / Profiles
    path('teacher-dashboard/', views.teacher_dashboard, name='teacher_dashboard'),
    path('student-profile/', views.student_profile, name='student_profile'),
    path('teacher-profile/', views.teacher_profile, name='teacher_profile'),
    path('group/<int:group_id>/', views.group_chat_detail, name='group_chat_detail'),
    # Do'stlik tizimi
    path('api/send-friend-request/', views.send_friend_request, name='send_friend_request'),
    path('api/respond-friend-request/', views.respond_friend_request, name='respond_friend_request'),
    path('add-to-group/<int:user_id>/', views.add_to_group, name='add_to_group'),
    path('api/homework/<int:homework_id>/', views.api_get_homework, name='api_get_homework'),
    path('api/submit-homework/', views.api_submit_homework, name='api_submit_homework'),
    # Achievements / Yutuqlar (Dublikatlar olib tashlandi va funksiya nomi to'g'rilandi)
    path('achievements/', views.achievements_view, name='achievements'),
    path('equip-title/', views.equip_title, name='equip_title'),
    path('equip-title/<int:target_id>/', views.equip_title, name='equip_title_with_id'),
    path('api/unlock-achievement/<int:achievement_id>/', views.unlock_achievement, name='unlock_achievement'),
    path('chats/', views.chats_view, name='chats'),
    path('chats/<int:user_id>/', views.chats_view, name='chat_detail'),
    path('api/subjects-with-homeworks/', views.api_subjects_with_homeworks, name='api_subjects_with_homeworks'),
    path('api/homeworks-by-subject/<int:teacher_id>/', views.api_homeworks_by_subject, name='api_homeworks_by_subject'),


    path('api/homework/<int:homework_id>/', views.api_get_homework, name='api_get_homework'),
    path('api/submit-homework/', views.api_submit_homework, name='api_submit_homework'),
    # Qo'shimcha funksiyalar
    path('teacher-dashboard/create-homework/', views.create_homework_view, name='create_homework'),
    path('teacher-dashboard/attach-quiz/', views.attach_quiz, name='attach_quiz'),
    path('rating-help/', views.student_rating_view, name='student_rating_help'),
    path('voice-room/', views.voice_room, name='voice_room'),
    path('api/ai-chat/', views.ai_chat, name='ai_chat'),
    path('api/ai-generate-test/', views.ai_generate_test, name='ai_generate_test'),
    path('api/test-ai/', views.test_ai_connection),
    path('api/save-test-result/', views.save_test_result, name='save_test_result'),
    path('send-invite/<int:user_id>/', views.send_invite, name='send_invite'),
    path('api/save-iq-score/', views.save_iq_score, name='save_iq_score'),
    path('update-nickname/', views.update_nickname, name='update_nickname'),
    path('update-profile-info/', views.update_profile_info, name='update_profile_info'),
    path('teacher-profile/update/', views.update_teacher_profile, name='update_teacher_profile'),
    path('teacher-profile/update-avatar/', views.update_teacher_avatar, name='update_teacher_avatar'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)