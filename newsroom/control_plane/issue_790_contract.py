"""Reviewed immutable identities for issue #790's owner-approved operation."""

from __future__ import annotations

from dataclasses import dataclass

ISSUE_790_APPROVED_PLAN_DIGEST = (
    "sha256:ce7ee7fd56c931b147158dad2a74047ada90b805e5a4c545e53db1f4d2ae7383"
)
ISSUE_790_APPROVED_INVOCATION_ID = (
    "sha256:75f14fd50f54c01c852c557291eb7bb92b05a79c937d10d048bb245863b7a196"
)
ISSUE_790_APPROVED_TERMINAL_DIGEST = (
    "sha256:0c73f6a7ad2255f13bfdb617370f0c935464917e0e80c69b2da216ffca60ee0c"
)
ISSUE_790_APPROVED_ALLOCATION_DIGEST = (
    "sha256:800dd0c6155a34cfafe91c1c240dac2d44730f558be9417d5fe34b5fb23780b2"
)
ISSUE_790_APPROVED_SCOPE = (
    "CONSERVATIVE_SUBSCRIPTION_CLI_USAGE_DISPOSITION"
)
ISSUE_790_APPROVED_BY = "github:fol2"
ISSUE_790_APPROVAL_REFERENCE = (
    "https://github.com/fol2/newsroom/issues/790#issuecomment-5426599150"
)
ISSUE_790_APPROVED_AT = "2026-08-26T14:12:57.000000Z"
ISSUE_790_APPROVED_TERMINAL_OUTCOME = "FAILED"
ISSUE_790_APPROVED_ROUTE_OPEN_REASON = "SYSTEMIC_TRANSPORT"

ISSUE_790_SUCCESS_SEQUENCE_PLAN_DIGEST = (
    "sha256:3347669cc57fcc3740f9e7027cf7c9c6936626dfb1932eeec5ea2018fe6f6308"
)
ISSUE_790_SUCCESS_SEQUENCE_STEP_2_PLAN_DIGEST = (
    "sha256:f759403c9838ef431cff38126989d8732ed5ba7e03ce92f554760ba0ef2d2c61"
)
ISSUE_790_SUCCESS_SEQUENCE_STEP_3_PLAN_DIGEST = (
    "sha256:598bc32d1e9c662d19188df6b0d038ac4205641d59810356504ee3da805250d4"
)
ISSUE_790_SUCCESS_SEQUENCE_STEP_4_PLAN_DIGEST = (
    "sha256:12e2aa639b1d378b48d1a8ae10113720f887e679432b1f8866aaff3576df98fd"
)
ISSUE_790_SUCCESS_SEQUENCE_STEP_5_PLAN_DIGEST = (
    "sha256:cca39c56b4c8368fc87b262b501f55b2e754f923eda83f38330c099f1888dacb"
)
ISSUE_790_SUCCESS_SEQUENCE_STEP_6_PLAN_DIGEST = (
    "sha256:be8ccb6cec126cdaffe9801421cfc115d4651b5a305435a7e820290e17099239"
)
ISSUE_790_SUCCESS_SEQUENCE_STEP_8_PLAN_DIGEST = (
    "sha256:e45fb670577de1b929a4c7cde114e6cc05c589ff7e010abbab9656445a2edb8c"
)
ISSUE_790_SUCCESS_SEQUENCE_STEP_9_PLAN_DIGEST = (
    "sha256:ed9ddb506df0cc6572777bd9a91249b474032eb4dea6458d2c3e9b0466cbce77"
)
ISSUE_790_SUCCESS_SEQUENCE_STEP_10_PLAN_DIGEST = (
    "sha256:a4f9549afec46d57edeedd1fc478b6732b55a80e80f7d0690f08e58c9396c2af"
)
ISSUE_790_SUCCESS_SEQUENCE_STEP_11_PLAN_DIGEST = (
    "sha256:66e503ce0dbb3935bf000f2af2ecc9c0435fcb1daa9b142137913a7990fc3406"
)
ISSUE_790_SUCCESS_SEQUENCE_STEP_12_PLAN_DIGEST = (
    "sha256:2e95f49445ec600ccd8ec152348ffc40a338c86f6d597f62b894dd213ed201c4"
)
ISSUE_790_SUCCESS_SEQUENCE_STEP_13_PLAN_DIGEST = (
    "sha256:44b7f2ab1a36232b458d0d604c010f155f65e57cb6aed25d00d5577bb4d83bc8"
)
ISSUE_790_SUCCESS_SEQUENCE_STEP_14_PLAN_DIGEST = (
    "sha256:3878757b1a20c1a45439d849020dc7e9df1c19f81895db671d796c4dcecf73ac"
)
ISSUE_790_SUCCESS_SEQUENCE_STEP_15_PLAN_DIGEST = (
    "sha256:58220d3a2b389ca25bf86f71b4d7974c6186ee26ab705af351091a20228e1db8"
)
ISSUE_790_STEP16_CANDIDATE_SCHEMA = (
    "newsroom.issue-790.checked-candidate-plan.v1"
)
ISSUE_790_STEP16_CHECKED_CANDIDATE_DIGEST = (
    "sha256:601d0cfe63775d5205de6c672b344ab8b0055521fe6f191eb526e25c72a48d9e"
)
ISSUE_790_STEP16_PENDING_DIGEST = (
    "sha256:8651368768f8ead04d2d96c0d0bbcf387b3baefedaaa5b5a07fb2e4d169fe271"
)
ISSUE_790_STEP16_OWNER_APPROVAL_SCHEMA = (
    "newsroom.issue-790.step16-owner-approval.v1"
)
ISSUE_790_STEP16_ACTIVATION_SCHEMA = (
    "newsroom.issue-790.step16-activation-receipt.v1"
)
ISSUE_790_STEP16_ACTIVATION_POLICY_VERSION = (
    "issue-790-step16-owner-activation.v1"
)
ISSUE_790_STEP16_APPROVAL_MARKER = "NEWSROOM_ISSUE_790_STEP16_OWNER_APPROVAL_V1"
ISSUE_790_STEP16_REVOKED_CHECKED_LIVE_PLAN_DIGEST = (
    "sha256:72723b72b71f12fee2a9ec31c2b4145e5cbac4ac55f8ddbc51319248e94c21f9"
)
ISSUE_790_STEP16_ACTIVATED_PLAN_DIGEST = (
    "sha256:68142ca2d7dc343bfba579271f619c8d00c1e7f32ebda584f70eb8871f756b5e"
)
ISSUE_790_STEP16_ACTIVATION_DIGEST = (
    "sha256:c2518592533bf09886e7457d05e41be41eb0605f47941230d750931e192b68c3"
)
ISSUE_790_STEP17_PENDING_DIGEST = (
    "sha256:1a25b92b9959db9862726b4f40489996796ef20ddf8d09c5d811b9aa8f875a43"
)
ISSUE_790_STEP17_CHECKED_CANDIDATE_DIGEST = (
    "sha256:c88fdc3b1316a0e4a8c9ff09db0f923927664bb24536ec076a799f7f3054b3d2"
)
ISSUE_790_STEP17_ACTIVATED_PLAN_DIGEST = (
    "sha256:bbdae8cb9aa5c8581180d453bc4388f1cd02796aa62375637c5bb3be1957ad2c"
)
ISSUE_790_STEP17_ACTIVATION_DIGEST = (
    "sha256:0cb24bce4a82b8520651f818c42516db37e1356bb950ade8b3ca1b4e21bb2acb"
)
ISSUE_790_STEP17_GATE_OUTCOME_DIGEST = (
    "sha256:83da516b8d3a8699e7eee234c684e1317ad78ea0d254bc2dd763970c6f95116d"
)
ISSUE_790_STEP18_PENDING_DIGEST = (
    "sha256:798e0f39e2c618f5d56aa68d4def18ccd2cadc273fc9da4474e8f832c5cbd3ec"
)
ISSUE_790_STEP18_CHECKED_CANDIDATE_DIGEST = (
    "sha256:48c0073d65c6a0063883743b7eea03f02edae19c22e2050e86da6691b13e2479"
)
ISSUE_790_STEP18_ACTIVATED_PLAN_DIGEST = (
    "sha256:6b48b375eaac0aa3922cd0e5e28e28a7a2d3e08434a6ef8e5519fe769827204d"
)
ISSUE_790_STEP18_ACTIVATION_DIGEST = (
    "sha256:d4132cafe723b6bc09f688aeda7497d7a35e7ec4e6a2b3ae50c1651f5eb5aafc"
)
ISSUE_790_STEP19_PENDING_DIGEST = (
    "sha256:db5bb96029e1f18afe5401c9f50f1051342483454f83e8a819a01f29aad903dc"
)
ISSUE_790_STEP19_CHECKED_CANDIDATE_DIGEST = (
    "sha256:da549328193abf9ff9490ca35bd620487df16afeb41636c4148f0c42cef24b8a"
)
ISSUE_790_STEP19_ACTIVATED_PLAN_DIGEST = (
    "sha256:174ed95376ef1e7fd43a156c8c21d7a898272a966052cca55fe6c0c31b85cc10"
)
ISSUE_790_STEP19_ACTIVATION_DIGEST = (
    "sha256:a3dd425449b8fac476294317829362ef67ac86b39684f0bc6224574d40013d9c"
)
ISSUE_790_STEP20_PENDING_DIGEST = (
    "sha256:a1a70f3f3e515fd93d9775f89f483cdb59d5258107b1357166d8148216ec8b34"
)
ISSUE_790_STEP20_CHECKED_CANDIDATE_DIGEST = (
    "sha256:3eda7bc788a7f98dc8be810a7aaf320fde51e1ffce240996512f75fc0d09d03c"
)
ISSUE_790_STEP20_ACTIVATED_PLAN_DIGEST = (
    "sha256:ee4a425de2d3f72dceba89ce563c035feae3935489ef06b82bf3a49fe914e7c7"
)
ISSUE_790_STEP20_ACTIVATION_DIGEST = (
    "sha256:a562cf7b241c5f20862b240884788244a1f646d49634a44b8cb4b0cb8e523b40"
)
ISSUE_790_STEP21_PENDING_DIGEST = (
    "sha256:cb5ff53443a5a3fda9c24af93386d4ec02ed682f639c09326c46a66287102ede"
)
ISSUE_790_STEP21_CHECKED_CANDIDATE_DIGEST = (
    "sha256:ffa787e74e16dbf5b606c3952f064e1a0d908dcc13bbf5ec8dcdc68e69ef7fd2"
)
ISSUE_790_STEP21_ACTIVATED_PLAN_DIGEST = (
    "sha256:effc7aed0657c5f164427b81f0e7c05580fcdec5baa4ec18aea588a69912dbb1"
)
ISSUE_790_STEP21_ACTIVATION_DIGEST = (
    "sha256:87b12eae84e1892174e1b720c0c7ba0ef5724798c7657efb72f097e26da9c003"
)
ISSUE_790_STEP22_PENDING_DIGEST = (
    "sha256:5245ee8fab237fac3a0b9bf8863ef7693ba55d78311bf4e8ffe4e949f1a87ce4"
)
ISSUE_790_STEP22_CHECKED_CANDIDATE_DIGEST = (
    "sha256:deae29a6ddb8d88300ba72c48c2140c6d15d5f3ff1f25343b9cc2608ae7287c8"
)
ISSUE_790_OWNER_ACTIVATED_SEQUENCE_ORDINALS = frozenset(
    {16, 17, 18, 19, 20, 21, 22}
)


