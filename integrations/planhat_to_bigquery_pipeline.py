"""
planhat_to_bigquery_pipeline.py
--------------------------------
Extracts customer health signals from the Planhat REST API and lands them
in BigQuery for downstream dbt transformation and NRR/GRR analysis.

This script handles three Planhat objects per run:
    1. Companies          → raw_planhat.companies
    2. Datapoints (metrics) → raw_planhat.datapoints
    3. NPS responses      → raw_planhat.nps_responses

Design decisions:
    - Companies: refresh (low volume, schema can drift)
    - Datapoints: incremental by date (high volume, append-only)
    - NPS: incremental by created date (sparse, append-only)

Authentication: Planhat API token stored in environment variable.
BigQuery: Uses Application Default Credentials (service account in prod,
          gcloud auth in local dev).

Usage:
    python integrations/planhat_to_bigquery_pipeline.py --mode full
    python integrations/planhat_to_bigquery_pipeline.py --mode incremental --days 7

Dependencies:
    pip install requests google-cloud-bigquery python-dotenv
"""

import os
import time
import logging
import argparse
from datetime import datetime, timedelta, timezone
from typing import Generator

import requests
from dotenv import load_dotenv

# NOTE: BigQuery import is conditional - pipeline logic runs without it
# In a real environment: from google.cloud import bigquery

try:
    from google.cloud import bigquery
    BQ_AVAILABLE = True
except ImportError:
    BQ_AVAILABLE = False

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Config

PLANHAT_API_TOKEN = os.getenv("PLANHAT_API_TOKEN")
PLANHAT_BASE_URL  = "https://api.planhat.com"
BQ_PROJECT        = os.getenv("GCP_PROJECT_ID", "your-gcp-project")
BQ_DATASET        = "raw_planhat"

HEADERS = {
    "Authorization": f"Bearer {PLANHAT_API_TOKEN}",
    "Content-Type": "application/json",
}

PAGE_SIZE     = 100
RATE_LIMIT_DELAY = 0.35  # seconds between requests (~170 req/min, under 200 limit)


# Planhat API client

class PlanhatClient:
    """
    Thin wrapper around the Planhat REST API.
    Handles authentication, pagination, and rate limiting.
    """

    def __init__(self, token: str):
        if not token:
            raise ValueError(
                "PLANHAT_API_TOKEN not set. "
                "Add it to your .env file or export it as an environment variable."
            )
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        self.base_url = PLANHAT_BASE_URL

    def _get(self, endpoint: str, params: dict = None) -> list:
        """Single paginated GET - raises on non-200 responses."""
        url = f"{self.base_url}{endpoint}"
        response = self.session.get(url, params=params, timeout=30)

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            log.warning(f"Rate limited. Waiting {retry_after}s before retry.")
            time.sleep(retry_after)
            return self._get(endpoint, params)

        response.raise_for_status()
        return response.json()

    def paginate(self, endpoint: str, extra_params: dict = None) -> Generator:
        """
        Iterate through all pages of a Planhat endpoint.
        Planhat paginates via offset + limit. Stops when response is empty.
        """
        offset = 0
        params = {"limit": PAGE_SIZE, "offset": offset}
        if extra_params:
            params.update(extra_params)

        while True:
            params["offset"] = offset
            batch = self._get(endpoint, params)

            if not batch:
                log.info(f"  {endpoint}: pagination complete at offset {offset}")
                break

            yield batch
            offset += len(batch)

            # Respect rate limit
            time.sleep(RATE_LIMIT_DELAY)

    # Object-specific extractors

    def get_companies(self) -> list[dict]:
        """
        Full extract of all Company records.
        Selects only fields used in our health model to minimise payload.
        """
        fields = ",".join([
            "_id", "externalId", "name", "phase", "mr", "arr",
            "renewalDate", "contractSignedDate", "health",
            "custom.vehicle_count", "custom.legacy_system",
            "custom.country", "custom.segment",
            "csmId", "tags",
        ])

        companies = []
        log.info("Extracting Planhat companies...")

        for batch in self.paginate("/companies", extra_params={"select": fields}):
            companies.extend(batch)
            log.info(f"  Fetched {len(companies)} companies so far...")

        log.info(f"Companies extract complete: {len(companies)} records")
        return companies

    def get_datapoints(self, from_date: str, to_date: str) -> list[dict]:
        """
        Incremental extract of metric datapoints.
        from_date / to_date: ISO 8601 date strings (YYYY-MM-DD)
        """
        datapoints = []
        log.info(f"Extracting datapoints: {from_date} → {to_date}")

        for batch in self.paginate(
            "/datapoints",
            extra_params={"from": from_date, "to": to_date}
        ):
            datapoints.extend(batch)
            if len(datapoints) % 1000 == 0:
                log.info(f"  Fetched {len(datapoints)} datapoints...")

        log.info(f"Datapoints extract complete: {len(datapoints)} records")
        return datapoints

    def get_nps_responses(self, from_date: str) -> list[dict]:
        """Incremental extract of NPS survey responses."""
        responses = []
        log.info(f"Extracting NPS responses since {from_date}...")

        for batch in self.paginate(
            "/nps",
            extra_params={"from": from_date}
        ):
            responses.extend(batch)

        log.info(f"NPS extract complete: {len(responses)} records")
        return responses


