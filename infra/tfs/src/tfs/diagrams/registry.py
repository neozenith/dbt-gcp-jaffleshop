"""Resource -> diagram-node registry, and the noise/edge classification rules.

This is the single editable surface that maps a Terraform resource *type* to an
icon + category. It is **cloud-agnostic**: GCP, AWS, Azure and Kubernetes are all
populated below. Adding a resource is a one-line row here; adding a whole provider
means vendoring its stencil library (see `scripts/extract_stencils.py`).

A ``stencil_id`` is ``"<library>/<shape>"`` as it appears in draw.io's stencil
libraries (e.g. ``"mxgraph.gcp2/Cloud Run"``, ``"mxgraph.aws4/lambda"``). The
vendored asset (``assets/stencils.json``) is keyed by exactly these ids, and the
extractor asserts every id referenced here is present.

The mapping is generated/refreshed by resolving candidate shape names against the
vendored asset (keeps icon ids honest); unmapped types fall back to a plain box.
"""

from __future__ import annotations

import re

# tf resource type -> (stencil_id, category label). Unknown types render as a
# plain (icon-less) box under the "Other" category — provider-neutral fallback.
RESOURCE_STENCILS: dict[str, tuple[str, str]] = {
    # --- Google Cloud ---
    "google_cloud_run_v2_service": ("mxgraph.gcp2/Cloud Run", "Compute"),
    "google_cloud_run_service": ("mxgraph.gcp2/Cloud Run", "Compute"),
    "google_compute_instance": ("mxgraph.gcp2/Compute Engine", "Compute"),
    "google_compute_instance_template": ("mxgraph.gcp2/Compute Engine", "Compute"),
    "google_compute_instance_group_manager": ("mxgraph.gcp2/Compute Engine", "Compute"),
    "google_app_engine_application": ("mxgraph.gcp2/App Engine", "Compute"),
    "google_cloudfunctions_function": ("mxgraph.gcp2/Cloud Functions", "Compute"),
    "google_cloudfunctions2_function": ("mxgraph.gcp2/Cloud Functions", "Compute"),
    "google_container_cluster": ("mxgraph.gcp2/Container Engine", "Containers"),
    "google_container_node_pool": ("mxgraph.gcp2/Container Engine", "Containers"),
    "google_storage_bucket": ("mxgraph.gcp2/Cloud Storage", "Storage"),
    "google_filestore_instance": ("mxgraph.gcp2/Cloud Filestore", "Storage"),
    "google_compute_disk": ("mxgraph.gcp2/Persistent Disk", "Storage"),
    "google_bigquery_dataset": ("mxgraph.gcp2/BigQuery", "Analytics"),
    "google_bigquery_table": ("mxgraph.gcp2/BigQuery", "Analytics"),
    "google_bigtable_instance": ("mxgraph.gcp2/Cloud Bigtable", "Data"),
    "google_bigtable_table": ("mxgraph.gcp2/Cloud Bigtable", "Data"),
    "google_spanner_instance": ("mxgraph.gcp2/Cloud Spanner", "Data"),
    "google_spanner_database": ("mxgraph.gcp2/Cloud Spanner", "Data"),
    "google_sql_database_instance": ("mxgraph.gcp2/Cloud SQL", "Data"),
    "google_sql_database": ("mxgraph.gcp2/Cloud SQL", "Data"),
    "google_firestore_database": ("mxgraph.gcp2/cloud firestore", "Data"),
    "google_datastore_index": ("mxgraph.gcp2/Cloud Datastore", "Data"),
    "google_redis_instance": ("mxgraph.gcp2/Cloud Memorystore", "Data"),
    "google_pubsub_topic": ("mxgraph.gcp2/Cloud PubSub", "Messaging"),
    "google_pubsub_subscription": ("mxgraph.gcp2/Cloud PubSub", "Messaging"),
    "google_cloud_tasks_queue": ("mxgraph.gcp2/Cloud Tasks", "Messaging"),
    "google_cloud_scheduler_job": ("mxgraph.gcp2/Cloud Scheduler", "Management"),
    "google_dataflow_job": ("mxgraph.gcp2/Cloud Dataflow", "Analytics"),
    "google_dataproc_cluster": ("mxgraph.gcp2/Cloud Dataproc", "Analytics"),
    "google_composer_environment": ("mxgraph.gcp2/Cloud Composer", "Analytics"),
    "google_artifact_registry_repository": ("mxgraph.gcp2/Container Registry", "Build & Registry"),
    "google_cloudbuild_trigger": ("mxgraph.gcp2/Container Builder", "Build & Registry"),
    "google_service_account": ("mxgraph.gcp2/Cloud IAM", "Security & IAM"),
    "google_kms_key_ring": ("mxgraph.gcp2/Key Management Service", "Security & IAM"),
    "google_kms_crypto_key": ("mxgraph.gcp2/Key Management Service", "Security & IAM"),
    "google_project_service_identity": ("mxgraph.gcp2/Identity Aware Proxy", "Security & IAM"),
    "google_compute_network": ("mxgraph.gcp2/Virtual Private Cloud", "Networking"),
    "google_compute_subnetwork": ("mxgraph.gcp2/Virtual Private Cloud", "Networking"),
    "google_compute_firewall": ("mxgraph.gcp2/Cloud Firewall Rules", "Networking"),
    "google_compute_router": ("mxgraph.gcp2/Cloud Router", "Networking"),
    "google_compute_router_nat": ("mxgraph.gcp2/Cloud NAT", "Networking"),
    "google_compute_forwarding_rule": ("mxgraph.gcp2/Cloud Load Balancing", "Networking"),
    "google_compute_global_forwarding_rule": ("mxgraph.gcp2/Cloud Load Balancing", "Networking"),
    "google_compute_url_map": ("mxgraph.gcp2/Cloud Load Balancing", "Networking"),
    "google_dns_managed_zone": ("mxgraph.gcp2/Cloud DNS", "Networking"),
    "google_compute_vpn_gateway": ("mxgraph.gcp2/Cloud VPN", "Networking"),
    "google_compute_address": ("mxgraph.gcp2/Cloud External IP Addresses", "Networking"),
    "google_compute_global_address": ("mxgraph.gcp2/Cloud External IP Addresses", "Networking"),
    "google_endpoints_service": ("mxgraph.gcp2/Cloud Endpoints", "Networking"),
    "google_logging_project_sink": ("mxgraph.gcp2/Logging", "Management"),
    "google_monitoring_alert_policy": ("mxgraph.gcp2/cloud monitoring", "Management"),
    # --- AWS ---
    "aws_instance": ("mxgraph.aws4/ec2", "Compute"),
    "aws_launch_template": ("mxgraph.aws4/ec2", "Compute"),
    "aws_autoscaling_group": ("mxgraph.aws4/auto scaling", "Compute"),
    "aws_lambda_function": ("mxgraph.aws4/lambda", "Compute"),
    "aws_batch_job_definition": ("mxgraph.aws4/batch", "Compute"),
    "aws_apprunner_service": ("mxgraph.aws4/app runner", "Compute"),
    "aws_ecs_service": ("mxgraph.aws4/ecs", "Containers"),
    "aws_ecs_cluster": ("mxgraph.aws4/ecs", "Containers"),
    "aws_ecs_task_definition": ("mxgraph.aws4/fargate", "Containers"),
    "aws_eks_cluster": ("mxgraph.aws4/eks", "Containers"),
    "aws_eks_node_group": ("mxgraph.aws4/eks", "Containers"),
    "aws_ecr_repository": ("mxgraph.aws4/ecr", "Build & Registry"),
    "aws_s3_bucket": ("mxgraph.aws4/s3", "Storage"),
    "aws_efs_file_system": ("mxgraph.aws4/elastic file system", "Storage"),
    "aws_fsx_lustre_file_system": ("mxgraph.aws4/fsx", "Storage"),
    "aws_ebs_volume": ("mxgraph.aws4/elastic block store", "Storage"),
    "aws_dynamodb_table": ("mxgraph.aws4/dynamodb", "Data"),
    "aws_db_instance": ("mxgraph.aws4/rds", "Data"),
    "aws_rds_cluster": ("mxgraph.aws4/aurora", "Data"),
    "aws_elasticache_cluster": ("mxgraph.aws4/elasticache", "Data"),
    "aws_elasticache_replication_group": ("mxgraph.aws4/elasticache", "Data"),
    "aws_redshift_cluster": ("mxgraph.aws4/redshift", "Analytics"),
    "aws_neptune_cluster": ("mxgraph.aws4/neptune", "Data"),
    "aws_docdb_cluster": ("mxgraph.aws4/documentdb with mongodb compatibility", "Data"),
    "aws_kinesis_stream": ("mxgraph.aws4/kinesis", "Analytics"),
    "aws_kinesis_firehose_delivery_stream": ("mxgraph.aws4/kinesis data firehose", "Analytics"),
    "aws_glue_job": ("mxgraph.aws4/glue", "Analytics"),
    "aws_athena_database": ("mxgraph.aws4/athena", "Analytics"),
    "aws_emr_cluster": ("mxgraph.aws4/emr", "Analytics"),
    "aws_sqs_queue": ("mxgraph.aws4/sqs", "Messaging"),
    "aws_sns_topic": ("mxgraph.aws4/sns", "Messaging"),
    "aws_cloudwatch_event_rule": ("mxgraph.aws4/eventbridge", "Messaging"),
    "aws_mq_broker": ("mxgraph.aws4/mq", "Messaging"),
    "aws_msk_cluster": ("mxgraph.aws4/managed streaming for kafka", "Messaging"),
    "aws_sfn_state_machine": ("mxgraph.aws4/step functions", "Integration"),
    "aws_vpc": ("mxgraph.aws4/vpc", "Networking"),
    "aws_subnet": ("mxgraph.aws4/vpc", "Networking"),
    "aws_security_group": ("mxgraph.aws4/vpc", "Networking"),
    "aws_lb": ("mxgraph.aws4/elastic load balancing", "Networking"),
    "aws_alb": ("mxgraph.aws4/application load balancer", "Networking"),
    "aws_route53_zone": ("mxgraph.aws4/route 53", "Networking"),
    "aws_cloudfront_distribution": ("mxgraph.aws4/cloudfront", "Networking"),
    "aws_api_gateway_rest_api": ("mxgraph.aws4/api gateway", "Networking"),
    "aws_apigatewayv2_api": ("mxgraph.aws4/api gateway", "Networking"),
    "aws_iam_role": ("mxgraph.aws4/identity and access management", "Security & IAM"),
    "aws_iam_user": ("mxgraph.aws4/identity and access management", "Security & IAM"),
    "aws_kms_key": ("mxgraph.aws4/key management service", "Security & IAM"),
    "aws_secretsmanager_secret": ("mxgraph.aws4/secrets manager", "Security & IAM"),
    "aws_acm_certificate": ("mxgraph.aws4/certificate manager", "Security & IAM"),
    "aws_cognito_user_pool": ("mxgraph.aws4/cognito", "Security & IAM"),
    "aws_wafv2_web_acl": ("mxgraph.aws4/waf", "Security & IAM"),
    "aws_sagemaker_endpoint": ("mxgraph.aws4/sagemaker", "ML & AI"),
    "aws_cloudformation_stack": ("mxgraph.aws4/cloudformation", "Management"),
    "aws_ssm_parameter": ("mxgraph.aws4/systems manager", "Management"),
    "aws_cloudwatch_log_group": ("mxgraph.aws4/cloudwatch", "Management"),
    "aws_cloudwatch_metric_alarm": ("mxgraph.aws4/cloudwatch", "Management"),
    # --- Azure ---
    "azurerm_linux_virtual_machine": ("mxgraph.mscae.cloud/Virtual Machine Container", "Compute"),
    "azurerm_windows_virtual_machine": ("mxgraph.mscae.cloud/Virtual Machine Container", "Compute"),
    "azurerm_virtual_machine": ("mxgraph.mscae.cloud/Virtual Machine Container", "Compute"),
    "azurerm_virtual_machine_scale_set": ("mxgraph.mscae.cloud/VM Scale Set", "Compute"),
    "azurerm_linux_function_app": ("mxgraph.mscae.cloud/Functions", "Compute"),
    "azurerm_function_app": ("mxgraph.mscae.cloud/Functions", "Compute"),
    "azurerm_linux_web_app": ("mxgraph.mscae.cloud/App Service", "Compute"),
    "azurerm_windows_web_app": ("mxgraph.mscae.cloud/App Service", "Compute"),
    "azurerm_app_service": ("mxgraph.mscae.cloud/App Service", "Compute"),
    "azurerm_service_plan": ("mxgraph.mscae.cloud/App Service", "Compute"),
    "azurerm_kubernetes_cluster": ("mxgraph.mscae.cloud/Container Service", "Containers"),
    "azurerm_container_group": ("mxgraph.mscae.cloud/Container Service", "Containers"),
    "azurerm_container_registry": ("mxgraph.mscae.cloud/Container Registry", "Build & Registry"),
    "azurerm_storage_account": ("mxgraph.mscae.cloud/Azure Storage", "Storage"),
    "azurerm_managed_disk": ("mxgraph.mscae.cloud/Managed Discs", "Storage"),
    "azurerm_cosmosdb_account": ("mxgraph.mscae.cloud/Cosmos DB", "Data"),
    "azurerm_mssql_server": ("mxgraph.mscae.cloud/SQL Database Premium", "Data"),
    "azurerm_mssql_database": ("mxgraph.azure/SQL Database", "Data"),
    "azurerm_sql_database": ("mxgraph.azure/SQL Database", "Data"),
    "azurerm_mysql_flexible_server": ("mxgraph.azure/MySQL Database", "Data"),
    "azurerm_redis_cache": ("mxgraph.azure/Azure Cache", "Data"),
    "azurerm_data_factory": ("mxgraph.mscae.cloud/Data Factory", "Analytics"),
    "azurerm_data_lake_store": ("mxgraph.mscae.cloud/Data Lake Store", "Analytics"),
    "azurerm_synapse_workspace": ("mxgraph.mscae.cloud/SQL DataWarehouse", "Analytics"),
    "azurerm_stream_analytics_job": ("mxgraph.mscae.cloud/Stream Analytics", "Analytics"),
    "azurerm_eventhub": ("mxgraph.mscae.cloud/Event Hubs", "Messaging"),
    "azurerm_eventhub_namespace": ("mxgraph.mscae.cloud/Event Hubs", "Messaging"),
    "azurerm_eventgrid_topic": ("mxgraph.mscae.cloud/Event Grid", "Messaging"),
    "azurerm_servicebus_namespace": ("mxgraph.mscae.cloud/Service Bus", "Messaging"),
    "azurerm_servicebus_queue": ("mxgraph.mscae.cloud/Service Bus Queues", "Messaging"),
    "azurerm_servicebus_topic": ("mxgraph.mscae.cloud/Service Bus Topics", "Messaging"),
    "azurerm_logic_app_workflow": ("mxgraph.mscae.cloud/Logic App", "Integration"),
    "azurerm_api_management": ("mxgraph.mscae.cloud/API Management", "Integration"),
    "azurerm_key_vault": ("mxgraph.mscae.cloud/Key Vault", "Security & IAM"),
    "azurerm_virtual_network": ("mxgraph.azure/Virtual Network", "Networking"),
    "azurerm_subnet": ("mxgraph.azure/Virtual Network", "Networking"),
    "azurerm_network_security_group": ("mxgraph.mscae.cloud/NSG", "Networking"),
    "azurerm_lb": ("mxgraph.azure/Azure Load Balancer", "Networking"),
    "azurerm_application_gateway": ("mxgraph.mscae.cloud/Application Gateway", "Networking"),
    "azurerm_dns_zone": ("mxgraph.mscae.cloud/Azure DNS", "Networking"),
    "azurerm_virtual_network_gateway": ("mxgraph.mscae.cloud/VPN Gateway", "Networking"),
    "azurerm_express_route_circuit": ("mxgraph.mscae.cloud/ExpressRoute", "Networking"),
    "azurerm_cdn_profile": ("mxgraph.mscae.cloud/Content Delivery Network", "Networking"),
    "azurerm_cognitive_account": ("mxgraph.mscae.cloud/Cognitive Services", "ML & AI"),
    "azurerm_machine_learning_workspace": ("mxgraph.mscae.cloud/Machine Learning", "ML & AI"),
    "azurerm_resource_group": ("mxgraph.mscae.cloud/Resource Group", "Management"),
    "azurerm_application_insights": ("mxgraph.mscae.cloud/Application Insights", "Management"),
    "azurerm_monitor_metric_alert": ("mxgraph.mscae.cloud/Monitor", "Management"),
    # --- Kubernetes ---
    "kubernetes_deployment": ("mxgraph.kubernetes2/deploy", "Compute"),
    "kubernetes_deployment_v1": ("mxgraph.kubernetes2/deploy", "Compute"),
    "kubernetes_pod": ("mxgraph.kubernetes2/pod", "Compute"),
    "kubernetes_stateful_set": ("mxgraph.kubernetes2/sts", "Compute"),
    "kubernetes_daemon_set": ("mxgraph.kubernetes2/ds", "Compute"),
    "kubernetes_job": ("mxgraph.kubernetes2/job", "Compute"),
    "kubernetes_cron_job": ("mxgraph.kubernetes2/cronjob", "Compute"),
    "kubernetes_replication_controller": ("mxgraph.kubernetes2/rs", "Compute"),
    "kubernetes_horizontal_pod_autoscaler": ("mxgraph.kubernetes2/hpa", "Compute"),
    "kubernetes_service": ("mxgraph.kubernetes2/svc", "Networking"),
    "kubernetes_ingress": ("mxgraph.kubernetes2/ing", "Networking"),
    "kubernetes_ingress_v1": ("mxgraph.kubernetes2/ing", "Networking"),
    "kubernetes_network_policy": ("mxgraph.kubernetes2/netpol", "Networking"),
    "kubernetes_config_map": ("mxgraph.kubernetes2/cm", "Storage"),
    "kubernetes_persistent_volume": ("mxgraph.kubernetes2/pv", "Storage"),
    "kubernetes_persistent_volume_claim": ("mxgraph.kubernetes2/pvc", "Storage"),
    "kubernetes_storage_class": ("mxgraph.kubernetes2/sc", "Storage"),
    "kubernetes_secret": ("mxgraph.kubernetes2/secret", "Security & IAM"),
    "kubernetes_service_account": ("mxgraph.kubernetes2/sa", "Security & IAM"),
    "kubernetes_role": ("mxgraph.kubernetes2/role", "Security & IAM"),
    "kubernetes_role_binding": ("mxgraph.kubernetes2/rb", "Security & IAM"),
    "kubernetes_cluster_role": ("mxgraph.kubernetes2/c role", "Security & IAM"),
    "kubernetes_cluster_role_binding": ("mxgraph.kubernetes2/crb", "Security & IAM"),
    "kubernetes_namespace": ("mxgraph.kubernetes2/ns", "Management"),
}

