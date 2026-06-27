"""Tests: Einladungs-/Passwort-Setzen-Flow für vom Backend angelegte Benutzer
sowie die Benachrichtigungs-Einstellungen im Profil."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from booking import services as svc
from booking.admin import AdminUserInviteForm
from booking.models import Member, OutboxEmail


class AccountInviteTests(TestCase):
    def test_invite_queues_mail_with_working_set_password_link(self):
        u = User.objects.create(username="neu", email="neu@example.org")
        u.set_unusable_password()
        u.save()
        mail = svc.send_account_invite(u)
        self.assertIsNotNone(mail)
        self.assertEqual(OutboxEmail.objects.count(), 1)
        # Link aus der Mail ziehen und den Setz-Flow durchspielen.
        import re
        m = re.search(r"/passwort-setzen/[^\s]+", mail.body)
        self.assertIsNotNone(m, "Set-Password-Link fehlt in der Mail")
        path = m.group(0)
        # Django leitet den /<uidb64>/<token>/-Link intern auf set-password/ um.
        r = self.client.get(path, follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Passwort")
        # Passwort setzen über die aufgelöste Formular-URL.
        post_url = r.redirect_chain[-1][0] if r.redirect_chain else path
        r2 = self.client.post(post_url, {
            "new_password1": "Geheim-1234!", "new_password2": "Geheim-1234!"})
        self.assertIn(r2.status_code, (200, 302))
        u.refresh_from_db()
        self.assertTrue(u.has_usable_password())
        self.assertTrue(u.check_password("Geheim-1234!"))

    def test_no_invite_without_email(self):
        u = User.objects.create(username="ohnemail")
        u.set_unusable_password()
        u.save()
        self.assertIsNone(svc.send_account_invite(u))
        self.assertEqual(OutboxEmail.objects.count(), 0)

    def test_admin_invite_form_creates_user_without_password(self):
        f = AdminUserInviteForm(data={"username": "backenduser",
                                      "email": "back@example.org"})
        self.assertTrue(f.is_valid(), f.errors)
        u = f.save()
        self.assertFalse(u.has_usable_password())
        self.assertEqual(u.email, "back@example.org")

    def test_admin_invite_form_requires_email(self):
        f = AdminUserInviteForm(data={"username": "keinmail", "email": ""})
        self.assertFalse(f.is_valid())
        self.assertIn("email", f.errors)

    def test_freischaltung_mail_skipped_until_password_set(self):
        # Konto ohne Passwort: das Anlegen des Mitglieds löst KEINE
        # „Konto freigeschaltet"-Mail aus (die Person bekommt die Einladung).
        u = User.objects.create(username="p", email="p@example.org")
        u.set_unusable_password()
        u.save()
        Member.objects.create(user=u, display_name="P", email_opt_in=True)
        self.assertEqual(OutboxEmail.objects.count(), 0)

    def test_freischaltung_mail_sent_when_password_usable(self):
        u = User.objects.create_user("q", email="q@example.org", password="x")
        Member.objects.create(user=u, display_name="Q", email_opt_in=True)
        self.assertEqual(OutboxEmail.objects.filter(
            subject__icontains="freigeschaltet").count(), 1)


class ProfileNotifyPrefsTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("m", email="m@example.org", password="x")
        self.member = Member.objects.create(user=self.u, display_name="M",
                                            email_opt_in=True)

    def test_toggle_email_opt_in_off_and_on(self):
        self.client.force_login(self.u)
        # Checkbox NICHT mitgeschickt -> aus.
        self.client.post(reverse("profile"), {"action": "notify_prefs"})
        self.member.refresh_from_db()
        self.assertFalse(self.member.email_opt_in)
        # Checkbox gesetzt -> an.
        self.client.post(reverse("profile"),
                         {"action": "notify_prefs", "email_opt_in": "on"})
        self.member.refresh_from_db()
        self.assertTrue(self.member.email_opt_in)
