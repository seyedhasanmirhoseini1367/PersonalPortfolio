"""
Management command to seed the database with sample AI/ML/DS/DL stories.
Usage: python manage.py seed_stories
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from stories.models import Story, Tag

User = get_user_model()

TAGS_DATA = [
    {"name": "Artificial Intelligence", "description": "Stories about AI concepts, tools, and trends."},
    {"name": "Data Science", "description": "Stories covering data analysis, visualization, and workflows."},
    {"name": "Machine Learning", "description": "Stories about ML algorithms, pipelines, and best practices."},
    {"name": "Deep Learning", "description": "Stories focused on neural networks and deep learning techniques."},
    {"name": "Python", "description": "Python programming tips and libraries for data science and ML."},
    {"name": "NLP", "description": "Natural Language Processing concepts and applications."},
]

STORIES_DATA = [
    {
        "title": "The Rise of Artificial Intelligence: Transforming Every Industry",
        "excerpt": (
            "Artificial Intelligence is no longer a futuristic concept — it is reshaping healthcare, finance, "
            "education, and beyond. Discover how AI is being applied today and what the next decade holds."
        ),
        "content": """Artificial Intelligence (AI) has moved from science fiction into everyday reality faster than almost anyone predicted.
Just a decade ago, self-driving cars and AI-powered medical diagnoses were distant dreams. Today, they are being tested and deployed at scale.

What Exactly Is Artificial Intelligence?

At its core, AI refers to systems that can perform tasks that typically require human intelligence — reasoning, learning, problem-solving, understanding language, and perceiving the environment.
Unlike traditional software that follows rigid rules, modern AI systems learn patterns from data and generalize to new situations.

How AI Is Transforming Industries

Healthcare
AI is accelerating drug discovery, detecting cancers from medical images with radiologist-level accuracy, and predicting patient deterioration before doctors notice clinical signs.
Companies like DeepMind have already demonstrated AI that can diagnose over 50 eye diseases from retinal scans.

Finance
Banks use AI to detect fraudulent transactions in real time, assess credit risk more fairly, and power algorithmic trading systems that execute thousands of trades per second based on market signals.

Education
Adaptive learning platforms adjust the difficulty and style of content based on each student's progress.
AI tutors provide personalized feedback 24/7, democratizing access to quality education regardless of geography.

Manufacturing
Predictive maintenance powered by AI monitors machinery sensors to detect anomalies before equipment fails, saving billions in downtime costs annually.

The Ethical Dimension

With great power comes great responsibility. As AI systems influence hiring decisions, loan approvals, and even criminal sentencing, ensuring they are fair, transparent, and accountable is critical.
Researchers and policymakers worldwide are working on frameworks to govern AI responsibly.

What Comes Next?

The next frontier is Artificial General Intelligence (AGI) — systems that can reason across domains the way humans do.
While AGI remains an open research challenge, the progress in narrow AI is staggering.
From large language models that write code and prose to reinforcement learning agents that master complex games, the pace of innovation shows no signs of slowing.

Whether you are a student, professional, or curious observer, understanding AI is becoming as essential as understanding electricity.
The question is no longer whether AI will transform your field — it is how soon and how deeply.""",
        "tags": ["Artificial Intelligence", "Machine Learning"],
        "is_featured": True,
    },
    {
        "title": "Data Science From Scratch: A Practical End-to-End Workflow",
        "excerpt": (
            "Data Science is not just about building models. It is a disciplined process of collecting, cleaning, "
            "exploring, modeling, and communicating data. Walk through a complete DS workflow with real examples."
        ),
        "content": """Data Science is one of the most sought-after skills of the 21st century, yet it is widely misunderstood.
Many beginners jump straight into machine learning algorithms without appreciating that the bulk of a data scientist's work happens long before any model is trained.

Step 1 — Define the Problem

Every successful data science project starts with a crisp business question.
"Can we predict which customers are likely to churn in the next 30 days?" is actionable.
"Tell me something interesting about our data" is not.

Step 2 — Collect the Data

Data comes from many sources: relational databases, APIs, web scraping, sensors, and third-party providers.
Understanding the data's provenance — how it was collected and what biases it may carry — is as important as the data itself.

Step 3 — Clean and Preprocess

Real-world data is messy. Missing values, duplicates, inconsistent formatting, and outliers are the norm, not the exception.
The saying "garbage in, garbage out" is a fundamental truth in data science.