@dataclass(frozen=True, slots=True)
class Issue790ApprovedPlanContract:
    """Exact identities which reviewed code may turn into one authority row."""

    schema_version: str
    plan_digest: str
    invocation_id: str
    terminal_digest: str
    allocation_digest: str
    approved_by: str
    approval_reference: str
    approved_at: str
    scope: str
    terminal_outcome: str
    route_open_reason: str
    root_plan_digest: str
    predecessor_plan_digest: str | None
    sequence_ordinal: int
    controller_timeout_ms: int
    extraction_timeout_ms: int
    cleanup_reserve_ms: int
    fixed_constraints_digest: str | None
    predecessor_causal_report_digest: str | None
    constraint_change: str | None
    reviewed_fix_digest: str | None
    projection_policy_version: str | None = None
    projection_policy_digest: str | None = None
    temporal_policy_version: str | None = None
    validator_contract_version: str | None = None
    pre_dispatch_operational_requirements_digest: str | None = None


@dataclass(frozen=True, slots=True)
class Issue790CheckedCandidateContract:
    """Seal-proof identities. Not live approved-plan authority."""

    schema_version: str
    candidate_digest: str
    pending_digest: str
    invocation_id: str
    terminal_digest: str
    allocation_digest: str
    predecessor_plan_digest: str
    sequence_ordinal: int
    projection_policy_version: str
    projection_policy_digest: str
    temporal_policy_version: str
    validator_contract_version: str
    pre_dispatch_operational_requirements_digest: str
    reviewed_fix_digest: str
    predecessor_causal_report_digest: str
    checked_approved_by: str
    checked_approval_reference: str
    candidate_event_qualification_digest: str | None = None
    candidate_event_id: str | None = None
    candidate_ledger_seq: int | None = None
    candidate_event_manifest_digest: str | None = None