# Schema transformers

def transform_company(record: dict) -> dict:
    """
    Normalise a raw Planhat Company record to our BigQuery schema.
    Handles missing custom fields, Planhat returns nothing
    for unset custom fields, not null.
    """
    custom = record.get("custom", {})
    tags = record.get("tags", [])

    return {
        "planhat_id":            record.get("_id"),
        "external_id":           record.get("externalId"),           # = SFDC Account ID
        "company_name":          record.get("name"),
        "lifecycle_phase":       record.get("phase"),
        "mrr":                   record.get("mr") or record.get("mrr"),
        "arr":                   record.get("arr"),
        "health_score":          record.get("health"),
        "renewal_date":          record.get("renewalDate"),
        "contract_start_date":   record.get("contractSignedDate"),
        "csm_id":                record.get("csmId"),
        "vehicle_count":         custom.get("vehicle_count"),
        "legacy_system":         custom.get("legacy_system"),
        "country":               custom.get("country"),
        "segment":               custom.get("segment"),
        "tags":                  ",".join(tags) if tags else None,
        "extracted_at":          datetime.now(timezone.utc).isoformat(),
    }


def transform_datapoint(record: dict) -> dict:
    """Normalise a Planhat metric datapoint."""
    return {
        "planhat_id":      record.get("_id"),
        "company_id":      record.get("companyId"),
        "external_id":     record.get("companyExternalId"),
        "dimension_id":    record.get("dimensionId"),          # e.g. "gps_adoption_pct"
        "value":           record.get("value"),
        "date":            record.get("date"),
        "extracted_at":    datetime.now(timezone.utc).isoformat(),
    }


def transform_nps(record: dict) -> dict:
    """Normalise a Planhat NPS response."""
    return {
        "planhat_id":    record.get("_id"),
        "company_id":   record.get("companyId"),
        "external_id":  record.get("companyExternalId"),
        "score":        record.get("score"),
        "feedback":     record.get("feedback"),
        "campaign_id":  record.get("campaignId"),
        "created_at":   record.get("created"),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


# BigQuery

class BigQueryWriter:
    """
    Writes transformed records to BigQuery.
    Uses WRITE_TRUNCATE for refresh tables, WRITE_APPEND for incremental.
    """

    def __init__(self, project: str, dataset: str):
        if not BQ_AVAILABLE:
            log.warning("google-cloud-bigquery not installed. Simulating BQ writes.")
            self.client = None
        else:
            self.client = bigquery.Client(project=project)
        self.dataset = dataset
        self.project = project

    def write(
        self,
        records: list[dict],
        table_name: str,
        mode: str = "WRITE_APPEND",  # or "WRITE_TRUNCATE"
    ) -> None:
        table_id = f"{self.project}.{self.dataset}.{table_name}"

        if not records:
            log.info(f"  No records to write to {table_id}")
            return

        if not self.client:
            # Simulation mode
            log.info(f"  [SIMULATION] Would write {len(records)} rows to {table_id} ({mode})")
            log.info(f"  Sample record: {records[0]}")
            return

        job_config = bigquery.LoadJobConfig(
            write_disposition=mode,
            autodetect=True,                   # In prod: use explicit schema
            ignore_unknown_values=True,
        )

        job = self.client.load_table_from_json(
            records, table_id, job_config=job_config
        )
        job.result()  # Wait for completion

        log.info(f"  ✓ Wrote {len(records)} rows to {table_id}")


# Pipeline orchestrator

def run_pipeline(mode: str = "incremental", lookback_days: int = 7):
    """
    Main pipeline entry point.

    mode="full"        → Refresh all tables. Use for initial load or schema changes.
    mode="incremental" → Append new records only, based on lookback_days.
    """
    log.info(f"Starting Planhat → BigQuery pipeline (mode={mode}, lookback={lookback_days}d)")

    client = PlanhatClient(token=PLANHAT_API_TOKEN)
    writer = BigQueryWriter(project=BQ_PROJECT, dataset=BQ_DATASET)

    today     = datetime.now(timezone.utc).date()
    from_date = (today - timedelta(days=lookback_days)).isoformat()
    to_date   = today.isoformat()

    # Companies 
    raw_companies = client.get_companies()
    transformed   = [transform_company(r) for r in raw_companies]
    writer.write(transformed, "companies", mode="WRITE_TRUNCATE")

    # Datapoints
    raw_datapoints = client.get_datapoints(from_date=from_date, to_date=to_date)
    transformed    = [transform_datapoint(r) for r in raw_datapoints]
    writer.write(transformed, "datapoints", mode="WRITE_APPEND")

    # NPS responses
    raw_nps     = client.get_nps_responses(from_date=from_date)
    transformed = [transform_nps(r) for r in raw_nps]
    writer.write(transformed, "nps_responses", mode="WRITE_APPEND")

    log.info("Pipeline complete.")


# CLI

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Planhat → BigQuery pipeline")
    parser.add_argument(
        "--mode",
        choices=["full", "incremental"],
        default="incremental",
        help="full = WRITE_TRUNCATE companies; incremental = append by date range",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Lookback window in days for incremental mode (default: 7)",
    )
    args = parser.parse_args()
    run_pipeline(mode=args.mode, lookback_days=args.days)