Common preprocessing tasks include:
- Imputing or dropping missing values
- Encoding categorical variables (one-hot encoding, label encoding, target encoding)
- Scaling numerical features (standardization, min-max normalization)
- Handling outliers (clipping, winsorization, or domain-informed removal)

Step 4 — Exploratory Data Analysis (EDA)

Before modeling, spend time understanding your data.
Visualize distributions, correlations, and relationships between variables.
Tools like pandas, matplotlib, seaborn, and plotly make EDA both powerful and visual.

Step 5 — Feature Engineering

Raw data rarely has the perfect representation for a model.
Feature engineering — creating new variables that capture domain knowledge — is often where data scientists add the most value.
Examples: extracting day-of-week from a timestamp, computing moving averages, or creating interaction terms between features.

Step 6 — Model Building and Evaluation

Choose a model appropriate for your problem (classification, regression, clustering, etc.), train it on a portion of your data, and evaluate it on a held-out test set.

Critical metrics to understand:
- Classification: accuracy, precision, recall, F1, AUC-ROC
- Regression: MAE, RMSE, R²

Always use cross-validation to get reliable performance estimates and avoid overfitting.

Step 7 — Communicate Results

The final deliverable is not a model — it is insight.
Data scientists who can translate technical results into business language and compelling visualizations create far more impact.

Tools of the Trade

The modern data scientist's toolkit includes Python (pandas, scikit-learn, matplotlib), SQL for data extraction, Jupyter notebooks for exploration, and cloud platforms (AWS, GCP, Azure) for scalable computation.

Final Thoughts

Data Science is simultaneously a technical discipline and a creative endeavor.
Mastering it requires curiosity, statistical intuition, engineering skill, and the humility to know that your first model is rarely your best one.""",
        "tags": ["Data Science", "Python"],
        "is_featured": True,
    },
    {
        "title": "Machine Learning Demystified: Algorithms Every Practitioner Should Know",
        "excerpt": (
            "From linear regression to gradient boosting, this guide breaks down the most important ML algorithms, "
            "explaining when to use each one and what pitfalls to watch out for."
        ),
        "content": """Machine Learning (ML) is the engine powering most modern AI applications.
At its heart, ML is about building systems that learn from data to make predictions or decisions without being explicitly programmed for each scenario.

The Three Paradigms of Machine Learning

Supervised Learning
The model learns from labeled examples — input-output pairs — and learns to map inputs to outputs.
Common tasks: classification (spam detection, image recognition) and regression (house price prediction, demand forecasting).

Unsupervised Learning
The model finds structure in unlabeled data.
Common tasks: clustering (customer segmentation), dimensionality reduction (PCA, t-SNE), and anomaly detection.

Reinforcement Learning
An agent learns by interacting with an environment, receiving rewards for good actions and penalties for bad ones.
Applications: game playing (AlphaGo), robotics, and recommendation systems.

Key Algorithms Every Practitioner Should Know

Linear and Logistic Regression
The simplest and most interpretable models.
Linear regression predicts a continuous value; logistic regression predicts class probabilities.
Always start with these baselines before reaching for complexity.

Decision Trees and Random Forests
Decision trees split data on feature thresholds, building an interpretable flowchart.
Random forests ensemble hundreds of trees, dramatically reducing variance and improving generalization.

Gradient Boosting Machines (GBM)
XGBoost, LightGBM, and CatBoost dominate structured-data competitions.
They build trees sequentially, each correcting the errors of the previous one.
Extremely powerful, but require careful hyperparameter tuning.

Support Vector Machines (SVM)
SVMs find the maximum-margin boundary between classes.
They excel in high-dimensional spaces and are robust to overfitting, but do not scale well to very large datasets.

K-Nearest Neighbors (KNN)
A lazy learner that classifies a point by the majority class among its K nearest neighbors.
Simple and effective for low-dimensional data; slow and memory-intensive at scale.

The Bias-Variance Tradeoff

The central challenge in ML is the bias-variance tradeoff:
- High bias (underfitting): The model is too simple to capture the data's patterns.
- High variance (overfitting): The model memorizes the training data but fails on new examples.

Regularization techniques (L1/Lasso, L2/Ridge, dropout in neural networks) help manage this tradeoff.

Cross-Validation and Hyperparameter Tuning

Always evaluate your model using cross-validation — split your data into K folds, train on K-1, and evaluate on the remaining fold, rotating through all possibilities.

For hyperparameter tuning, grid search, random search, and Bayesian optimization are your tools.
Modern libraries like Optuna make this process nearly automatic.

Practical Advice