_SUCCESS_SEQUENCE_CONTRACTS = (
    Issue790ApprovedPlanContract(
        schema_version="newsroom.issue-790.iterative-canary-plan.v2",
        plan_digest=ISSUE_790_SUCCESS_SEQUENCE_PLAN_DIGEST,
        invocation_id=(
            "sha256:8e219f498ee1eff71cd21c5d9dd3d958e5aed62db8f938b0a2bfdba6d4e9de7d"
        ),
        terminal_digest=(
            "sha256:f5e67d327b215c1eda3a320b07e2cee642151880c5fa275686e8d534646ca9b9"
        ),
        allocation_digest=(
            "sha256:468bc90fb8c9114ca8d4fc780d137f676ce69b453fcfda74bef88e0508a15643"
        ),
        approved_by="github:fol2",
        approval_reference=(
            "https://github.com/fol2/newsroom/issues/790#issuecomment-5430967545"
        ),
        approved_at="2026-08-26T20:51:55.000000Z",
        scope=ISSUE_790_APPROVED_SCOPE,
        terminal_outcome="TIMEOUT",
        route_open_reason="TIMEOUT",
        root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        predecessor_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        sequence_ordinal=1,
        controller_timeout_ms=160_000,
        extraction_timeout_ms=180_000,
        cleanup_reserve_ms=20_000,
        fixed_constraints_digest=(
            "sha256:a3d6a7759c57df52e0a25feae3edcc740ce7ec26064996aae018b276fd36fbb2"
        ),
        predecessor_causal_report_digest=(
            "sha256:cb1b72361e6f17d02e5f8ecce30d2ff53a79e9334ba942728f58fcf8d977f7f2"
        ),
        constraint_change="INITIAL_QUALIFIED_BASELINE",
        reviewed_fix_digest=None,
    ),
    Issue790ApprovedPlanContract(
        schema_version="newsroom.issue-790.iterative-canary-plan.v2",
        plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_2_PLAN_DIGEST,
        invocation_id=(
            "sha256:98a2abb90c523af7dd314746039810c07227baef136e70b74887604e052e0ddd"
        ),
        terminal_digest=(
            "sha256:78aaae4b8717ecb691a2b63564425ac8fe9fe84dc7742059104e47801b13e91e"
        ),
        allocation_digest=(
            "sha256:203659ac4f8399b5810657425a0f4fde77220e6daf3b07eed456e2cf9a3385bd"
        ),
        approved_by="github:fol2",
        approval_reference=(
            "https://github.com/fol2/newsroom/issues/790#issuecomment-5432307187"
        ),
        approved_at="2026-08-26T23:29:50.000000Z",
        scope=ISSUE_790_APPROVED_SCOPE,
        terminal_outcome="FAILED",
        route_open_reason="SYSTEMIC_TRANSPORT",
        root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        predecessor_plan_digest=ISSUE_790_SUCCESS_SEQUENCE_PLAN_DIGEST,
        sequence_ordinal=2,
        controller_timeout_ms=160_000,
        extraction_timeout_ms=180_000,
        cleanup_reserve_ms=20_000,
        fixed_constraints_digest=(
            "sha256:a3d6a7759c57df52e0a25feae3edcc740ce7ec26064996aae018b276fd36fbb2"
        ),
        predecessor_causal_report_digest=(
            "sha256:0f06ffa65fc95a8e3278fccc92eed8dc23cebf5517a722d74bce14c73e2984a8"
        ),
        constraint_change="REVIEWED_NON_TIMEOUT_FIX",
        reviewed_fix_digest=(
            "sha256:1bfba70f2f88eec47da9d8329030239c316cdc995b519c929fe074dcb9b14e32"
        ),
    ),
    Issue790ApprovedPlanContract(
        schema_version="newsroom.issue-790.iterative-canary-plan.v2",
        plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_3_PLAN_DIGEST,
        invocation_id=(
            "sha256:e6a0ffed3f985874890cecb49fe39ffac4cda35b0500d15974138afb733deb98"
        ),
        terminal_digest=(
            "sha256:dde1567eef7a2492af7dc4f27fd71349536e712ac6964134075e2ea5915c7580"
        ),
        allocation_digest=(
            "sha256:56250dc0660a2aceedc2fc5950771979acd5f47558f9817ad537d7b8684e270b"
        ),
        approved_by="github:fol2",
        approval_reference=(
            "https://github.com/fol2/newsroom/issues/790#issuecomment-5432472121"
        ),
        approved_at="2026-08-26T23:52:26.000000Z",
        scope=ISSUE_790_APPROVED_SCOPE,
        terminal_outcome="FAILED",
        route_open_reason="SYSTEMIC_TRANSPORT",
        root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        predecessor_plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_2_PLAN_DIGEST,
        sequence_ordinal=3,
        controller_timeout_ms=160_000,
        extraction_timeout_ms=180_000,
        cleanup_reserve_ms=20_000,
        fixed_constraints_digest=(
            "sha256:84400663bfddfef14935cdf9c6a0942d548adeab08a732b023e19876de2b2fc2"
        ),
        predecessor_causal_report_digest=(
            "sha256:44ef2cafb3de22a5cfb9adf285e5fad12c41e10a38218a9a613b983b384fe071"
        ),
        constraint_change="REVIEWED_NON_TIMEOUT_FIX",
        reviewed_fix_digest=(
            "sha256:de1912ed425dd21b3bdc632fd33fb6af7e3842cd7fba989ebe2a2ded2ddcd13c"
        ),
    ),
    Issue790ApprovedPlanContract(
        schema_version="newsroom.issue-790.iterative-canary-plan.v2",
        plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_4_PLAN_DIGEST,
        invocation_id=(
            "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
        ),
        terminal_digest=(
            "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
        ),
        allocation_digest=(
            "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
        ),
        approved_by="github:fol2",
        approval_reference=(
            "https://github.com/fol2/newsroom/issues/790#issuecomment-5432738868"
        ),
        approved_at="2026-08-27T00:29:06.000000Z",
        scope=ISSUE_790_APPROVED_SCOPE,
        terminal_outcome="FAILED",
        route_open_reason="SYSTEMIC_TRANSPORT",
        root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        predecessor_plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_3_PLAN_DIGEST,
        sequence_ordinal=4,
        controller_timeout_ms=160_000,
        extraction_timeout_ms=180_000,
        cleanup_reserve_ms=20_000,
        fixed_constraints_digest=(
            "sha256:84400663bfddfef14935cdf9c6a0942d548adeab08a732b023e19876de2b2fc2"
        ),
        predecessor_causal_report_digest=(
            "sha256:84cfe4b80853815c2969d2f0570f68cf13be07b4c1e51502fe19adb1dedad817"
        ),
        constraint_change="REVIEWED_NON_TIMEOUT_FIX",
        reviewed_fix_digest=(
            "sha256:f76ef9a132955ebcbd4dffcc33cec7be87e54c1976b48a5f54134c6bd50af490"
        ),
    ),
    Issue790ApprovedPlanContract(
        schema_version="newsroom.issue-790.iterative-canary-plan.v2",
        plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_5_PLAN_DIGEST,
        invocation_id=(
            "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
        ),
        terminal_digest=(
            "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
        ),
        allocation_digest=(
            "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
        ),
        approved_by="github:fol2",
        approval_reference=(
            "https://github.com/fol2/newsroom/issues/790#issuecomment-5432910225"
        ),
        approved_at="2026-08-27T00:53:36.000000Z",
        scope=ISSUE_790_APPROVED_SCOPE,
        terminal_outcome="FAILED",
        route_open_reason="SYSTEMIC_TRANSPORT",
        root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        predecessor_plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_4_PLAN_DIGEST,
        sequence_ordinal=5,
        controller_timeout_ms=160_000,
        extraction_timeout_ms=180_000,
        cleanup_reserve_ms=20_000,
        fixed_constraints_digest=(
            "sha256:84400663bfddfef14935cdf9c6a0942d548adeab08a732b023e19876de2b2fc2"
        ),
        predecessor_causal_report_digest=(
            "sha256:3923ce0cd2d6dfe82b1e580ab27bfef6e48d66d7167ee9e2c875281bc1e8ab67"
        ),
        constraint_change="REVIEWED_NON_TIMEOUT_FIX",
        reviewed_fix_digest=(
            "sha256:cce5f07d7b2138bcacca235116683cb7fd8edc31cefcfd54f686e423732d96b5"
        ),
    ),
    Issue790ApprovedPlanContract(
        schema_version="newsroom.issue-790.iterative-canary-plan.v2",
        plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_6_PLAN_DIGEST,
        invocation_id=(
            "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
        ),
        terminal_digest=(
            "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
        ),
        allocation_digest=(
            "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
        ),
        approved_by="github:fol2",
        approval_reference=(
            "https://github.com/fol2/newsroom/issues/790#issuecomment-5433067552"
        ),
        approved_at="2026-08-27T01:14:18.000000Z",
        scope=ISSUE_790_APPROVED_SCOPE,
        terminal_outcome="FAILED",
        route_open_reason="SYSTEMIC_TRANSPORT",
        root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        predecessor_plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_5_PLAN_DIGEST,
        sequence_ordinal=6,
        controller_timeout_ms=160_000,
        extraction_timeout_ms=180_000,
        cleanup_reserve_ms=20_000,
        fixed_constraints_digest=(
            "sha256:84400663bfddfef14935cdf9c6a0942d548adeab08a732b023e19876de2b2fc2"
        ),
        predecessor_causal_report_digest=(
            "sha256:0addaad5a37b05a47f4701cd2a0b201664176ca49901cf66acb1df904af76771"
        ),
        constraint_change="REVIEWED_NON_TIMEOUT_FIX",
        reviewed_fix_digest=(
            "sha256:433886545558d316b483e760282fae71b996a3dd95ca31234f8900f4153c2df4"
        ),
    ),
    Issue790ApprovedPlanContract(
        schema_version="newsroom.issue-790.iterative-canary-plan.v2",
        plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_8_PLAN_DIGEST,
        invocation_id=(
            "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
        ),
        terminal_digest=(
            "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
        ),
        allocation_digest=(
            "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
        ),
        approved_by="github:fol2",
        approval_reference=(
            "https://github.com/fol2/newsroom/issues/790#issuecomment-5441746872"
        ),
        approved_at="2026-08-27T16:00:00.000000Z",
        scope=ISSUE_790_APPROVED_SCOPE,
        terminal_outcome="FAILED",
        route_open_reason="SYSTEMIC_TRANSPORT",
        root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        predecessor_plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_5_PLAN_DIGEST,
        sequence_ordinal=8,
        controller_timeout_ms=160_000,
        extraction_timeout_ms=180_000,
        cleanup_reserve_ms=20_000,
        fixed_constraints_digest=(
            "sha256:accd35045a4bc3c8d20c50c272755e7d4e6980dc6d7e1a4f029b36b3cd2a20c1"
        ),
        predecessor_causal_report_digest=(
            "sha256:b37cf8c0cf42e47a15dfbca586af72042a02e2561e8e5e290c038676047ce2e4"
        ),
        constraint_change="COMPATIBILITY_FLOOR_ARCHITECTURE",
        reviewed_fix_digest=(
            "sha256:71798bc4f6569e2a3efa44b0e3ffcbe81c29d7e3949ae35b7d86ceacc64785a3"
        ),
    ),
    Issue790ApprovedPlanContract(
        schema_version="newsroom.issue-790.iterative-canary-plan.v2",
        plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_9_PLAN_DIGEST,
        invocation_id=(
            "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
        ),
        terminal_digest=(
            "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
        ),
        allocation_digest=(
            "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
        ),
        approved_by="github:fol2",
        approval_reference=(
            "https://github.com/fol2/newsroom/issues/790#issuecomment-5444911652"
        ),
        approved_at="2026-08-27T20:35:35.000000Z",
        scope=ISSUE_790_APPROVED_SCOPE,
        terminal_outcome="FAILED",
        route_open_reason="SYSTEMIC_TRANSPORT",
        root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        predecessor_plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_8_PLAN_DIGEST,
        sequence_ordinal=9,
        controller_timeout_ms=160_000,
        extraction_timeout_ms=180_000,
        cleanup_reserve_ms=20_000,
        fixed_constraints_digest=(
            "sha256:accd35045a4bc3c8d20c50c272755e7d4e6980dc6d7e1a4f029b36b3cd2a20c1"
        ),
        predecessor_causal_report_digest=(
            "sha256:26e5a7cac3063dfc777e489dd7948db6ab73139e45a96d97deb98ca856b100d3"
        ),
        constraint_change="REVIEWED_NON_TIMEOUT_FIX",
        reviewed_fix_digest=(
            "sha256:b2c07a4303c5449a4bf09017c4a06496c1df9e66ed215305d6cff616a9b4fc0e"
        ),
    ),
    Issue790ApprovedPlanContract(
        schema_version="newsroom.issue-790.iterative-canary-plan.v2",
        plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_10_PLAN_DIGEST,
        invocation_id=(
            "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
        ),
        terminal_digest=(
            "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
        ),
        allocation_digest=(
            "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
        ),
        approved_by="github:fol2",
        approval_reference=(
            "https://github.com/fol2/newsroom/issues/790#issuecomment-5445612635"
        ),
        approved_at="2026-08-27T21:47:43.000000Z",
        scope=ISSUE_790_APPROVED_SCOPE,
        terminal_outcome="FAILED",
        route_open_reason="SYSTEMIC_TRANSPORT",
        root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        predecessor_plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_9_PLAN_DIGEST,
        sequence_ordinal=10,
        controller_timeout_ms=160_000,
        extraction_timeout_ms=180_000,
        cleanup_reserve_ms=20_000,
        fixed_constraints_digest=(
            "sha256:accd35045a4bc3c8d20c50c272755e7d4e6980dc6d7e1a4f029b36b3cd2a20c1"
        ),
        predecessor_causal_report_digest=(
            "sha256:27859022a5040914dad6a721195697b98c42926e2188f046790a4fcff234c9a3"
        ),
        constraint_change="REVIEWED_NON_TIMEOUT_FIX",
        reviewed_fix_digest=(
            "sha256:0d2f621bdea9b83bdd672749dbcc49555cdbbf4ca8738e51e3db10782cab1c89"
        ),
    ),
    Issue790ApprovedPlanContract(
        schema_version="newsroom.issue-790.iterative-canary-plan.v2",
        plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_11_PLAN_DIGEST,
        invocation_id=(
            "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
        ),
        terminal_digest=(
            "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
        ),
        allocation_digest=(
            "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
        ),
        approved_by="github:fol2",
        approval_reference=(
            "https://github.com/fol2/newsroom/issues/790#issuecomment-5446029651"
        ),
        approved_at="2026-08-27T22:50:00.000000Z",
        scope=ISSUE_790_APPROVED_SCOPE,
        terminal_outcome="FAILED",
        route_open_reason="SYSTEMIC_TRANSPORT",
        root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        predecessor_plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_10_PLAN_DIGEST,
        sequence_ordinal=11,
        controller_timeout_ms=160_000,
        extraction_timeout_ms=180_000,
        cleanup_reserve_ms=20_000,
        fixed_constraints_digest=(
            "sha256:accd35045a4bc3c8d20c50c272755e7d4e6980dc6d7e1a4f029b36b3cd2a20c1"
        ),
        predecessor_causal_report_digest=(
            "sha256:ecf044810686da89c223bdd26376aa3af93d48291e616258db0173555ff4d1d1"
        ),
        constraint_change="REVIEWED_NON_TIMEOUT_FIX",
        reviewed_fix_digest=(
            "sha256:95340a480f847098680aef04bcaf22330b0a29968a092508851b233ad1e9e583"
        ),
    ),
    Issue790ApprovedPlanContract(
        schema_version="newsroom.issue-790.iterative-canary-plan.v2",
        plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_12_PLAN_DIGEST,
        invocation_id=(
            "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
        ),
        terminal_digest=(
            "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
        ),
        allocation_digest=(
            "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
        ),
        approved_by="github:fol2",
        approval_reference=(
            "https://github.com/fol2/newsroom/issues/790#issuecomment-5446747058"
        ),
        approved_at="2026-08-28T00:50:00.000000Z",
        scope=ISSUE_790_APPROVED_SCOPE,
        terminal_outcome="FAILED",
        route_open_reason="SYSTEMIC_TRANSPORT",
        root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        predecessor_plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_11_PLAN_DIGEST,
        sequence_ordinal=12,
        controller_timeout_ms=160_000,
        extraction_timeout_ms=180_000,
        cleanup_reserve_ms=20_000,
        fixed_constraints_digest=(
            "sha256:accd35045a4bc3c8d20c50c272755e7d4e6980dc6d7e1a4f029b36b3cd2a20c1"
        ),
        predecessor_causal_report_digest=(
            "sha256:ae2899bc554d8a3fbe4cd108686c0a07e09d7484a704943156e152fe9b8d6450"
        ),
        constraint_change="REVIEWED_NON_TIMEOUT_FIX",
        reviewed_fix_digest=(
            "sha256:174569dfc24edcf9258d9daf4bbbd85647426bc002b97837291e118ff5122513"
        ),
    ),
    Issue790ApprovedPlanContract(
        schema_version="newsroom.issue-790.iterative-canary-plan.v2",
        plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_13_PLAN_DIGEST,
        invocation_id=(
            "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
        ),
        terminal_digest=(
            "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
        ),
        allocation_digest=(
            "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
        ),
        approved_by="github:fol2",
        approval_reference=(
            "https://github.com/fol2/newsroom/issues/790#issuecomment-5450562651"
        ),
        approved_at="2026-08-28T10:00:00.000000Z",
        scope=ISSUE_790_APPROVED_SCOPE,
        terminal_outcome="FAILED",
        route_open_reason="SYSTEMIC_TRANSPORT",
        root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        predecessor_plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_12_PLAN_DIGEST,
        sequence_ordinal=13,
        controller_timeout_ms=160_000,
        extraction_timeout_ms=180_000,
        cleanup_reserve_ms=20_000,
        fixed_constraints_digest=(
            "sha256:accd35045a4bc3c8d20c50c272755e7d4e6980dc6d7e1a4f029b36b3cd2a20c1"
        ),
        predecessor_causal_report_digest=(
            "sha256:922a5e20c4045ba49f675bf1a8375548a01a4cdb03326c97f4c9650886e98743"
        ),
        constraint_change="REVIEWED_NON_TIMEOUT_FIX",
        reviewed_fix_digest=(
            "sha256:eee0d5cb17c37c48354d9cc87e695c62bf6c615f8d29833fc9209bdb2ece76e8"
        ),
    ),
    Issue790ApprovedPlanContract(
        schema_version="newsroom.issue-790.iterative-canary-plan.v2",
        plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_14_PLAN_DIGEST,
        invocation_id=(
            "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
        ),
        terminal_digest=(
            "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
        ),
        allocation_digest=(
            "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
        ),
        approved_by="github:fol2",
        approval_reference=(
            "https://github.com/fol2/newsroom/issues/790#issuecomment-5453897190"
        ),
        approved_at="2026-08-28T14:50:00.000000Z",
        scope=ISSUE_790_APPROVED_SCOPE,
        terminal_outcome="FAILED",
        route_open_reason="SYSTEMIC_TRANSPORT",
        root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        predecessor_plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_13_PLAN_DIGEST,
        sequence_ordinal=14,
        controller_timeout_ms=160_000,
        extraction_timeout_ms=180_000,
        cleanup_reserve_ms=20_000,
        fixed_constraints_digest=(
            "sha256:accd35045a4bc3c8d20c50c272755e7d4e6980dc6d7e1a4f029b36b3cd2a20c1"
        ),
        predecessor_causal_report_digest=(
            "sha256:9832d8f9135f586951feb3f925210627c636742ca599891afc8741b2a52b76dd"
        ),
        constraint_change="REVIEWED_NON_TIMEOUT_FIX",
        reviewed_fix_digest=(
            "sha256:7a2481dfb4daca3f2183b6769959eac59918854f056ecd7123aeaad7b593204e"
        ),
    ),
    Issue790ApprovedPlanContract(
        schema_version="newsroom.issue-790.iterative-canary-plan.v2",
        plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_15_PLAN_DIGEST,
        invocation_id=(
            "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
        ),
        terminal_digest=(
            "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
        ),
        allocation_digest=(
            "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
        ),
        approved_by="github:fol2",
        approval_reference=(
            "https://github.com/fol2/newsroom/issues/790#issuecomment-5454874548"
        ),
        approved_at="2026-08-28T16:15:00.000000Z",
        scope=ISSUE_790_APPROVED_SCOPE,
        terminal_outcome="FAILED",
        route_open_reason="SYSTEMIC_TRANSPORT",
        root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
        predecessor_plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_14_PLAN_DIGEST,
        sequence_ordinal=15,
        controller_timeout_ms=160_000,
        extraction_timeout_ms=180_000,
        cleanup_reserve_ms=20_000,
        fixed_constraints_digest=(
            "sha256:accd35045a4bc3c8d20c50c272755e7d4e6980dc6d7e1a4f029b36b3cd2a20c1"
        ),
        predecessor_causal_report_digest=(
            "sha256:ac329bb3fcd57d80977524084f1d22facdd3c9058cb9afa0cbff90c8480676e3"
        ),
        constraint_change="REVIEWED_NON_TIMEOUT_FIX",
        reviewed_fix_digest=(
            "sha256:2294e17e08ad9a287e52450152b7f4c7e019b9300e36f5efba04397b1b83a42d"
        ),
    ),
)

