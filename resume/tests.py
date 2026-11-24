from django.test import TestCase

# Create your tests here.


class ResumeFromCvTests(TestCase):
    """The resume matches the CV, and the uploaded CV PDF lives in the database (survives deploys)."""

    def setUp(self):
        from django.core.management import call_command
        call_command('populate_resume', verbosity=0)

    def test_content_matches_cv(self):
        from .models import Education, Experience, ResumeSetting, Skill
        rs = ResumeSetting.objects.get()
        self.assertEqual(rs.job_title, 'Data Scientist')
        self.assertNotIn('production', rs.professional_summary.lower())
        self.assertEqual(Education.objects.count(), 3)
        self.assertEqual(list(Experience.objects.values_list('position', flat=True).order_by('display_order')),
                         ['Foundation Model Researcher', 'Research Assistant (Trainee)'])
        self.assertTrue(Skill.objects.filter(name='Azure (familiarity)', category='CLOUD').exists())
        self.assertFalse(Skill.objects.filter(name__icontains='Azure ML').exists())
        r = self.client.get('/resume/')
        self.assertContains(r, 'Tools &amp; Deployment')
        self.assertContains(r, 'Co-authored 4 peer-reviewed publications.')
        self.assertNotContains(r, 'MLOps')

    def test_uploaded_pdf_is_kept_in_database_and_downloaded(self):
        from django.core.files.base import ContentFile
        from .models import ResumeSetting, StoredFile
        rs = ResumeSetting.objects.get()
        rs.cv_pdf.save('MirHosseini_CV.pdf', ContentFile(b'%PDF-1.4 test cv'), save=True)
        self.assertEqual(StoredFile.objects.count(), 1)
        self.assertEqual(rs.cv_pdf.url, '/resume/download/')
        r = self.client.get('/resume/download/')
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertEqual(r.content, b'%PDF-1.4 test cv')
        self.assertIn('Seyedhasan_Mirhosseini_CV.pdf', r['Content-Disposition'])

    def test_missing_pdf_falls_back_to_generated(self):
        from .models import ResumeSetting
        ResumeSetting.objects.filter(pk=ResumeSetting.objects.get().pk).update(cv_pdf='resume/gone.pdf')
        r = self.client.get('/resume/download/')
        self.assertEqual(r.status_code, 200)   # no 500 for a lost file
