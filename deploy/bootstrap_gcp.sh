#!/usr/bin/env bash
# One-time GCP bootstrap for AutoSRE-0. Usage: GCP_PROJECT_ID=my-proj ./deploy/bootstrap_gcp.sh
set -euo pipefail
: "${GCP_PROJECT_ID:?set GCP_PROJECT_ID}"
REGION="${GCP_REGION:-us-central1}"
SA="autosre-deployer"
SA_EMAIL="${SA}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "$GCP_PROJECT_ID"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com logging.googleapis.com iam.googleapis.com
gcloud artifacts repositories create autosre --repository-format=docker --location="$REGION" 2>/dev/null || true
gcloud iam service-accounts create "$SA" --display-name="AutoSRE-0 deployer" 2>/dev/null || true
for role in roles/run.admin roles/artifactregistry.writer roles/logging.viewer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" --member="serviceAccount:${SA_EMAIL}" --role="$role" --condition=None >/dev/null
done
gcloud iam service-accounts keys create /tmp/autosre-key.json --iam-account="$SA_EMAIL"
echo "Add /tmp/autosre-key.json contents as a *File*-type masked CI/CD variable GCP_SA_KEY, then delete the local copy."
echo "(Production hardening: replace the key with Workload Identity Federation for GitLab OIDC.)"