_STEP16_CHECKED_CANDIDATE = Issue790CheckedCandidateContract(
    schema_version=ISSUE_790_STEP16_CANDIDATE_SCHEMA,
    candidate_digest=ISSUE_790_STEP16_CHECKED_CANDIDATE_DIGEST,
    pending_digest=ISSUE_790_STEP16_PENDING_DIGEST,
    invocation_id=(
        "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
    ),
    terminal_digest=(
        "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
    ),
    allocation_digest=(
        "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
    ),
    predecessor_plan_digest=ISSUE_790_SUCCESS_SEQUENCE_STEP_15_PLAN_DIGEST,
    sequence_ordinal=16,
    projection_policy_version="NewsroomGovernedProposalProjectionV1",
    projection_policy_digest=(
        "sha256:c68a9c5bf81a8d052ba9b05f286b0d1cf664e86e2e00ee3c39684f7809b16a7c"
    ),
    temporal_policy_version="graphiti-source-reference-time-v2",
    validator_contract_version="NewsroomCombinedTemporalNormaliseV2",
    pre_dispatch_operational_requirements_digest=(
        "sha256:968d0875cbed3a37cca56c2aa696598c3996e10d3a0ad6edc5978c21965d587b"
    ),
    reviewed_fix_digest=(
        "sha256:bfb44a10ec9441c9a2c05761650bad0bd6e289910bbb58885241420ede0aaa5c"
    ),
    predecessor_causal_report_digest=(
        "sha256:c10f71ef35bbbd7e4bcc3eac005d3f4959d03dcca699fb447d4f8eeaddaa4ca5"
    ),
    checked_approved_by="checked:issue-790-step16-sealer",
    checked_approval_reference=f"checked:{ISSUE_790_STEP16_PENDING_DIGEST}",
)

