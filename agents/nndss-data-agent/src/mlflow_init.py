"""MLflow initialization for NNDSS Data Agent.

Handles CR mode auth (RHOAI 3.5 operator), CA bundle merging,
experiment setup, and prompt registration.

Pattern adapted from agentops-redhatskills-com and bank-voice-agent.
"""

import os
import tempfile


def _setup_ca_bundle() -> None:
    """Merge system CAs with Kubernetes service CA for TLS to MLflow gateway."""
    if os.environ.get("REQUESTS_CA_BUNDLE"):
        return

    system_ca = "/etc/pki/tls/certs/ca-bundle.crt"
    service_ca = "/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt"

    parts = []
    if os.path.isfile(system_ca):
        with open(system_ca) as f:
            parts.append(f.read())
    if os.path.isfile(service_ca):
        with open(service_ca) as f:
            parts.append(f.read())

    if parts:
        combined = tempfile.NamedTemporaryFile(
            mode="w", suffix=".crt", delete=False, prefix="ca-bundle-"
        )
        combined.write("\n".join(parts))
        combined.close()
        os.environ["REQUESTS_CA_BUNDLE"] = combined.name
        print(f"[mlflow] CA bundle: {combined.name}", flush=True)


def init_mlflow() -> None:
    """Configure MLflow tracing and register prompts."""
    mlflow_uri = os.environ.get("MLFLOW_TRACKING_URI", "").strip()
    if not mlflow_uri:
        return

    # Force synchronous trace export so traces are available
    # immediately for prompt linking.
    os.environ.setdefault("MLFLOW_ASYNC_TRACE_EXPORT_ENABLED", "false")

    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # Set up CA bundle for TLS to MLflow operator gateway
        _setup_ca_bundle()

        import mlflow

        # Token file auth (MLflow operator CR mode on RHOAI 3.5)
        token_file = os.environ.get("MLFLOW_TRACKING_TOKEN_FILE", "").strip()
        if token_file and os.path.isfile(token_file):
            with open(token_file) as f:
                os.environ["MLFLOW_TRACKING_TOKEN"] = f.read().strip()

        mlflow.set_tracking_uri(mlflow_uri)

        # Workspace support (MLflow operator CR mode)
        workspace = os.environ.get("MLFLOW_WORKSPACE", "").strip()
        if workspace:
            mlflow.set_workspace(workspace)

        experiment_name = os.environ.get(
            "MLFLOW_EXPERIMENT_NAME", "nndss-data-agent"
        )

        if workspace:
            # RHOAI MLflow operator gateway blocks get_experiment /
            # get_experiment_by_name. Use search_experiments to find or
            # create, then set _active_experiment_id directly.
            import mlflow.tracking.fluent as _fluent

            client = mlflow.MlflowClient()
            exps = client.search_experiments(
                filter_string=f"name = '{experiment_name}'"
            )
            if exps:
                _fluent._active_experiment_id = exps[0].experiment_id
            else:
                exp_id = client.create_experiment(experiment_name)
                _fluent._active_experiment_id = exp_id
            print(
                f"[mlflow] Workspace={workspace}  "
                f"experiment_id={_fluent._active_experiment_id}",
                flush=True,
            )
        else:
            mlflow.set_experiment(experiment_name)

        # Enable autolog for OpenAI SDK calls.
        mlflow.openai.autolog(log_traces=True)

        print(
            f"[mlflow] Tracing enabled (openai autolog) → {mlflow_uri}  "
            f"experiment={experiment_name}",
            flush=True,
        )

        # Register prompts now that MLflow auth is configured
        from src.prompts import _register_prompts
        _register_prompts()

    except Exception as exc:
        print(
            f"[mlflow] Failed to initialise (continuing without): {exc}",
            flush=True,
        )