Start simple. A well-tuned logistic regression often beats a poorly tuned neural network.
Understand your data before reaching for powerful models.
And remember: model interpretability matters in production — stakeholders need to understand and trust the system's decisions.""",
        "tags": ["Machine Learning", "Python", "Data Science"],
        "is_featured": False,
    },
    {
        "title": "Deep Learning Unveiled: Neural Networks That Are Changing the World",
        "excerpt": (
            "Deep learning has achieved superhuman performance in image recognition, language translation, and protein "
            "folding. This story explains how neural networks work and why they are so powerful."
        ),
        "content": """Deep Learning (DL) is a subfield of machine learning that uses neural networks with many layers — hence "deep" — to learn hierarchical representations of data.
It is the technology behind image recognition systems, large language models, autonomous vehicles, and AlphaFold's landmark protein structure predictions.

The Building Block: The Artificial Neuron

Inspired loosely by biological neurons, an artificial neuron:
1. Takes a weighted sum of its inputs
2. Adds a bias term
3. Passes the result through a non-linear activation function (ReLU, sigmoid, tanh, GELU)

Stack thousands of these neurons into layers, connect the layers, and you have a neural network.

Why "Deep" Matters

Shallow networks with one or two layers can approximate any function in theory (the universal approximation theorem), but they require exponentially many neurons for complex tasks.
Deep networks learn hierarchical features: early layers detect edges and textures; later layers combine them into complex concepts like "cat face" or "fraudulent transaction pattern."

Key Deep Learning Architectures

Convolutional Neural Networks (CNNs)
Designed for grid-structured data like images.
Convolutional filters slide across the image, detecting local patterns regardless of their position.
CNNs power face recognition, medical imaging, and self-driving car perception systems.

Recurrent Neural Networks (RNNs) and LSTMs
Designed for sequential data like time series and text.
They maintain a hidden state that carries information across time steps.
Long Short-Term Memory (LSTM) networks solve the vanishing gradient problem that plagues vanilla RNNs.

Transformers and Attention
The architecture behind GPT, BERT, and virtually all modern large language models.
Self-attention mechanisms allow the model to weigh the relevance of every input token against every other, capturing long-range dependencies that RNNs struggle with.
Transformers now dominate not just NLP but also computer vision (Vision Transformers) and protein biology (AlphaFold).

Training Deep Networks

Training a deep network involves:
1. Forward pass: compute predictions
2. Loss computation: measure how wrong the predictions are (cross-entropy, MSE, etc.)
3. Backward pass (backpropagation): compute gradients of the loss with respect to every parameter
4. Parameter update: adjust weights using gradient descent (SGD, Adam, AdamW)

Key challenges: vanishing/exploding gradients, overfitting, computational cost, and the need for massive labeled datasets.

Modern Solutions: Transfer Learning and Fine-Tuning

Training large models from scratch requires enormous compute.
Transfer learning lets you start from a pre-trained model (e.g., ResNet trained on ImageNet, or GPT-2) and fine-tune it on your task with much less data and compute.

This democratization of deep learning has been transformative — enabling small teams to achieve state-of-the-art results on specialized tasks.

The Future of Deep Learning

Multimodal models that understand images, text, audio, and video simultaneously are the frontier.
Models like GPT-4V, Gemini, and Claude combine modalities to reason more like humans.
Meanwhile, researchers are pursuing architectures that are more efficient, interpretable, and robust than today's transformers.

Deep learning is not magic — it is applied mathematics, statistics, and engineering at scale.
Understanding the fundamentals allows you to build, debug, and innovate rather than just consume.""",
        "tags": ["Deep Learning", "Machine Learning", "Artificial Intelligence"],
        "is_featured": True,
    },
    {
        "title": "Natural Language Processing in 2025: From Tokenization to Large Language Models",
        "excerpt": (
            "NLP has undergone a revolution. From classical bag-of-words approaches to billion-parameter transformers, "
            "this story traces the evolution of machines that understand human language."
        ),
        "content": """Natural Language Processing (NLP) is the branch of AI concerned with enabling computers to understand, interpret, and generate human language.
It is the technology behind your email spam filter, Google Translate, customer service chatbots, and the large language models (LLMs) that have captured the world's imagination.

The Classical Era: Rule-Based and Statistical NLP

Early NLP systems relied on hand-crafted linguistic rules.
Parsing sentences required grammarians to specify the rules of language explicitly — a brittle and labor-intensive approach.

The statistical revolution of the 1990s and 2000s changed everything.
Instead of rules, models learned from large text corpora.
Techniques like n-gram language models, TF-IDF for information retrieval, and Hidden Markov Models for part-of-speech tagging became standard.

Word Embeddings: Teaching Computers About Meaning

A breakthrough came with word embeddings — dense vector representations that capture semantic meaning.
Word2Vec (2013) showed that vector arithmetic could encode relationships: "king" - "man" + "woman" ≈ "queen".
GloVe and fastText followed, each improving on the approach.

The problem: these embeddings were static.
The word "bank" has the same vector whether you mean a river bank or a financial institution.

The Transformer Revolution

The 2017 paper "Attention Is All You Need" introduced the Transformer architecture and rendered most prior approaches obsolete.
Transformers generate contextual embeddings — the representation of each word is influenced by every other word in the sentence.

BERT (2018) trained a transformer to understand language by predicting masked words, creating powerful general-purpose representations.
GPT (2018) trained a transformer to predict the next word, enabling fluent text generation.

Scaling to Large Language Models

Researchers discovered that scaling up — more parameters, more data, more compute — produced qualitatively new capabilities.
GPT-3 (175 billion parameters) could write essays, answer questions, and even code with minimal examples.

Modern LLMs like GPT-4, Claude, and Gemini demonstrate emergent abilities: translation across hundreds of languages, multi-step reasoning, code generation, and creative writing — all from a single model.

Key NLP Tasks and Applications

Text Classification: sentiment analysis, topic categorization, spam detection
Named Entity Recognition (NER): extracting people, places, organizations from text
Machine Translation: converting text between languages
Question Answering: retrieving or generating answers from context
Text Summarization: condensing long documents into key points
Conversational AI: chatbots and virtual assistants

Challenges and Frontiers

Despite remarkable progress, NLP faces real challenges:
- Hallucination: LLMs sometimes generate plausible-sounding but false information
- Bias: models reflect and can amplify biases present in training data
- Reasoning: multi-step logical and mathematical reasoning remains an active research area
- Efficiency: deploying billion-parameter models at scale requires significant engineering

Retrieval-Augmented Generation (RAG) — combining LLMs with a knowledge retrieval system — is one of the most promising approaches to grounding models in factual, up-to-date information.

The field of NLP is arguably the fastest-moving area in all of AI.
Staying current requires reading papers, experimenting with open-source models, and engaging with the vibrant research community.""",
        "tags": ["NLP", "Deep Learning", "Artificial Intelligence"],
        "is_featured": False,
    },
]