_STEP17_CHECKED_CANDIDATE = Issue790CheckedCandidateContract(
    schema_version=ISSUE_790_STEP16_CANDIDATE_SCHEMA,
    candidate_digest=ISSUE_790_STEP17_CHECKED_CANDIDATE_DIGEST,
    pending_digest=ISSUE_790_STEP17_PENDING_DIGEST,
    invocation_id=(
        "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
    ),
    terminal_digest=(
        "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
    ),
    allocation_digest=(
        "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
    ),
    predecessor_plan_digest=ISSUE_790_STEP16_ACTIVATED_PLAN_DIGEST,
    sequence_ordinal=17,
    projection_policy_version="NewsroomGovernedProposalProjectionV1",
    projection_policy_digest=(
        "sha256:c68a9c5bf81a8d052ba9b05f286b0d1cf664e86e2e00ee3c39684f7809b16a7c"
    ),
    temporal_policy_version="graphiti-source-reference-time-v2",
    validator_contract_version="NewsroomCombinedTemporalNormaliseV2",
    pre_dispatch_operational_requirements_digest=(
        "sha256:968d0875cbed3a37cca56c2aa696598c3996e10d3a0ad6edc5978c21965d587b"
    ),
    reviewed_fix_digest=(
        "sha256:0eb14558caad4d87cfd87ac508df2c74883f9fc0eebbe4c19f558ec00584f5a9"
    ),
    predecessor_causal_report_digest=(
        "sha256:cbbbae379cb55cd23503152de4b982dde99873a670c78dec1b23e5789556023d"
    ),
    checked_approved_by="checked:issue-790-step17-sealer",
    checked_approval_reference=f"checked:{ISSUE_790_STEP17_PENDING_DIGEST}",
)

