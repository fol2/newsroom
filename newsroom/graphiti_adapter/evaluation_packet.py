"""EVALUATION packet for the private unpublished GraphRAG beta.

Graphiti chat uses cursor-agent CLI `composer-2.5`, then Grok Build CLI
`grok-4.6` medium. Embeddings remain OpenRouter `text-embedding-3-large`.
CLI chat is subscription: ledgered, not OD-011 debit. PRODUCTION stays closed.
Increment 9P proving still must not call OpenRouter (`OPENROUTER_UNUSED`).
"""

from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.canonical import digest_canonical
from newsroom.graphiti_adapter.contracts import (
    GRAPHITI_ADAPTER_CODE_COMPONENT,
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
from newsroom.graphiti_adapter.temporal_vocabulary import TEMPORAL_POLICY_VERSION
from newsroom.increment9.proving import PORTFOLIO

GRAPHITI_CORE_RELEASE = "graphiti-core-0.29.3"
GRAPHITI_CHAT_MODEL = "cursor-agent-cli:composer-2.5"
GRAPHITI_CHAT_FALLBACK = "grok-build-cli:grok-4.6-medium"
CURSOR_AGENT_MODEL_ID = "composer-2.5"
GROK_CHAT_MODEL_ID = "grok-4.6"
GROK_CHAT_REASONING = "medium"
GRAPHITI_EMBEDDING_MODEL = "openrouter:openai.text-embedding-3-large"


@dataclass(frozen=True, slots=True)
class GraphitiEvaluationProviderDestination:
    """One EVALUATION Graphiti route and its retained rights destination token."""

    route: str
    destination_token: str


GRAPHITI_EVALUATION_PROVIDER_DESTINATIONS = (
    GraphitiEvaluationProviderDestination(
        route=GRAPHITI_CHAT_MODEL,
        destination_token="EVALUATION_CURSOR_AGENT_CLI",
    ),
    GraphitiEvaluationProviderDestination(
        route=GRAPHITI_CHAT_FALLBACK,
        destination_token="EVALUATION_GROK_BUILD_CLI",
    ),
    GraphitiEvaluationProviderDestination(
        route=GRAPHITI_EMBEDDING_MODEL,
        destination_token="EVALUATION_OPENROUTER_EMBEDDINGS",
    ),
)
GRAPHITI_EVALUATION_DESTINATION_TOKENS = frozenset(
    item.destination_token for item in GRAPHITI_EVALUATION_PROVIDER_DESTINATIONS
)
WRITER_MODEL = "grok-build-cli:grok-4.6"
WRITER_FALLBACK = "cursor-agent-cli"
OPENROUTER_EMBEDDING_SLUG = "openai/text-embedding-3-large"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_API = "OPENROUTER_API"
OPENROUTER_KEYCHAIN_SERVICE = "newsroom.shadow.v1"
NEO4J_COMMUNITY_LOCAL = "NEO4J_COMMUNITY_LOCAL"
OD_011_CASH_CEILING_GBP = 250
GRAPHITI_EXTRACTION_INSTRUCTIONS = (
    "Extract people, organisations, places, events, policies and their relations "
    "from the source content. Do not treat newsroom source-registry identifiers "
    "(for example HK-04, RAD-02, UK-01) as world entities or relations. "
    "Do not extract SourceItem, SourceRevision, DERIVED_FROM or OBSERVED_IN lineage."
)
GRAPHITI_INPUT_WATERMARK = digest_canonical({"portfolio": list(PORTFOLIO)})

GRAPHITI_GENERATION_DIGEST = digest_canonical(
    {
        "framework": GRAPHITI_CORE_RELEASE,
        "chat": GRAPHITI_CHAT_MODEL,
        "fallback": GRAPHITI_CHAT_FALLBACK,
        "embedding": GRAPHITI_EMBEDDING_MODEL,
        "temporal": TEMPORAL_POLICY_VERSION,
        "prompt": GRAPHITI_PROMPT_COMPONENT.contract_digest,
        "ontology": GRAPHITI_ADAPTER_OUTPUT_SCHEMA_COMPONENT.canonical_value(),
        "adapter_code": GRAPHITI_ADAPTER_CODE_COMPONENT.canonical_value(),
        "extraction_instructions": GRAPHITI_EXTRACTION_INSTRUCTIONS,
        "input_watermark": GRAPHITI_INPUT_WATERMARK,
    }
)
GRAPHITI_GENERATION_ID = GRAPHITI_GENERATION_DIGEST.removeprefix("sha256:")[:12]
GRAPHITI_WORKSPACE_GROUP = f"newsroom-eval-proposal-{GRAPHITI_GENERATION_ID}"

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
            "issues": [693, 698, 699, 700, 707, 722],
            "chat": GRAPHITI_CHAT_MODEL,
            "chat_fallback": GRAPHITI_CHAT_FALLBACK,
            "embedding_provider": OPENROUTER_API,
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
            "generation_id": GRAPHITI_GENERATION_ID,
        }
    ),
    data_processing_terms_digest=_digest(
        {
            "metered_api": OPENROUTER_API,
            "keychain_service": OPENROUTER_KEYCHAIN_SERVICE,
            "chat": GRAPHITI_CHAT_MODEL,
            "chat_fallback": GRAPHITI_CHAT_FALLBACK,
            "writer": WRITER_MODEL,
            "writer_fallback": WRITER_FALLBACK,
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
                "openrouter.ai",
                "127.0.0.1",
                "localhost",
            ),
            "credential_classes": (
                OPENROUTER_API,
                NEO4J_COMMUNITY_LOCAL,
            ),
            "chat_cli": (GRAPHITI_CHAT_MODEL, GRAPHITI_CHAT_FALLBACK),
        }
    ),
    budget_digest=_digest(
        {
            "od_011_cash_ceiling_gbp": OD_011_CASH_CEILING_GBP,
            "pre_spend": False,
            "embedding_provider": OPENROUTER_API,
            "chat_subscription_not_debited": True,
            "writer_subscription_not_debited": True,
        }
    ),
    evaluation_plan_digest=_digest(
        {
            "profile": "EVALUATION",
            "production_forbidden": True,
            "proving_openrouter_unused": True,
        }
    ),
    rollback_digest=_digest(
        {
            "wipe_graphiti_group": GRAPHITI_WORKSPACE_GROUP,
            "generation_id": GRAPHITI_GENERATION_ID,
            "ledger_retained": True,
        }
    ),
)
