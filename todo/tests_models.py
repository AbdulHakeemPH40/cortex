from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from todo.models import Task

class TaskModelTests(TestCase):
    def setUp(self):
        """Create test user and tasks for testing"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create some test tasks
        self.task1 = Task.objects.create(
            user=self.user,
            title='Test Task 1',
            description='This is a test task',
            priority='H',
            status='P',
            progress=0,
            due_date=timezone.now() + timezone.timedelta(days=1)
        )
        
        self.task2 = Task.objects.create(
            user=self.user,
            title='Test Task 2',
            description='Another test task',
            priority='M',
            status='I',
            progress=50,
            due_date=timezone.now() + timezone.timedelta(days=2)
        )
        
        self.task3 = Task.objects.create(
            user=self.user,
            title='Test Task 3',
            description='Completed task',
            priority='L',
            status='C',
            progress=100,
            due_date=timezone.now() - timezone.timedelta(days=1)  # Overdue
        )
    
    def test_task_creation(self):
        """Test that tasks are created correctly"""
        self.assertEqual(Task.objects.count(), 3)
        self.assertEqual(self.task1.title, 'Test Task 1')
        self.assertEqual(self.task1.user.username, 'testuser')
        self.assertEqual(self.task1.priority, 'H')
        self.assertEqual(self.task1.status, 'P')
        self.assertEqual(self.task1.progress, 0)
    
    def test_task_string_representation(self):
        """Test the __str__ method"""
        self.assertEqual(str(self.task1), 'Test Task 1')
        self.assertEqual(str(self.task2), 'Test Task 2')
    
    def test_task_priority_choices(self):
        """Test that priority choices are valid"""
        valid_priorities = ['H', 'M', 'L']
        for task in Task.objects.all():
            self.assertIn(task.priority, valid_priorities)
    
    def test_task_status_choices(self):
        """Test that status choices are valid"""
        valid_statuses = ['P', 'I', 'C', 'X']
        for task in Task.objects.all():
            self.assertIn(task.status, valid_statuses)
    
    def test_task_progress_range(self):
        """Test that progress is between 0 and 100"""
        for task in Task.objects.all():
            self.assertGreaterEqual(task.progress, 0)
            self.assertLessEqual(task.progress, 100)
    
    def test_task_is_overdue(self):
        """Test overdue task detection"""
        # task3 is overdue (due_date is in the past)
        self.assertTrue(self.task3.is_overdue())
        
        # task1 and task2 are not overdue
        self.assertFalse(self.task1.is_overdue())
        self.assertFalse(self.task2.is_overdue())
    
    def test_task_priority_display(self):
        """Test priority display method"""
        self.assertEqual(self.task1.get_priority_display(), 'High')
        self.assertEqual(self.task2.get_priority_display(), 'Medium')
        self.assertEqual(self.task3.get_priority_display(), 'Low')
    
    def test_task_status_display(self):
        """Test status display method"""
        self.assertEqual(self.task1.get_status_display(), 'Pending')
        self.assertEqual(self.task2.get_status_display(), 'In Progress')
        self.assertEqual(self.task3.get_status_display(), 'Completed')
    
    def test_task_user_relationship(self):
        """Test that tasks are linked to users"""
        user_tasks = Task.objects.filter(user=self.user)
        self.assertEqual(user_tasks.count(), 3)
        
        # Create another user and test isolation
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='otherpass123'
        )
        
        other_task = Task.objects.create(
            user=other_user,
            title='Other User Task',
            description='Task for other user',
            priority='M',
            status='P',
            progress=0
        )
        
        # Original user should still have only 3 tasks
        self.assertEqual(Task.objects.filter(user=self.user).count(), 3)
        # Other user should have 1 task
        self.assertEqual(Task.objects.filter(user=other_user).count(), 1)
    
    def test_task_ordering(self):
        """Test that tasks are ordered by creation date (newest first)"""
        tasks = list(Task.objects.filter(user=self.user))
        
        # Check that tasks are ordered by created_at descending
        for i in range(len(tasks) - 1):
            self.assertGreaterEqual(tasks[i].created_at, tasks[i + 1].created_at)
    
    def test_task_update(self):
        """Test updating task properties"""
        self.task1.title = 'Updated Task Title'
        self.task1.status = 'C'
        self.task1.progress = 100
        self.task1.save()
        
        updated_task = Task.objects.get(id=self.task1.id)
        self.assertEqual(updated_task.title, 'Updated Task Title')
        self.assertEqual(updated_task.status, 'C')
        self.assertEqual(updated_task.progress, 100)
    
    def test_task_delete(self):
        """Test deleting a task"""
        task_id = self.task1.id
        self.task1.delete()
        
        # Task should no longer exist
        with self.assertRaises(Task.DoesNotExist):
            Task.objects.get(id=task_id)
        
        # Should have 2 tasks remaining
        self.assertEqual(Task.objects.count(), 2)