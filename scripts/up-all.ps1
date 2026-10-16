# Start every profile (core + pipeline[NiFi, Airflow] + search[Elasticsearch]) with the URLs the backend needs.
$env:ELASTICSEARCH_URL = "http://elasticsearch:9200"
$env:NIFI_URL = "http://nifi:8080"
$env:AIRFLOW_URL = "http://airflow:8080"
$env:SIM_DIRECT_INGEST = "false"   # NiFi becomes the only ingestion path for the simulator's CSV files
docker compose --profile all up -d --build
