"""
azure_ml_deploy.py
==================
Deploy the EEG Foundation Model to Azure ML as a real-time inference endpoint.

LEARNING GUIDE — read this file top-to-bottom to understand Azure ML concepts.

────────────────────────────────────────────────────────────
AZURE ML MENTAL MODEL (read this first)
────────────────────────────────────────────────────────────

Azure ML has 5 core concepts you need to know:

1. WORKSPACE
   The root container for everything. Like a project folder in the cloud.
   One workspace per project/team. Contains models, data, experiments, endpoints.

2. MODEL REGISTRY
   A versioned store for your .pt / .pkl / .h5 files.
   You upload a model once → it gets a name + version (e.g. "eeg-rt-model:1").
   You can promote models (staging → production) without changing code.

3. ENVIRONMENT
   A Docker image + conda/pip spec that defines your runtime.
   Like a requirements.txt but reproducible on any machine.
   Azure ML caches environments — only rebuilds when you change the spec.

4. MANAGED ENDPOINT
   A URL that accepts HTTP POST requests and returns predictions.
   Think: a Flask/Django endpoint, but fully managed (auto-scaling, health checks,
   TLS, logging) with no server to manage.
   Two types:
     - Online endpoint  → real-time, always on, <100ms latency
     - Batch endpoint   → processes large files on a schedule

5. DEPLOYMENT
   The combination of (model + environment + compute SKU) assigned to an endpoint.
   One endpoint can have multiple deployments (e.g. 90% traffic → v1, 10% → v2).
   This is how you do A/B testing or safe rollouts.

────────────────────────────────────────────────────────────
WORKFLOW
────────────────────────────────────────────────────────────
  Local training
      ↓
  Register model in Azure ML Model Registry   ← step A
      ↓
  Define Environment (pip packages)            ← step B
      ↓
  Write scoring script (score.py)              ← step C
      ↓
  Create Managed Online Endpoint               ← step D
      ↓
  Deploy to endpoint                           ← step E
      ↓
  Test endpoint with curl / Python SDK         ← step F
      ↓
  Call from Django portfolio                   ← step G

────────────────────────────────────────────────────────────
PREREQUISITES
────────────────────────────────────────────────────────────
  pip install azure-ai-ml azure-identity

  You also need:
  - An Azure subscription
  - A Resource Group (e.g. "rg-portfolio")
  - An Azure ML Workspace (create in portal or with CLI)

  az group create -n rg-portfolio -l northeurope
  az ml workspace create -n eeg-workspace -g rg-portfolio

────────────────────────────────────────────────────────────
"""

import os
from azure.ai.ml import MLClient
from azure.ai.ml.entities import (
    Model,
    ManagedOnlineEndpoint,
    ManagedOnlineDeployment,
    Environment,
    CodeConfiguration,
)
from azure.ai.ml.constants import AssetTypes
from azure.identity import DefaultAzureCredential

# ── STEP 0: Connection config ─────────────────────────────────────────────────
# These values come from your Azure ML workspace.
# Find them: portal.azure.com → your workspace → "View SDK connection details"

SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID", "your-subscription-id")
RESOURCE_GROUP  = os.environ.get("AZURE_RESOURCE_GROUP",  "rg-portfolio")
WORKSPACE_NAME  = os.environ.get("AZURE_WORKSPACE_NAME",  "eeg-workspace")

# ── STEP 1: Authenticate ──────────────────────────────────────────────────────
# DefaultAzureCredential tries in order:
#   1. Environment variables (AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID)
#   2. Managed Identity (when running inside Azure)
#   3. Azure CLI login (az login) ← easiest for local development
#
# For local dev: just run `az login` in your terminal first.

credential = DefaultAzureCredential()
ml_client  = MLClient(credential, SUBSCRIPTION_ID, RESOURCE_GROUP, WORKSPACE_NAME)

print(f"Connected to workspace: {WORKSPACE_NAME}")


# ── STEP A: Register the model ────────────────────────────────────────────────
# WHY: Versioned model storage. If you retrain, you register v2, v3, etc.
#      You can always roll back to a previous version.
# HOW: Point to your local .pt file — Azure ML uploads it automatically.

def register_model(challenge: int) -> Model:
    if challenge == 1:
        local_path  = "D:/eegchallenge_results/finetuning_20260426_034840/weights_challenge_1.pt"
        model_name  = "eeg-rt-predictor"
        description = "EEG Foundation Model fine-tuned for reaction time prediction (NeurIPS 2025 Challenge 1)"
    else:
        local_path  = "D:/eegchallenge_results/challenge2_externalizing_unfrozen_20260426_094813/weights_challenge_2.pt"
        model_name  = "eeg-externalizing-predictor"
        description = "EEG Foundation Model fine-tuned for externalizing score prediction (NeurIPS 2025 Challenge 2)"

    model = Model(
        path        = local_path,
        name        = model_name,
        description = description,
        type        = AssetTypes.CUSTOM_MODEL,  # custom (not sklearn/mlflow/etc)
    )
    registered = ml_client.models.create_or_update(model)
    print(f"Registered model: {registered.name}:{registered.version}")
    return registered


