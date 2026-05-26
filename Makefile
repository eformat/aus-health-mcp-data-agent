# Makefile for NNDSS MCP-for-Public-Health
#
# Build and push container images to quay.io/eformat

REGISTRY     ?= quay.io/eformat
AGENT_IMAGE  ?= nndss-agent
TAG          ?= latest
PLATFORM     ?= linux/amd64

.PHONY: help build push all deploy-all eval-compile eval-submit eval-status spicedb-schema spicedb-seed spicedb-check

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

all: build push ## Build and push agent image

build: ## Build agent image
	podman build --platform $(PLATFORM) \
		-t $(REGISTRY)/$(AGENT_IMAGE):$(TAG) \
		-f agents/nndss-agent/Containerfile \
		agents/nndss-agent

push: ## Push agent image to registry
	podman push $(REGISTRY)/$(AGENT_IMAGE):$(TAG)

# ── Model ───────────────────────────────────────────────────
MAAS_BASE_URL ?= http://maas.apps.ocp.cloud.rhai-tmm.dev/prelude-maas
AGENT_MODEL   ?= qwen36-27b

set-model: ## Switch agent model: make set-model AGENT_MODEL=kimi-k2-6
	@./scripts/set-model.sh $(AGENT_MODEL)

PROMPT_MSG ?= Prompt update
register-prompt: ## Register system_prompt.md in MLflow: make register-prompt PROMPT_MSG="v4 changes"
	@./scripts/register-prompt.sh "$(PROMPT_MSG)"

# ── Deployment ──────────────────────────────────────────────
deploy-all: ## Deploy everything (MinIO → Trino → Agent → DSPA → Eval)
	./scripts/deploy-all.sh

# ── Evaluation ──────────────────────────────────────────────
eval-compile: ## Compile eval pipeline to YAML
	python3 evaluations/pipeline.py --compile

eval-submit: ## Compile and submit eval pipeline run
	./scripts/eval-submit.sh

eval-status: ## Check latest eval pipeline run status
	@./scripts/eval-status.sh

# ── SpiceDB ────────────────────────────────────────────────
SPICEDB_NS ?= spicedb

spicedb-schema: ## Write SpiceDB schema from schema.zed
	@./scripts/spicedb-manage.sh schema

spicedb-seed: ## Seed SpiceDB with test users and relationships
	@./scripts/spicedb-manage.sh seed

USER ?= admin
PERM ?= query
DATASET ?= notifications
spicedb-check: ## Check permission: make spicedb-check USER=admin PERM=query DATASET=notifications
	@./scripts/spicedb-manage.sh check $(USER) $(PERM) $(DATASET)