_STEP18_CHECKED_CANDIDATE = Issue790CheckedCandidateContract(
    schema_version=ISSUE_790_STEP16_CANDIDATE_SCHEMA,
    candidate_digest=ISSUE_790_STEP18_CHECKED_CANDIDATE_DIGEST,
    pending_digest=ISSUE_790_STEP18_PENDING_DIGEST,
    invocation_id=(
        "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
    ),
    terminal_digest=(
        "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
    ),
    allocation_digest=(
        "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
    ),
    predecessor_plan_digest=ISSUE_790_STEP17_ACTIVATED_PLAN_DIGEST,
    sequence_ordinal=18,
    projection_policy_version="NewsroomGovernedProposalProjectionV1",
    projection_policy_digest=(
        "sha256:c68a9c5bf81a8d052ba9b05f286b0d1cf664e86e2e00ee3c39684f7809b16a7c"
    ),
    temporal_policy_version="graphiti-source-reference-time-v2",
    validator_contract_version="NewsroomCombinedTemporalNormaliseV2",
    pre_dispatch_operational_requirements_digest=(
        "sha256:968d0875cbed3a37cca56c2aa696598c3996e10d3a0ad6edc5978c21965d587b"
    ),
    reviewed_fix_digest=(
        "sha256:05c15f64c43aeba82e8046394fedfbae89f93e5cc24240398f6b45878aa03ac4"
    ),
    predecessor_causal_report_digest=(
        "sha256:caa65939801e85ecaa1abe6fa091c434f802e14ff4312a5a1ac9545a716adf17"
    ),
    checked_approved_by="checked:issue-790-step18-sealer",
    checked_approval_reference=f"checked:{ISSUE_790_STEP18_PENDING_DIGEST}",
    candidate_event_qualification_digest=(
        "sha256:598445df7fadc3a33336608da40df103b2d952f9422ea22055b19d7c55342c78"
    ),
    candidate_event_id=(
        "sha256:fb49a59d1c421c261bab4586873680e50e8181acfd0d6ebc03a14f889147d896"
    ),
    candidate_ledger_seq=13284,
    candidate_event_manifest_digest=(
        "sha256:317f51b6ad0ed41ce61682913ed5b71285130a9727aa710c278afcc12c091f38"
    ),
)

_STEP19_CHECKED_CANDIDATE = Issue790CheckedCandidateContract(
    schema_version=ISSUE_790_STEP16_CANDIDATE_SCHEMA,
    candidate_digest=ISSUE_790_STEP19_CHECKED_CANDIDATE_DIGEST,
    pending_digest=ISSUE_790_STEP19_PENDING_DIGEST,
    invocation_id=(
        "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
    ),
    terminal_digest=(
        "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
    ),
    allocation_digest=(
        "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
    ),
    predecessor_plan_digest=ISSUE_790_STEP18_ACTIVATED_PLAN_DIGEST,
    sequence_ordinal=19,
    projection_policy_version="NewsroomGovernedProposalProjectionV1",
    projection_policy_digest=(
        "sha256:c68a9c5bf81a8d052ba9b05f286b0d1cf664e86e2e00ee3c39684f7809b16a7c"
    ),
    temporal_policy_version="graphiti-source-reference-time-v2",
    validator_contract_version="NewsroomCombinedTemporalNormaliseV2",
    pre_dispatch_operational_requirements_digest=(
        "sha256:968d0875cbed3a37cca56c2aa696598c3996e10d3a0ad6edc5978c21965d587b"
    ),
    reviewed_fix_digest=(
        "sha256:2c58862fe7a06556812efea88e7b98ef1487daa8ac7e81c3305ccf0b65f9e997"
    ),
    predecessor_causal_report_digest=(
        "sha256:eafcfb63a2e458c0b6661f0119cfb1a82ded9fb6cf47fabb7403c9561a5225c6"
    ),
    checked_approved_by="checked:issue-790-step19-sealer",
    checked_approval_reference=f"checked:{ISSUE_790_STEP19_PENDING_DIGEST}",
    candidate_event_qualification_digest=(
        "sha256:d2a672ee9069d76f263adb18d02e177242feb834875552b0c1c7dca00cf9cc59"
    ),
    candidate_event_id=(
        "sha256:e4ef6fd0af91d5d525af3f37f5cfb422733a1640c84c16cdc162f0e6d8bb0b5b"
    ),
    candidate_ledger_seq=13337,
    candidate_event_manifest_digest=(
        "sha256:34e5a002b331f34ced889b965816e310d744db2d60815c3ea142d9ef3849149d"
    ),
)

_STEP20_CHECKED_CANDIDATE = Issue790CheckedCandidateContract(
    schema_version=ISSUE_790_STEP16_CANDIDATE_SCHEMA,
    candidate_digest=ISSUE_790_STEP20_CHECKED_CANDIDATE_DIGEST,
    pending_digest=ISSUE_790_STEP20_PENDING_DIGEST,
    invocation_id=(
        "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
    ),
    terminal_digest=(
        "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
    ),
    allocation_digest=(
        "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
    ),
    predecessor_plan_digest=ISSUE_790_STEP19_ACTIVATED_PLAN_DIGEST,
    sequence_ordinal=20,
    projection_policy_version="NewsroomGovernedProposalProjectionV1",
    projection_policy_digest=(
        "sha256:c68a9c5bf81a8d052ba9b05f286b0d1cf664e86e2e00ee3c39684f7809b16a7c"
    ),
    temporal_policy_version="graphiti-source-reference-time-v2",
    validator_contract_version="NewsroomCombinedTemporalNormaliseV2",
    pre_dispatch_operational_requirements_digest=(
        "sha256:968d0875cbed3a37cca56c2aa696598c3996e10d3a0ad6edc5978c21965d587b"
    ),
    reviewed_fix_digest=(
        "sha256:25f9adfcc50f3678c5c057b5389f196ec01d1b561535b5e83de656f764c77495"
    ),
    predecessor_causal_report_digest=(
        "sha256:0df9d4de8f0b4d49d041e716320727718f89c201f7d304962cd79edf2aaf4d0c"
    ),
    checked_approved_by="checked:issue-790-step20-sealer",
    checked_approval_reference=f"checked:{ISSUE_790_STEP20_PENDING_DIGEST}",
)

