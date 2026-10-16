"""Human-verified account assistance, exposed only by Django's superuser admin."""
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError as APIValidationError
from .models import User, AuditLog
from .validation import mobile as normalize_mobile


class AccountAssistanceForm(forms.Form):
    operation = forms.ChoiceField(choices=[('link_mobile', 'Link a verified login mobile'), ('reset_password', 'Reset password after ownership verification')])
    mobile = forms.CharField(required=False, max_length=20)
    temporary_password = forms.CharField(required=False, max_length=128, widget=forms.PasswordInput)
    confirm_password = forms.CharField(required=False, max_length=128, widget=forms.PasswordInput)
    ownership_verified = forms.BooleanField(label='I independently verified ownership of this account and store')
    verification_reference = forms.CharField(max_length=200, help_text='Internal support case reference and verification method. Do not enter identity documents, passwords or sensitive personal data.')
    admin_password = forms.CharField(max_length=128, widget=forms.PasswordInput, label='Your administrator password')

    def __init__(self, *args, actor, target, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor, self.target = actor, target

    def clean(self):
        data = super().clean()
        if not self.actor.is_active or not self.actor.is_superuser or self.actor.must_change_password:
            raise ValidationError('Only an active platform administrator can assist an account.')
        if not self.actor.check_password(data.get('admin_password', '')):
            raise ValidationError('Your administrator password is incorrect.')
        if data.get('operation') == 'link_mobile':
            try: data['mobile'] = normalize_mobile(data.get('mobile', ''))
            except APIValidationError: raise ValidationError('Enter a valid Indian mobile number.')
            if User.objects.filter(login_mobile=data['mobile']).exclude(pk=self.target.pk).exists():
                raise ValidationError('This login number is already assigned. Accounts cannot be merged here.')
        elif data.get('operation') == 'reset_password':
            if not self.target.login_mobile:
                raise ValidationError('Verify and link the login mobile before resetting this account.')
            if self.target.pk == self.actor.pk:
                raise ValidationError('Use Change Password in your account settings for your own account.')
            password = data.get('temporary_password', '')
            if not password or password != data.get('confirm_password'):
                raise ValidationError('Temporary passwords must match.')
            validate_password(password, self.target)
            if self.target.check_password(password): raise ValidationError('Choose a different temporary password.')
        return data

    @transaction.atomic
    def save(self):
        data = self.cleaned_data
        user = User.objects.select_for_update().get(pk=self.target.pk)
        if data['operation'] == 'link_mobile':
            user.login_mobile = data['mobile']
            user.legacy_mobile_candidate = None
            # Preserve the old contact field and all password hashes.
            user.save(update_fields=['login_mobile', 'legacy_mobile_candidate'])
            action = 'admin.login_mobile_verified'
        else:
            user.set_password(data['temporary_password'])
            user.must_change_password = True
            user.password_reset_at = timezone.now()
            user.save(update_fields=['password', 'must_change_password', 'password_reset_at'])
            action = 'admin.password_reset'
        AuditLog.objects.create(actor=self.actor, business=getattr(getattr(user, 'membership', None), 'business', None),
            action=action, object_id=str(user.pk), verification_reference=data['verification_reference'])
        return user