# ── STEP B: Define the environment ────────────────────────────────────────────
# WHY: Reproducible runtime. Azure ML builds this into a Docker image once.
#      All requests to your endpoint run in this exact environment.
# HOW: Provide a conda YAML or pip requirements list.

def create_environment() -> Environment:
    env = Environment(
        name        = "eeg-inference-env",
        description = "EEG Foundation Model inference environment",
        conda_file  = {
            "name": "eeg-inference",
            "channels": ["conda-forge"],
            "dependencies": [
                "python=3.11",
                "pip",
                {"pip": [
                    "torch==2.2.0",
                    "numpy==1.26.4",
                    "scikit-learn==1.4.2",
                    "mne==1.7.0",
                    "pandas==2.2.0",
                    "azureml-defaults",   # required for AzureML scoring
                ]},
            ],
        },
        # Alternatively use a pre-built base image:
        # image="mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu22.04:latest",
    )
    registered = ml_client.environments.create_or_update(env)
    print(f"Environment registered: {registered.name}:{registered.version}")
    return registered


# ── STEP C: The scoring script ─────────────────────────────────────────────────
# score.py is what Azure ML calls for every inference request.
# It must have two functions:
#   init()  — called once when the container starts (load model here)
#   run()   — called for every request (parse input → predict → return)
#
# The file is written to disk by this script so it can be uploaded.

SCORE_PY_CONTENT = '''
"""score.py — Azure ML scoring script for EEG Foundation Model."""
import os, sys, json, io
import numpy as np
import torch

# Azure ML sets AZUREML_MODEL_DIR to the directory where the model was downloaded
MODEL_DIR = os.environ.get("AZUREML_MODEL_DIR", ".")
MODEL     = None


def init():
    """Called once when the endpoint container starts. Load model here."""
    global MODEL
    import sys

    # The pretrain_model.py is uploaded alongside score.py
    sys.path.insert(0, os.path.dirname(__file__))
    from pretrain_model import EEGFoundationModel

    # Find the .pt bundle
    bundle_path = None
    for fname in os.listdir(MODEL_DIR):
        if fname.endswith(".pt"):
            bundle_path = os.path.join(MODEL_DIR, fname)
            break

    if bundle_path is None:
        raise RuntimeError(f"No .pt file found in {MODEL_DIR}")

    bundle = torch.load(bundle_path, map_location="cpu", weights_only=False)
    cfg    = bundle["model_config"]
    task   = bundle["task_name"]

    model = EEGFoundationModel(
        n_channels       = cfg["n_channels"],
        patch_size        = cfg["patch_size"],
        d_model           = cfg["d_model"],
        n_heads           = cfg["n_heads"],
        n_encoder_layers  = cfg["n_encoder_layers"],
        n_decoder_layers  = cfg["n_decoder_layers"],
        dim_feedforward   = cfg["dim_feedforward"],
        dropout           = cfg["dropout"],
    )
    model.add_task_head(task, "regression", output_dim=1)
    model.load_state_dict(bundle["model_state_dict"], strict=False)
    model.eval()

    MODEL = {"model": model, "task": task, "bundle": bundle}
    print(f"Model loaded. Task: {task}")


def run(raw_data: str) -> str:
    """
    Called for each inference request.

    Input JSON format:
    {
        "data": [[...129 channels...], [...200 samples each...]]
    }
    The array shape must be (129, 200) — channels × samples.

    Returns JSON:
    {
        "prediction": -0.067,
        "prediction_label": "590 ms  (z=-0.07)",
        "task": "rt"
    }
    """
    try:
        body  = json.loads(raw_data)
        arr   = np.array(body["data"], dtype=np.float32)  # (129, 200)

        # z-score normalise per channel
        mean  = arr.mean(axis=1, keepdims=True)
        std   = arr.std(axis=1,  keepdims=True)
        std[std == 0] = 1e-8
        arr   = (arr - mean) / std

        x = torch.tensor(arr[np.newaxis], dtype=torch.float32)  # (1, 129, 200)

        with torch.no_grad():
            out  = MODEL["model"](x, mode="finetune", task_name=MODEL["task"])
            pred = float(out["prediction"].squeeze().item())

        return json.dumps({"prediction": round(pred, 4), "task": MODEL["task"]})

    except Exception as e:
        return json.dumps({"error": str(e)})
'''


