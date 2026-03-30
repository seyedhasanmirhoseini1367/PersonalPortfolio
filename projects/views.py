from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
import pickle
import json
import numpy as np
import pandas as pd
import os
from .models import Projects


def projects_list(request):
    """
    View to display all portfolio projects with filtering options
    """
    # Get filter parameters from URL
    project_type = request.GET.get('type', '')
    skill_filter = request.GET.get('skill', '')
    featured_only = request.GET.get('featured', '')

    # Start with all public projects
    projects = Projects.objects.filter(is_public=True)

    # Apply filters
    if project_type:
        projects = projects.filter(project_type=project_type)

    if skill_filter:
        # For TextField, we use contains lookup
        projects = projects.filter(skills_used__contains=skill_filter)

    if featured_only:
        projects = projects.filter(is_featured=True)

    # Get unique project types and skills for filters
    project_types = Projects.PROJECT_TYPE_CHOICES
    skills = Projects.SKILL_CHOICES

    context = {
        'projects': projects,
        'project_types': project_types,
        'skills': skills,
        'active_type': project_type,
        'active_skill': skill_filter,
        'page_title': 'My Data Science Portfolio',
        'total_projects': projects.count(),
        'featured_count': projects.filter(is_featured=True).count(),
    }

    return render(
        request=request,
        template_name="projects/projects_list.html",
        context=context
    )


def project_detail(request, project_id):
    """
    View to display details of a specific project
    """
    project = get_object_or_404(Projects, id=project_id, is_public=True)

    # Calculate additional context data
    kaggle_percentile = project.get_kaggle_percentile()
    skills_display = project.get_skills_display()

    # Get related projects (same type or shared skills)
    # Since skills_used is now TextField, we need to handle it differently
    related_projects = Projects.objects.filter(
        is_public=True
    ).exclude(id=project_id)

    # Build Q objects for related projects
    related_q_objects = Q(project_type=project.project_type)

    # For skills, check if any of the current project's skills appear in other projects
    current_skills = project.get_skills_list()
    for skill in current_skills:
        related_q_objects |= Q(skills_used__contains=skill)

    related_projects = related_projects.filter(related_q_objects)[:3]

    context = {
        'project': project,
        'kaggle_percentile': kaggle_percentile,
        'skills_display': skills_display,
        'related_projects': related_projects,
    }

    return render(
        request=request,
        template_name="projects/project_detail.html",
        context=context
    )


def home(request):
    """
    Homepage view featuring highlighted projects and stats
    """
    featured_projects = Projects.objects.filter(
        is_featured=True,
        is_public=True
    )[:6]

    # Calculate portfolio statistics
    total_projects = Projects.objects.filter(is_public=True).count()
    kaggle_projects = Projects.objects.filter(
        project_type='KAGGLE_COMPETITION',
        is_public=True
    ).count()

    # Get skills frequency for skills cloud
    all_projects = Projects.objects.filter(is_public=True)
    skill_count = {}
    for project in all_projects:
        skills_list = project.get_skills_list()
        for skill in skills_list:
            skill_count[skill] = skill_count.get(skill, 0) + 1

    # Convert to list of tuples for template
    top_skills = sorted(skill_count.items(), key=lambda x: x[1], reverse=True)[:10]

    context = {
        'featured_projects': featured_projects,
        'total_projects': total_projects,
        'kaggle_projects': kaggle_projects,
        'top_skills': top_skills,
        'skill_choices': dict(Projects.SKILL_CHOICES),
    }

    return render(
        request=request,
        template_name="projects/home.html",
        context=context
    )


def prediction_demo(request, project_id):
    """Prediction demo page for a project"""
    project = get_object_or_404(Projects, id=project_id, is_public=True)

    if not project.has_prediction_capability():
        return render(request, 'projects/no_prediction.html', {'project': project})

    context = {
        'project': project,
        'input_features': project.input_features,
    }
    return render(request, 'projects/prediction_demo.html', context)


@csrf_exempt
def make_prediction(request, project_id):
    """API endpoint for making predictions"""
    if request.method == 'POST':
        project = get_object_or_404(Projects, id=project_id, is_public=True)

        if not project.has_prediction_capability():
            return JsonResponse({'error': 'This project does not have prediction capability'}, status=400)

        try:
            # Get user input data
            input_data = {}
            for feature in project.input_features:
                value = request.POST.get(feature['name'])
                if value:
                    # Convert to appropriate type
                    if feature.get('type') == 'number':
                        try:
                            input_data[feature['name']] = float(value)
                        except ValueError:
                            return JsonResponse({'error': f'Invalid number for {feature["name"]}'}, status=400)
                    else:
                        input_data[feature['name']] = value
                else:
                    # If value is missing, use 0 for numbers or empty string for text
                    if feature.get('type') == 'number':
                        input_data[feature['name']] = 0.0
                    else:
                        input_data[feature['name']] = ""

            # Make prediction
            prediction_result = predict_with_model(project, input_data)

            return JsonResponse({
                'success': True,
                'prediction': prediction_result,
                'input_data': input_data
            })

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Method not allowed'}, status=405)


def predict_with_model(project, input_data):
    """Helper function to make predictions with the model"""
    try:
        # Load model
        model_path = project.get_model_path()
        if not model_path or not os.path.exists(model_path):
            raise Exception("Model file not found")

        # Detect file type and load model
        if model_path.endswith('.pkl') or model_path.endswith('.pickle'):
            with open(model_path, 'rb') as f:
                model = pickle.load(f)
        elif model_path.endswith('.joblib'):
            import joblib
            model = joblib.load(model_path)
        else:
            raise Exception("Model file format not supported")

        # Prepare input data
        input_df = prepare_input_data(project, input_data)

        # Make prediction
        prediction = model.predict(input_df)

        # Format result
        if hasattr(prediction, '__len__') and len(prediction) == 1:
            result = float(prediction[0])
        else:
            result = float(prediction)

        return result

    except Exception as e:
        raise Exception(f"Prediction error: {str(e)}")


def prepare_input_data(project, input_data):
    """Prepare input data for model prediction"""
    # Create DataFrame with correct feature order
    feature_names = [feature['name'] for feature in project.input_features]

    # Create array with values in correct order
    input_array = []
    for feature in project.input_features:
        value = input_data.get(feature['name'])
        if value is None:
            # Default values if not provided
            if feature.get('type') == 'number':
                value = 0.0
            else:
                value = ""
        input_array.append(value)

    # Create DataFrame
    input_df = pd.DataFrame([input_array], columns=feature_names)
    return input_df