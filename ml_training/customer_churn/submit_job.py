import os
from azure.ai.ml import MLClient, command, Input, Output
from azure.ai.ml.entities import Environment
from azure.ai.ml.constants import AssetTypes
from azure.identity import DefaultAzureCredential

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Connect to Azure ML workspace ─────────────────────────────────────────────
ml_client = MLClient(
    DefaultAzureCredential(),
    subscription_id="55e3ff52-09b3-4231-985c-1362e939fc4b",
    resource_group_name="hasanai_group",
    workspace_name="hasanai-ml"
)

# ── Define environment ────────────────────────────────────────────────────────
env = Environment(
    name="customer-churn-env",
    conda_file=os.path.join(SCRIPT_DIR, "conda.yaml"),
    image="mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu20.04"
)

# ── Submit training job ───────────────────────────────────────────────────────
job = command(
    code=SCRIPT_DIR,
    command="python training.py --data_path ${{inputs.data_path}} --output_path ${{outputs.output_path}}",
    inputs={
        "data_path": Input(
            type=AssetTypes.URI_FOLDER,
            path="azureml:customer-churn:1"
        )
    },
    outputs={
        "output_path": Output(
            type=AssetTypes.URI_FOLDER,
            mode="upload",
            name="customer-churn-models",
            path="azureml://datastores/workspaceblobstore/paths/customer-churn/models/"
        )
    },
    environment=env,
    compute="hasanai-models",
    display_name="customer-churn-training",
    experiment_name="customer-churn-ml"
)
returned_job = ml_client.jobs.create_or_update(job)
print(f"Job submitted! Name: {returned_job.name}")
print(f"URL: {returned_job.studio_url}")