def write_score_script(directory: str = "azure_scoring"):
    """Write score.py + copy pretrain_model.py to upload directory."""
    import shutil
    os.makedirs(directory, exist_ok=True)

    with open(os.path.join(directory, "score.py"), "w") as f:
        f.write(SCORE_PY_CONTENT)

    # Copy the model architecture file so score.py can import it
    src = os.path.join(os.path.dirname(__file__), "pretrain_model.py")
    shutil.copy(src, os.path.join(directory, "pretrain_model.py"))
    print(f"Scoring scripts written to: {directory}/")


# ── STEP D: Create the endpoint ───────────────────────────────────────────────
# An endpoint is just a DNS name + auth key.
# The actual compute (deployment) is added in the next step.
# WHY separate: you can swap the deployment (new model version) without
# changing the URL your Django app calls.

def create_endpoint(endpoint_name: str) -> ManagedOnlineEndpoint:
    endpoint = ManagedOnlineEndpoint(
        name        = endpoint_name,
        description = "EEG Foundation Model real-time inference",
        auth_mode   = "key",   # "key" = API key auth; "aml_token" = AAD token
    )
    created = ml_client.online_endpoints.begin_create_or_update(endpoint).result()
    print(f"Endpoint created: {created.name}")
    print(f"Scoring URI: {created.scoring_uri}")
    return created


# ── STEP E: Create the deployment ─────────────────────────────────────────────
# Deployment binds: model + environment + scoring script + compute SKU.
# instance_type options (cheapest first):
#   Standard_F2s_v2  — 2 vCPU, 4 GB RAM, ~$0.10/hr  (good for small models)
#   Standard_DS2_v2  — 2 vCPU, 7 GB RAM, ~$0.14/hr
#   Standard_NC4as_T4_v3 — GPU (T4), ~$0.50/hr      (not needed for inference)

def create_deployment(
    endpoint_name: str,
    model: Model,
    environment: Environment,
    scoring_dir: str = "azure_scoring",
    deployment_name: str = "blue",
) -> ManagedOnlineDeployment:
    deployment = ManagedOnlineDeployment(
        name            = deployment_name,
        endpoint_name   = endpoint_name,
        model           = model,
        environment     = environment,
        code_configuration = CodeConfiguration(
            code        = scoring_dir,
            scoring_script = "score.py",
        ),
        instance_type   = "Standard_F2s_v2",
        instance_count  = 1,
    )
    created = ml_client.online_deployments.begin_create_or_update(deployment).result()

    # Route 100% of traffic to this deployment
    endpoint = ml_client.online_endpoints.get(endpoint_name)
    endpoint.traffic = {deployment_name: 100}
    ml_client.online_endpoints.begin_create_or_update(endpoint).result()

    print(f"Deployment ready: {created.name}")
    return created


# ── STEP F: Test the endpoint ─────────────────────────────────────────────────
# HOW TO TEST WITH CURL (replace values from portal):
#
#   curl -X POST https://<endpoint>.inference.ml.azure.com/score \
#     -H "Authorization: Bearer <API_KEY>" \
#     -H "Content-Type: application/json" \
#     -d '{"data": [[...129 rows × 200 columns...]]}'
#
# OR with Python SDK:

def test_endpoint(endpoint_name: str, sample_npy_path: str):
    import json
    arr  = np.load(sample_npy_path).tolist()
    body = json.dumps({"data": arr})

    response = ml_client.online_endpoints.invoke(
        endpoint_name    = endpoint_name,
        deployment_name  = "blue",
        request_file     = None,
        request_body     = body,
    )
    print(f"Test response: {response}")


# ── STEP G: Call from Django (azure_ml_client.py) ─────────────────────────────
# See: projects/inference/azure_ml_client.py
# Pattern: store endpoint URL + API key in Django settings / env vars.
# Call with a plain requests.post() — no Azure SDK needed at runtime.


# ── MAIN — run all steps ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Deploy EEG model to Azure ML")
    parser.add_argument("--challenge", type=int, choices=[1, 2], default=1)
    parser.add_argument("--endpoint",  type=str, default="eeg-foundation-endpoint")
    args = parser.parse_args()

    # A: Register model
    model = register_model(args.challenge)

    # B: Environment
    env = create_environment()

    # C: Scoring scripts
    write_score_script()

    # D: Endpoint
    endpoint = create_endpoint(args.endpoint)

    # E: Deployment
    create_deployment(args.endpoint, model, env)

    # F: Test
    sample = (
        "D:/PersonalPortfolio/projects/inference/sample_eeg_ch1.npy"
        if args.challenge == 1
        else "D:/PersonalPortfolio/projects/inference/sample_eeg_ch2.npy"
    )
    test_endpoint(args.endpoint, sample)

    print("\n=== Deployment complete ===")
    print(f"Your endpoint: {ml_client.online_endpoints.get(args.endpoint).scoring_uri}")
    print("Add to Django settings:")
    print(f"  EEG_AZURE_ENDPOINT = '<scoring_uri>'")
    print(f"  EEG_AZURE_API_KEY  = '<key from portal>'")
