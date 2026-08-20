"""EVALUATION packet for the private unpublished GraphRAG beta.

Does not flip REAL_GRAPHITI_RUNTIME_ENABLED. Completeness of this packet is
not execution authority (#700).
"""

from __future__ import annotations

from newsroom.authority.canonical import digest_canonical
from newsroom.graphiti_adapter.contracts import (
    GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT,
    GRAPHITI_PROMPT_COMPONENT,
)
from newsroom.graphiti_adapter.models import (
    GraphitiWorkspacePolicy,
    RealGraphitiRuntimeAuthority,
)
from newsroom.graphiti_adapter.types import (
    GraphitiCredentialClass,
    GraphitiEgressPolicy,
    GraphitiWorkspacePolicyId,
)

GRAPHITI_CORE_RELEASE = "graphiti-core-0.29.3"
GRAPHITI_CHAT_MODEL = "openai:gpt-5-mini"
GRAPHITI_EMBEDDING_MODEL = "openai:text-embedding-3-large"
GRAPHITI_WORKSPACE_GROUP = "newsroom-eval-proposal"
OPENAI_GRAPHITI_CHAT_API = "OPENAI_GRAPHITI_CHAT_API"
NEO4J_COMMUNITY_LOCAL = "NEO4J_COMMUNITY_LOCAL"
OD_011_CASH_CEILING_GBP = 250

EVALUATION_WORKSPACE_POLICY = GraphitiWorkspacePolicy(
    policy_id=GraphitiWorkspacePolicyId.parse(
        "00000000-0000-4000-8000-000000004803"
    ),
    policy_version="graphiti-disposable-workspace-v1",
    namespace_prefix=GRAPHITI_WORKSPACE_GROUP,
    max_workspace_bytes=32 * 1024 * 1024,
    max_private_nodes=20_000,
    max_private_relations=40_000,
    egress_policy=GraphitiEgressPolicy.APPROVED_PROVIDER_ONLY,
    credential_class=GraphitiCredentialClass.PROPOSAL_WORKSPACE_ONLY,
)


def _digest(contract: object) -> str:
    return digest_canonical(contract)


EVALUATION_GRAPHITI_PACKET = RealGraphitiRuntimeAuthority(
    authority_decision_digest=_digest(
        {
            "map": "private-unpublished-graphrag-editorial-beta",
            "profile": "EVALUATION",
            "issues": [693, 698, 699, 700, 707],
        }
    ),
    framework_release=GRAPHITI_CORE_RELEASE,
    model_release=GRAPHITI_CHAT_MODEL,
    embedding_release=GRAPHITI_EMBEDDING_MODEL,
    destination_contract_digest=_digest(
        {
            "engine": "neo4j-community-plus-graphiti",
            "neo4j_server": "2026.06.0",
            "driver": "neo4j==6.2.0",
            "graphiti_writes_ledger": False,
            "graphiti_writes_admitted_graph": False,
            "workspace_group": GRAPHITI_WORKSPACE_GROUP,
        }
    ),
    data_processing_terms_digest=_digest(
        {
            "openai_chat": OPENAI_GRAPHITI_CHAT_API,
            "openai_embeddings": "OPENAI_EMBEDDINGS_API",
            "writer": "XAI_GROK_BUILD_LOGIN",
            "neo4j": NEO4J_COMMUNITY_LOCAL,
        }
    ),
    prompt_contract_digest=GRAPHITI_PROMPT_COMPONENT.contract_digest,
    output_schema_contract_digest=GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT.contract_digest,
    permitted_expression_digest=_digest(
        {
            "source_is_untrusted_data": True,
            "proposal_only": True,
            "unpublished_surface_payload": True,
            "publication_bundle": False,
        }
    ),
    rights_privacy_retention_digest=_digest(
        {
            "od_012": True,
            "rights_014": True,
            "rights_017": True,
        }
    ),
    workspace_security_digest=EVALUATION_WORKSPACE_POLICY.canonical_digest,
    egress_credential_digest=_digest(
        {
            "default_deny": True,
            "hosts": (
                "api.openai.com",
                "127.0.0.1",
                "localhost",
            ),
            "credential_classes": (
                OPENAI_GRAPHITI_CHAT_API,
                "OPENAI_EMBEDDINGS_API",
                "XAI_GROK_BUILD_LOGIN",
                NEO4J_COMMUNITY_LOCAL,
            ),
        }
    ),
    budget_digest=_digest(
        {
            "od_011_cash_ceiling_gbp": OD_011_CASH_CEILING_GBP,
            "pre_spend": False,
            "grok_subscription_not_debited": True,
        }
    ),
    evaluation_plan_digest=_digest(
        {
            "profile": "EVALUATION",
            "production_forbidden": True,
        }
    ),
    rollback_digest=_digest(
        {
            "wipe_graphiti_group": GRAPHITI_WORKSPACE_GROUP,
            "ledger_retained": True,
        }
    ),
)
