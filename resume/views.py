from django.shortcuts import render
from django.http import HttpResponse
from django.template.loader import render_to_string
from io import BytesIO
from xhtml2pdf import pisa
from collections import defaultdict
from .models import (
    ResumeSetting, Education, Experience, Skill,
    ProjectHighlight, Certification, Language
)


def resume_page(request):
    """
    Main resume page view
    """
    resume_settings = ResumeSetting.objects.first()

    if not resume_settings or not resume_settings.is_active:
        return render(request, 'resume/resume_unavailable.html')

    # Group skills by category
    skills = Skill.objects.all().order_by('category', 'display_order', 'name')
    skills_by_category = defaultdict(list)

    for skill in skills:
        skills_by_category[skill.category].append(skill)

    context = {
        'resume_settings': resume_settings,
        'education': Education.objects.all(),
        'experience': Experience.objects.all(),
        'skills': skills_by_category,  # Now passing grouped skills
        'project_highlights': ProjectHighlight.objects.all(),
        'certifications': Certification.objects.all(),
        'languages': Language.objects.all(),
        'page_title': 'Resume - HasanPortfolio',
    }

    return render(request, 'resume/resume_page.html', context)


def download_resume_pdf(request):
    """
    Generate and download resume as PDF using xhtml2pdf
    """
    resume_settings = ResumeSetting.objects.first()

    if not resume_settings or not resume_settings.is_active:
        return HttpResponse("Resume not available", status=404)

    # Group skills by category
    skills = Skill.objects.all().order_by('category', 'display_order', 'name')
    skills_by_category = defaultdict(list)

    for skill in skills:
        skills_by_category[skill.category].append(skill)

    context = {
        'resume_settings': resume_settings,
        'education': Education.objects.all(),
        'experience': Experience.objects.all(),
        'skills': skills_by_category,  # Now passing grouped skills
        'project_highlights': ProjectHighlight.objects.all(),
        'certifications': Certification.objects.all(),
        'languages': Language.objects.all(),
    }

    # Render HTML template
    html_string = render_to_string('resume/resume_pdf.html', context)

    # Create PDF
    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html_string.encode("UTF-8")), result)

    if not pdf.err:
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="Hasan_Mirhoseini_Resume.pdf"'
        return response

    return HttpResponse("Error generating PDF", status=500)


def resume_json(request):
    """
    API endpoint to get resume data as JSON
    """
    import json
    from django.http import JsonResponse

    resume_settings = ResumeSetting.objects.first()

    if not resume_settings or not resume_settings.is_active:
        return JsonResponse({'error': 'Resume not available'}, status=404)

    # Group skills by category for JSON response
    skills = Skill.objects.all().order_by('category', 'display_order', 'name')
    skills_by_category = defaultdict(list)

    for skill in skills:
        skills_by_category[skill.category].append({
            'id': skill.id,
            'name': skill.name,
            'category': skill.category,
            'category_display': skill.get_category_display(),
            'proficiency': skill.proficiency,
            'description': skill.description,
            'display_order': skill.display_order,
            'is_featured': skill.is_featured,
            'created_at': skill.created_at,
            'updated_at': skill.updated_at,
        })

    data = {
        'personal_info': {
            'full_name': resume_settings.full_name,
            'job_title': resume_settings.job_title,
            'email': resume_settings.email,
            'phone': resume_settings.phone,
            'location': resume_settings.location,
            'website': resume_settings.website,
            'professional_summary': resume_settings.professional_summary,
        },
        'education': list(Education.objects.values()),
        'experience': list(Experience.objects.values()),
        'skills': dict(skills_by_category),  # Convert defaultdict to dict
        'project_highlights': list(ProjectHighlight.objects.values()),
        'certifications': list(Certification.objects.values()),
        'languages': list(Language.objects.values()),
    }

    return JsonResponse(data)