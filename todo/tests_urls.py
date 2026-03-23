from django.test import TestCase
from django.urls import reverse, resolve
from todo import views

class URLTests(TestCase):
    """Test that URLs resolve correctly"""
    
    def test_login_url_resolves(self):
        """Test that login URL resolves to correct view"""
        url = reverse('todo:login')
        self.assertEqual(url, '/login/')
        resolved = resolve('/login/')
        self.assertEqual(resolved.func.view_class, views.LoginView)
    
    def test_logout_url_resolves(self):
        """Test that logout URL resolves to correct view"""
        url = reverse('todo:logout')
        self.assertEqual(url, '/logout/')
        resolved = resolve('/logout/')
        self.assertEqual(resolved.func.view_class, views.LogoutView)
    
    def test_register_url_resolves(self):
        """Test that register URL resolves to correct view"""
        url = reverse('todo:register')
        self.assertEqual(url, '/register/')
        resolved = resolve('/register/')
        self.assertEqual(resolved.func.view_class, views.RegisterView)
    
    def test_profile_url_resolves(self):
        """Test that profile URL resolves to correct view"""
        url = reverse('todo:profile')
        self.assertEqual(url, '/profile/')
        resolved = resolve('/profile/')
        self.assertEqual(resolved.func.view_class, views.ProfileView)