# Project-API toggles, settings blobs, and other pure noise on an architecture
# diagram. Provider-specific; extend per provider as needed.
SKIP_TYPES: set[str] = {
    "google_project_service",
    "google_iap_settings",
}

# Identity resources — the "member" end of an IAM grant edge (identity -> resource).
# An IAM grant references an identity and a target; this set says which resolved
# refs are the identity. Provider-extensible.
IDENTITY_TYPES: set[str] = {
    "google_service_account",
    "google_project_service_identity",
    "aws_iam_role",
    "aws_iam_user",
    "azurerm_user_assigned_identity",
    "kubernetes_service_account",
}

# Category -> accent colour for the icon tint + node border. Generic labels, so
# the same palette serves any provider.
CATEGORY_COLOR: dict[str, str] = {
    "Compute": "#4285F4",
    "Containers": "#7B61FF",
    "Storage": "#F9AB00",
    "Data": "#34A853",
    "Analytics": "#00ACC1",
    "Messaging": "#E8710A",
    "Integration": "#C2185B",
    "Networking": "#455A9C",
    "Security & IAM": "#EA4335",
    "Build & Registry": "#A142F4",
    "ML & AI": "#00897B",
    "Management": "#5F6368",
    "Other": "#9AA0A6",
}

# IAM grants render as dashed, role-labelled EDGES (not boxes) by default. The
# heuristic is cloud-neutral: the three Terraform IAM-binding shapes across
# providers end in _iam_member / _iam_binding / _iam_policy.
_IAM_GRANT_RE = re.compile(r"_iam_(member|binding|policy)(_member)?$")


def is_iam_grant(tf_type: str) -> bool:
    return bool(_IAM_GRANT_RE.search(tf_type))


def is_skipped(tf_type: str) -> bool:
    return tf_type in SKIP_TYPES


def is_identity(tf_type: str) -> bool:
    return tf_type in IDENTITY_TYPES


def stencil_for(tf_type: str) -> tuple[str | None, str]:
    """(stencil_id, category) for a type; (None, "Other") when unmapped."""
    return RESOURCE_STENCILS.get(tf_type, (None, "Other"))


def category_for(tf_type: str) -> str:
    return stencil_for(tf_type)[1]


def color_for(tf_type: str) -> str:
    return CATEGORY_COLOR.get(category_for(tf_type), CATEGORY_COLOR["Other"])
