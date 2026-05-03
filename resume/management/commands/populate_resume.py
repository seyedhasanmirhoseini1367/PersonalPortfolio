"""
Management command: populate resume data from CV.

Usage:
    python manage.py populate_resume
    python manage.py populate_resume --clear   # wipe existing entries first
"""

import datetime
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Populate resume with CV data for Seyed Hasan Mir Hosseini."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete all existing resume entries before populating.",
        )
        parser.add_argument(
            "--if-empty",
            action="store_true",
            help="Skip silently if Education entries already exist (safe for repeated deploys).",
        )

    def handle(self, **options):
        from resume.models import (
            ResumeSetting, Education, Experience,
            Skill, ProjectHighlight, Language,
        )

        # ── Guard: skip if DB already has data (safe for repeated deploys) ────
        if options.get("if_empty") and Education.objects.exists():
            self.stdout.write("Resume data already present — skipping (use --clear to reset).")
            return

        # ── 1. ResumeSetting (singleton) ──────────────────────────────────────
        resume, created = ResumeSetting.objects.get_or_create(pk=1)
        resume.full_name = "Seyed Hasan Mir Hosseini"
        resume.job_title = "Data Scientist / Machine Learning Engineer"
        resume.email = "seyedhasan.mirhoseini1367@gmail.com"
        resume.phone = "+358 44 932 6220"
        resume.location = "Finland"
        resume.website = "https://hasanportfolio.azurewebsites.net"
        resume.professional_summary = (
            "Data Scientist with 2+ years of hands-on experience building and deploying "
            "predictive and deep-learning models (Transformers, CNN, LSTM) in Python. "
            "Experienced with large time-series datasets, feature engineering, and "
            "production deployment using Docker, CI/CD, and Azure ML across the full ML lifecycle."
        )
        resume.github_url   = "https://github.com/seyedhasanmirhoseini1367?tab=repositories"
        resume.linkedin_url = "https://www.linkedin.com/in/seyedhasanmirhosseini/"
        resume.is_active = True
        resume.save()
        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} ResumeSetting."))

        # ── 2. Optionally clear existing related entries ──────────────────────
        if options["clear"]:
            Education.objects.filter(resume=resume).delete()
            Experience.objects.filter(resume=resume).delete()
            Skill.objects.filter(resume=resume).delete()
            ProjectHighlight.objects.filter(resume=resume).delete()
            Language.objects.filter(resume=resume).delete()
            self.stdout.write(self.style.WARNING("Cleared existing resume entries."))

        # ── 3. Education ──────────────────────────────────────────────────────
        education_data = [
            dict(
                institution="Tampere University",
                degree="MASTER",
                field_of_study="Statistical Data Analytics",
                start_date=datetime.date(2023, 9, 1),
                end_date=datetime.date(2025, 6, 30),
                location="Tampere, Finland",
                display_order=1,
            ),
            dict(
                institution="University of Tehran",
                degree="MASTER",
                field_of_study="Business Administration (MBA)",
                start_date=datetime.date(2013, 9, 1),
                end_date=datetime.date(2016, 6, 30),
                location="Tehran, Iran",
                display_order=3,
            ),
            dict(
                institution="Damghan University",
                degree="BACHELOR",
                field_of_study="Mathematics",
                start_date=datetime.date(2008, 9, 1),
                end_date=datetime.date(2013, 6, 30),
                location="Damghan, Iran",
                display_order=4,
            ),
        ]
        self._bulk_create(Education, education_data, resume, "institution")

        # ── 4. Experience ─────────────────────────────────────────────────────
        experience_data = [
            dict(
                company="University of Eastern Finland",
                position="Data Scientist (Intern)",
                employment_type="INTERNSHIP",
                start_date=datetime.date(2025, 8, 1),
                end_date=datetime.date(2025, 11, 30),
                location="Finland",
                achievements=[
                    "Built a Transformer-based foundation model on large time-series data, "
                    "pretrained with self-supervised learning (VICReg) and fine-tuned for classification.",
                    "Developed the full PyTorch pipeline: preprocessing, augmentation, "
                    "pretraining, fine-tuning, and evaluation.",
                ],
                display_order=1,
            ),
            dict(
                company="Gamification Group, Tampere University",
                position="Data Analyst",
                employment_type="PART_TIME",
                start_date=datetime.date(2024, 1, 1),
                end_date=datetime.date(2025, 1, 31),
                location="Tampere, Finland",
                achievements=[
                    "Processed and analysed large experimental datasets: cleaning, preprocessing, "
                    "statistical analysis, and visualisation.",
                    "Co-authored peer-reviewed publications based on the research findings.",
                ],
                display_order=2,
            ),
            dict(
                company="Tampere University",
                position="Master's Thesis Researcher — Seizure Detection",
                employment_type="FULL_TIME",
                start_date=datetime.date(2024, 9, 1),
                end_date=datetime.date(2025, 6, 30),
                location="Tampere, Finland",
                achievements=[
                    "Designed and compared predictive deep-learning models (LSTM–Transformer, "
                    "CNN–Transformer, and multimodal fusion) for time-series classification.",
                    "Implemented end-to-end pipeline in PyTorch: preprocessing, spectrogram & "
                    "time-series feature extraction, training, and model evaluation.",
                ],
                display_order=3,
            ),
        ]
        self._bulk_create(Experience, experience_data, resume, "position")

        # ── 5. Skills (order and content matches CV Core Skills table) ──────────
        skills_data = [
            # Languages
            dict(name="Python (primary)", category="PROGRAMMING", proficiency=5, is_featured=True, display_order=1),
            dict(name="SQL",              category="PROGRAMMING", proficiency=3, display_order=2),
            dict(name="R",               category="PROGRAMMING", proficiency=3, display_order=3),

            # LLM / Agents
            dict(name="LangChain",                       category="TOOLS", proficiency=4, is_featured=True, display_order=1),
            dict(name="LangGraph",                       category="TOOLS", proficiency=4, display_order=2),
            dict(name="RAG systems",                     category="TOOLS", proficiency=4, is_featured=True, display_order=3),
            dict(name="Multi-agent orchestration",       category="TOOLS", proficiency=4, display_order=4),
            dict(name="Prompt engineering",              category="TOOLS", proficiency=4, display_order=5),
            dict(name="Groq (LLaMA 3.1)",               category="TOOLS", proficiency=3, display_order=6),
            dict(name="Gemini",                          category="TOOLS", proficiency=3, display_order=7),
            dict(name="ChromaDB",                        category="TOOLS", proficiency=3, display_order=8),
            dict(name="sentence-transformers",           category="TOOLS", proficiency=4, display_order=9),
            dict(name="BM25 + semantic hybrid retrieval", category="TOOLS", proficiency=4, display_order=10),

            # MLOps / Deploy
            dict(name="Docker (multi-stage)",             category="CLOUD", proficiency=4, is_featured=True, display_order=1),
            dict(name="Docker Compose",                   category="CLOUD", proficiency=4, display_order=2),
            dict(name="GitHub Actions CI/CD",             category="CLOUD", proficiency=4, is_featured=True, display_order=3),
            dict(name="Azure ML managed online endpoints", category="CLOUD", proficiency=4, is_featured=True, display_order=4),
            dict(name="Azure App Service",                category="CLOUD", proficiency=3, display_order=5),
            dict(name="REST APIs",                        category="CLOUD", proficiency=4, display_order=6),
            dict(name="Git",                              category="CLOUD", proficiency=5, display_order=7),

            # ML / DL
            dict(name="PyTorch",                         category="ML_FRAMEWORKS", proficiency=5, is_featured=True, display_order=1),
            dict(name="Transformers",                    category="ML_FRAMEWORKS", proficiency=4, is_featured=True, display_order=2),
            dict(name="CNN",                             category="ML_FRAMEWORKS", proficiency=4, display_order=3),
            dict(name="LSTM",                            category="ML_FRAMEWORKS", proficiency=4, display_order=4),
            dict(name="Autoencoders",                    category="ML_FRAMEWORKS", proficiency=4, display_order=5),
            dict(name="Self-supervised learning (VICReg)", category="ML_FRAMEWORKS", proficiency=4, display_order=6),
            dict(name="scikit-learn",                    category="ML_FRAMEWORKS", proficiency=5, is_featured=True, display_order=7),
            dict(name="LightGBM",                        category="ML_FRAMEWORKS", proficiency=4, display_order=8),
            dict(name="XGBoost",                         category="ML_FRAMEWORKS", proficiency=4, display_order=9),
            dict(name="CatBoost",                        category="ML_FRAMEWORKS", proficiency=4, display_order=10),

            # Data
            dict(name="Pandas",               category="DATA_ANALYSIS", proficiency=5, is_featured=True, display_order=1),
            dict(name="NumPy",                category="DATA_ANALYSIS", proficiency=5, display_order=2),
            dict(name="SciPy",                category="DATA_ANALYSIS", proficiency=4, display_order=3),
            dict(name="Matplotlib",           category="DATA_ANALYSIS", proficiency=4, display_order=4),
            dict(name="Feature engineering",  category="DATA_ANALYSIS", proficiency=4, is_featured=True, display_order=5),
            dict(name="Time-series processing", category="DATA_ANALYSIS", proficiency=5, is_featured=True, display_order=6),

            # Web / Backend
            dict(name="Django",     category="DATABASES", proficiency=4, is_featured=True, display_order=1),
            dict(name="REST APIs",  category="DATABASES", proficiency=4, display_order=2),
            dict(name="HTML",       category="DATABASES", proficiency=3, display_order=3),
            dict(name="CSS",        category="DATABASES", proficiency=3, display_order=4),

            # Soft Skills
            dict(name="Organized & Punctual",          category="SOFT_SKILLS", proficiency=5, display_order=1),
            dict(name="Self-Directed & Reliable",       category="SOFT_SKILLS", proficiency=5, display_order=2),
            dict(name="Collaborative Teamwork",         category="SOFT_SKILLS", proficiency=5, display_order=3),
            dict(name="Clear Communication",            category="SOFT_SKILLS", proficiency=5, display_order=4),
            dict(name="Project Management",             category="SOFT_SKILLS", proficiency=4, display_order=5),
            dict(name="Problem-Solving",                category="SOFT_SKILLS", proficiency=5, display_order=6),
            dict(name="Intellectual Curiosity",         category="SOFT_SKILLS", proficiency=5, display_order=7),
            dict(name="Adaptability",                   category="SOFT_SKILLS", proficiency=5, display_order=8),
        ]
        self._upsert_skills(skills_data, resume)

        # ── 6. Project Highlights ─────────────────────────────────────────────
        projects_data = [
            dict(
                title="HasanAI — Production ML Deployment Platform",
                description=(
                    "Personal portfolio website with live ML model prediction demos, a RAG-powered AI assistant, "
                    "and a technical blog. Deployed predictive ML models to production on Azure App Service with "
                    "live prediction endpoints. Built a modular inference registry routing requests to Azure ML "
                    "endpoints, with automatic local-model fallback."
                ),
                technologies_used=["Django", "Azure ML", "Docker", "GitHub Actions", "PostgreSQL", "LangChain", "RAG", "Python"],
                project_url="https://hasanportfolio.azurewebsites.net",
                start_date=datetime.date(2024, 1, 1),
                is_current=True,
                display_order=1,
            ),
            dict(
                title="HealthCompass — Health Analytics Web App",
                description=(
                    "Longitudinal biomarker trend analysis over time-series medical records. "
                    "RAG assistant with hybrid BM25 + semantic retrieval and multi-LLM failover (Groq, Gemini)."
                ),
                technologies_used=["Django", "LangChain", "RAG", "ChromaDB", "Python", "PostgreSQL"],
                start_date=datetime.date(2024, 6, 1),
                end_date=datetime.date(2025, 1, 31),
                display_order=2,
            ),
            dict(
                title="CasvuAI — Multi-Agent Content Pipeline",
                description=(
                    "Multi-agent RAG pipeline orchestrating 6+ specialised agents for multilingual content "
                    "generation, integrated with a Django web interface. Built during a hackathon."
                ),
                technologies_used=["LangChain", "LangGraph", "RAG", "Django", "Python", "Groq"],
                start_date=datetime.date(2024, 9, 1),
                end_date=datetime.date(2024, 9, 30),
                display_order=3,
            ),
            dict(
                title="Kaggle — Applied Predictive Modelling",
                description=(
                    "Competition-grade tabular and time-series prediction. Gradient-boosting ensembles "
                    "(LightGBM, CatBoost, XGBoost), Random Forest, and Autoencoders. "
                    "Feature engineering and cross-validated optimisation; evaluated with ROC-AUC, RMSE, and F1."
                ),
                technologies_used=["Python", "LightGBM", "CatBoost", "XGBoost", "scikit-learn", "Pandas", "NumPy"],
                start_date=datetime.date(2023, 9, 1),
                end_date=datetime.date(2025, 6, 30),
                display_order=4,
            ),
        ]
        self._bulk_create(ProjectHighlight, projects_data, resume, "title")

        # ── 7. Languages ──────────────────────────────────────────────────────
        languages_data = [
            dict(language="PERSIAN", proficiency="NATIVE", display_order=1),
            dict(language="ENGLISH", proficiency="PROFESSIONAL", display_order=2),
            dict(language="FINNISH", proficiency="BEGINNER", display_order=3),
        ]
        self._bulk_create(Language, languages_data, resume, "language")

        self.stdout.write(self.style.SUCCESS("\nResume populated successfully."))

    def _upsert_skills(self, data_list, resume):
        from resume.models import Skill
        created_count = updated_count = 0
        for item in data_list:
            obj, created = Skill.objects.get_or_create(
                resume=resume,
                name=item['name'],
                category=item['category'],
                defaults={**item, 'resume': resume},
            )
            if not created:
                for field, value in item.items():
                    setattr(obj, field, value)
                obj.resume = resume
                obj.save()
                updated_count += 1
            else:
                created_count += 1
        self.stdout.write(f"  Skill: {created_count} created, {updated_count} updated.")

    def _bulk_create(self, model, data_list, resume, label_field):
        created_count = 0
        updated_count = 0
        for item in data_list:
            obj, created = model.objects.get_or_create(
                resume=resume,
                **{label_field: item[label_field]},
                defaults={**item, "resume": resume},
            )
            if not created:
                for field, value in item.items():
                    setattr(obj, field, value)
                obj.resume = resume
                obj.save()
                updated_count += 1
            else:
                created_count += 1
        self.stdout.write(
            f"  {model.__name__}: {created_count} created, {updated_count} updated."
        )