class Command(BaseCommand):
    help = "Seed the database with sample AI/ML/DS/DL stories"

    def add_arguments(self, parser):
        parser.add_argument(
            "--author",
            type=str,
            default=None,
            help="Username of the author for the seeded stories. Defaults to the first superuser.",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete all existing stories and tags before seeding.",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            count = Story.objects.count()
            Story.objects.all().delete()
            Tag.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Cleared {count} existing stories and all tags."))

        # Resolve author
        username = options["author"]
        if username:
            try:
                author = User.objects.get(username=username)
            except User.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"User '{username}' not found."))
                return
        else:
            author = User.objects.filter(is_superuser=True).first()
            if not author:
                author = User.objects.first()
            if not author:
                self.stderr.write(self.style.ERROR("No users found. Create a superuser first."))
                return

        self.stdout.write(f"Using author: {author.username}")

        # Create tags
        tag_objects = {}
        for tag_data in TAGS_DATA:
            tag, created = Tag.objects.get_or_create(
                name=tag_data["name"],
                defaults={"description": tag_data["description"]},
            )
            tag_objects[tag.name] = tag
            status = "Created" if created else "Exists"
            self.stdout.write(f"  Tag [{status}]: {tag.name}")

        # Create stories
        created_count = 0
        for story_data in STORIES_DATA:
            if Story.objects.filter(title=story_data["title"]).exists():
                self.stdout.write(self.style.WARNING(f"  Story already exists: {story_data['title'][:60]}..."))
                continue

            story = Story.objects.create(
                author=author,
                title=story_data["title"],
                excerpt=story_data["excerpt"],
                content=story_data["content"],
                status=Story.Status.PUBLISHED,
                is_featured=story_data.get("is_featured", False),
                allow_comments=True,
                published_at=timezone.now(),
            )

            for tag_name in story_data["tags"]:
                if tag_name in tag_objects:
                    story.tags.add(tag_objects[tag_name])

            created_count += 1
            self.stdout.write(self.style.SUCCESS(f"  Created story: {story.title[:60]}..."))

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone! Created {created_count} stories and {len(tag_objects)} tags for author '{author.username}'."
            )
        )