_STEP21_CHECKED_CANDIDATE = Issue790CheckedCandidateContract(
    schema_version=ISSUE_790_STEP16_CANDIDATE_SCHEMA,
    candidate_digest=ISSUE_790_STEP21_CHECKED_CANDIDATE_DIGEST,
    pending_digest=ISSUE_790_STEP21_PENDING_DIGEST,
    invocation_id=(
        "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
    ),
    terminal_digest=(
        "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
    ),
    allocation_digest=(
        "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
    ),
    predecessor_plan_digest=ISSUE_790_STEP20_ACTIVATED_PLAN_DIGEST,
    sequence_ordinal=21,
    projection_policy_version="NewsroomGovernedProposalProjectionV1",
    projection_policy_digest=(
        "sha256:c68a9c5bf81a8d052ba9b05f286b0d1cf664e86e2e00ee3c39684f7809b16a7c"
    ),
    temporal_policy_version="graphiti-source-reference-time-v2",
    validator_contract_version="NewsroomCombinedTemporalNormaliseV2",
    pre_dispatch_operational_requirements_digest=(
        "sha256:968d0875cbed3a37cca56c2aa696598c3996e10d3a0ad6edc5978c21965d587b"
    ),
    reviewed_fix_digest=(
        "sha256:42b784753f0f9c6a9e761744b673bbd3dce786818c51aa1d9d4d52bac5d500b5"
    ),
    predecessor_causal_report_digest=(
        "sha256:406ce1f998c1754e219c6476a9c056996b328e1a96300eae624ad0f4fc063c4c"
    ),
    checked_approved_by="checked:issue-790-step21-sealer",
    checked_approval_reference=f"checked:{ISSUE_790_STEP21_PENDING_DIGEST}",
    candidate_event_qualification_digest=(
        "sha256:dc45e4f2e78217e0bd151a18af284ed007e0ddb94fe94394a131217618f9556a"
    ),
    candidate_event_id=(
        "sha256:90c3b4de731f2df8d4353e516762f65450570e1e8372ed7b703423f717351ae7"
    ),
    candidate_ledger_seq=13361,
    candidate_event_manifest_digest=(
        "sha256:c75596c1344ec017d6f4980849cc18d4d59212faa71d85bc428e437a0d8f81c7"
    ),
)

_STEP22_CHECKED_CANDIDATE = Issue790CheckedCandidateContract(
    schema_version=ISSUE_790_STEP16_CANDIDATE_SCHEMA,
    candidate_digest=ISSUE_790_STEP22_CHECKED_CANDIDATE_DIGEST,
    pending_digest=ISSUE_790_STEP22_PENDING_DIGEST,
    invocation_id=(
        "sha256:d0712807fd025520d0a94e5a28c532d4cb8684c936387290fe7eeb49d0b2336c"
    ),
    terminal_digest=(
        "sha256:d48e844404516bd41b17038b42a834c6e54bf5da520ef046f3baf81ea7a8cbbe"
    ),
    allocation_digest=(
        "sha256:c789330ca7151d097e6d366dd65481ff21d55f93891ff61e368d7369b12c7120"
    ),
    predecessor_plan_digest=ISSUE_790_STEP21_ACTIVATED_PLAN_DIGEST,
    sequence_ordinal=22,
    projection_policy_version="NewsroomGovernedProposalProjectionV1",
    projection_policy_digest=(
        "sha256:c68a9c5bf81a8d052ba9b05f286b0d1cf664e86e2e00ee3c39684f7809b16a7c"
    ),
    temporal_policy_version="graphiti-source-reference-time-v2",
    validator_contract_version="NewsroomCombinedTemporalNormaliseV2",
    pre_dispatch_operational_requirements_digest=(
        "sha256:968d0875cbed3a37cca56c2aa696598c3996e10d3a0ad6edc5978c21965d587b"
    ),
    reviewed_fix_digest=(
        "sha256:cd263467b00c0b93ad73cdba484cd2dbdd0ccab302bcc521c1a906aa052a1ebf"
    ),
    predecessor_causal_report_digest=(
        "sha256:56a309f1a025cca776048559fa3ceb53d0d4f7c53e8fc7b844a6945e44e41acc"
    ),
    checked_approved_by="checked:issue-790-step22-sealer",
    checked_approval_reference=f"checked:{ISSUE_790_STEP22_PENDING_DIGEST}",
    candidate_event_qualification_digest=(
        "sha256:df39aa693e712bc8d9b1c8c691f9effa6f1ff40bf945e20b9b997dbf32a16ed5"
    ),
    candidate_event_id=(
        "sha256:b39a1e6ea465ca4a993893d4ae51c94ca9ac3e0db7f4fd70a8c780367263be6b"
    ),
    candidate_ledger_seq=13665,
    candidate_event_manifest_digest=(
        "sha256:43ae5b036c46427d2ef7d55c1290c32e23ae5aa313dd7c66cac384272ed97404"
    ),
)

_CHECKED_CANDIDATES = {
    _STEP16_CHECKED_CANDIDATE.candidate_digest: _STEP16_CHECKED_CANDIDATE,
    _STEP17_CHECKED_CANDIDATE.candidate_digest: _STEP17_CHECKED_CANDIDATE,
    _STEP18_CHECKED_CANDIDATE.candidate_digest: _STEP18_CHECKED_CANDIDATE,
    _STEP19_CHECKED_CANDIDATE.candidate_digest: _STEP19_CHECKED_CANDIDATE,
    _STEP20_CHECKED_CANDIDATE.candidate_digest: _STEP20_CHECKED_CANDIDATE,
    _STEP21_CHECKED_CANDIDATE.candidate_digest: _STEP21_CHECKED_CANDIDATE,
    _STEP22_CHECKED_CANDIDATE.candidate_digest: _STEP22_CHECKED_CANDIDATE,
}
_CHECKED_CANDIDATES_BY_PENDING = {
    contract.pending_digest: contract
    for contract in _CHECKED_CANDIDATES.values()
}


def issue_790_owner_activated_sequence(ordinal: object) -> bool:
    """True for one-shot owner-activated sequence ordinals."""

    return type(ordinal) is int and ordinal in ISSUE_790_OWNER_ACTIVATED_SEQUENCE_ORDINALS


def issue_790_checked_candidate_contract(
    candidate_digest: str,
) -> Issue790CheckedCandidateContract:
    """Return a seal-proof candidate. This is not live authority."""

    try:
        return _CHECKED_CANDIDATES[candidate_digest]
    except KeyError:
        raise KeyError(candidate_digest) from None


def issue_790_checked_candidate_contract_for_pending(
    pending_digest: str,
) -> Issue790CheckedCandidateContract:
    """Return the seal-proof candidate bound to one pending digest."""

    try:
        return _CHECKED_CANDIDATES_BY_PENDING[pending_digest]
    except KeyError:
        raise KeyError(pending_digest) from None


