from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

User = get_user_model()


class LoginForm(forms.Form):
    username = forms.CharField(
        label="Login/Username",
        widget=forms.TextInput(attrs={
            'class': 'search-input',
            'placeholder': 'student_ali',
            'style': 'width: 100%; margin-bottom: 15px;'
        })
    )
    password = forms.CharField(
        label="Parol",
        widget=forms.PasswordInput(attrs={
            'class': 'search-input',
            'placeholder': '........',
            'style': 'width: 100%; margin-bottom: 20px;'
        })
    )


class StudentRegistrationForm(UserCreationForm):
    full_name = forms.CharField(
        label="F.I.SH (Username)",
        widget=forms.TextInput(attrs={'class': 'search-input', 'placeholder': 'Ali Valiyev'})
    )
    user_class = forms.CharField(
        label="Sinf (Class)",
        widget=forms.TextInput(attrs={'class': 'search-input', 'placeholder': '9-A sinf'})
    )
    phone = forms.CharField(
        label="Telefon Raqam",
        widget=forms.TextInput(attrs={'class': 'search-input', 'placeholder': '+998 90 123 45 67'})
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'full_name', 'user_class', 'phone')


class TeacherRegistrationForm(UserCreationForm):
    full_name = forms.CharField(
        label="O'qituvchi F.I.SH (Username)",
        widget=forms.TextInput(attrs={'class': 'search-input', 'placeholder': 'Dilshod Rahmatov'})
    )
    class_leader = forms.CharField(
        label="Qaysi sinf rahbari? (Which class?)",
        widget=forms.TextInput(attrs={'class': 'search-input', 'placeholder': "9-'A' Sinf"})
    )
    subject = forms.CharField(
        label="Qaysi fan o'qituvchisi? (Subject)",
        widget=forms.TextInput(attrs={'class': 'search-input', 'placeholder': 'Matematika va Algebra'})
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'full_name', 'class_leader', 'subject')