def issue_790_approved_plan_contract(
    plan_digest: str,
) -> Issue790ApprovedPlanContract:
    """Return the exact reviewed contract, including the legacy first plan."""

    if plan_digest == ISSUE_790_STEP16_REVOKED_CHECKED_LIVE_PLAN_DIGEST:
        raise KeyError(plan_digest)
    if plan_digest == ISSUE_790_APPROVED_PLAN_DIGEST:
        # Keep these aliases live so fixture tests can bind one exact synthetic plan
        # without broadening the production registry.
        return Issue790ApprovedPlanContract(
            schema_version="newsroom.issue-790.conservative-disposition-plan.v1",
            plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
            invocation_id=ISSUE_790_APPROVED_INVOCATION_ID,
            terminal_digest=ISSUE_790_APPROVED_TERMINAL_DIGEST,
            allocation_digest=ISSUE_790_APPROVED_ALLOCATION_DIGEST,
            approved_by=ISSUE_790_APPROVED_BY,
            approval_reference=ISSUE_790_APPROVAL_REFERENCE,
            approved_at=ISSUE_790_APPROVED_AT,
            scope=ISSUE_790_APPROVED_SCOPE,
            terminal_outcome=ISSUE_790_APPROVED_TERMINAL_OUTCOME,
            route_open_reason=ISSUE_790_APPROVED_ROUTE_OPEN_REASON,
            root_plan_digest=ISSUE_790_APPROVED_PLAN_DIGEST,
            predecessor_plan_digest=None,
            sequence_ordinal=0,
            controller_timeout_ms=80_000,
            extraction_timeout_ms=180_000,
            cleanup_reserve_ms=20_000,
            fixed_constraints_digest=None,
            predecessor_causal_report_digest=None,
            constraint_change=None,
            reviewed_fix_digest=None,
        )
    for contract in _SUCCESS_SEQUENCE_CONTRACTS:
        if contract.plan_digest == plan_digest:
            return contract
    raise KeyError(plan_digest)


def issue_790_approved_plan_contracts() -> tuple[Issue790ApprovedPlanContract, ...]:
    """Return every exact plan-to-target binding embedded by reviewed code."""

    return (
        issue_790_approved_plan_contract(ISSUE_790_APPROVED_PLAN_DIGEST),
        *_SUCCESS_SEQUENCE_CONTRACTS,
    )


def issue_790_invocation_plan_digests(invocation_id: str) -> frozenset[str]:
    """Return every reviewed plan digest bound to one retained invocation."""

    return frozenset(
        contract.plan_digest
        for contract in issue_790_approved_plan_contracts()
        if contract.invocation_id == invocation_id
    )


__all__ = [
    "ISSUE_790_APPROVAL_REFERENCE",
    "ISSUE_790_APPROVED_ALLOCATION_DIGEST",
    "ISSUE_790_APPROVED_AT",
    "ISSUE_790_APPROVED_BY",
    "ISSUE_790_APPROVED_INVOCATION_ID",
    "ISSUE_790_APPROVED_PLAN_DIGEST",
    "ISSUE_790_APPROVED_SCOPE",
    "ISSUE_790_APPROVED_TERMINAL_DIGEST",
    "ISSUE_790_APPROVED_TERMINAL_OUTCOME",
    "ISSUE_790_APPROVED_ROUTE_OPEN_REASON",
    "ISSUE_790_SUCCESS_SEQUENCE_PLAN_DIGEST",
    "ISSUE_790_SUCCESS_SEQUENCE_STEP_2_PLAN_DIGEST",
    "ISSUE_790_SUCCESS_SEQUENCE_STEP_3_PLAN_DIGEST",
    "ISSUE_790_SUCCESS_SEQUENCE_STEP_4_PLAN_DIGEST",
    "ISSUE_790_SUCCESS_SEQUENCE_STEP_5_PLAN_DIGEST",
    "ISSUE_790_SUCCESS_SEQUENCE_STEP_6_PLAN_DIGEST",
    "ISSUE_790_SUCCESS_SEQUENCE_STEP_8_PLAN_DIGEST",
    "ISSUE_790_SUCCESS_SEQUENCE_STEP_9_PLAN_DIGEST",
    "ISSUE_790_SUCCESS_SEQUENCE_STEP_10_PLAN_DIGEST",
    "ISSUE_790_SUCCESS_SEQUENCE_STEP_11_PLAN_DIGEST",
    "ISSUE_790_SUCCESS_SEQUENCE_STEP_12_PLAN_DIGEST",
    "ISSUE_790_SUCCESS_SEQUENCE_STEP_13_PLAN_DIGEST",
    "ISSUE_790_SUCCESS_SEQUENCE_STEP_14_PLAN_DIGEST",
    "ISSUE_790_SUCCESS_SEQUENCE_STEP_15_PLAN_DIGEST",
    "ISSUE_790_STEP16_CANDIDATE_SCHEMA",
    "ISSUE_790_STEP16_CHECKED_CANDIDATE_DIGEST",
    "ISSUE_790_STEP16_PENDING_DIGEST",
    "ISSUE_790_STEP16_OWNER_APPROVAL_SCHEMA",
    "ISSUE_790_STEP16_ACTIVATION_SCHEMA",
    "ISSUE_790_STEP16_ACTIVATION_POLICY_VERSION",
    "ISSUE_790_STEP16_APPROVAL_MARKER",
    "ISSUE_790_STEP16_REVOKED_CHECKED_LIVE_PLAN_DIGEST",
    "ISSUE_790_STEP16_ACTIVATED_PLAN_DIGEST",
    "ISSUE_790_STEP16_ACTIVATION_DIGEST",
    "ISSUE_790_STEP17_PENDING_DIGEST",
    "ISSUE_790_STEP17_CHECKED_CANDIDATE_DIGEST",
    "ISSUE_790_STEP17_ACTIVATED_PLAN_DIGEST",
    "ISSUE_790_STEP17_ACTIVATION_DIGEST",
    "ISSUE_790_STEP17_GATE_OUTCOME_DIGEST",
    "ISSUE_790_STEP18_PENDING_DIGEST",
    "ISSUE_790_STEP18_CHECKED_CANDIDATE_DIGEST",
    "ISSUE_790_STEP18_ACTIVATED_PLAN_DIGEST",
    "ISSUE_790_STEP18_ACTIVATION_DIGEST",
    "ISSUE_790_STEP19_PENDING_DIGEST",
    "ISSUE_790_STEP19_CHECKED_CANDIDATE_DIGEST",
    "ISSUE_790_STEP19_ACTIVATED_PLAN_DIGEST",
    "ISSUE_790_STEP19_ACTIVATION_DIGEST",
    "ISSUE_790_STEP20_PENDING_DIGEST",
    "ISSUE_790_STEP20_CHECKED_CANDIDATE_DIGEST",
    "ISSUE_790_STEP20_ACTIVATED_PLAN_DIGEST",
    "ISSUE_790_STEP20_ACTIVATION_DIGEST",
    "ISSUE_790_STEP21_PENDING_DIGEST",
    "ISSUE_790_STEP21_CHECKED_CANDIDATE_DIGEST",
    "ISSUE_790_STEP21_ACTIVATED_PLAN_DIGEST",
    "ISSUE_790_STEP21_ACTIVATION_DIGEST",
    "ISSUE_790_STEP22_PENDING_DIGEST",
    "ISSUE_790_STEP22_CHECKED_CANDIDATE_DIGEST",
    "ISSUE_790_OWNER_ACTIVATED_SEQUENCE_ORDINALS",
    "Issue790ApprovedPlanContract",
    "Issue790CheckedCandidateContract",
    "issue_790_approved_plan_contract",
    "issue_790_approved_plan_contracts",
    "issue_790_checked_candidate_contract",
    "issue_790_checked_candidate_contract_for_pending",
    "issue_790_owner_activated_sequence",
    "issue_790_invocation_plan_digests",
]
