# Increment 1B2 Neo4j Community qualification

## Qualification target

Increment 1B2 pins the development and GitHub Actions integration target to:

- Neo4j Community container: `neo4j:2026.06.0-community-trixie`
- Neo4j server version: `2026.06.0`
- official Neo4j Python driver: `neo4j==6.2.0`
- GitHub qualification runtime: Python 3.12 with the repository `uv.lock`

The exact image tag avoids a floating `latest` target and the Python driver is pinned in both `pyproject.toml` and `uv.lock`. The adapter rejects a different server version, edition, or driver version during its authenticated compatibility check.

This is an initial development and CI qualification target. It is **not** final production admission.

Primary references:

- Neo4j Docker image documentation: <https://neo4j.com/docs/operations-manual/current/docker/>
- Neo4j user management: <https://neo4j.com/docs/operations-manual/current/authentication-authorization/manage-users/>
- Neo4j Python driver compatibility: <https://neo4j.com/docs/python-manual/current/install/>
- official driver package: <https://pypi.org/project/neo4j/6.2.0/>

## Authority and transaction boundary

SQLite and governed objects remain the authority. Neo4j contains rebuildable structural context only.

A delivery follows this explicit sequence:

1. authenticate and authorize the exact B1 `APPLIED` authority transition;
2. resolve the retained SQLite event, family, mapping and provenance;
3. commit one explicit Neo4j transaction containing allow-listed nodes, relations and an exact delivery marker;
4. commit the pre-authorized B1 SQLite transition.

SQLite and Neo4j are not presented as one atomic distributed transaction. If the process fails after the graph commit but before the SQLite transition, the public facade raises `Neo4jAuthorityCommitPending`. A retry observes the exact Neo4j delivery marker, treats the graph operation as a duplicate, and retries only the exact B1 authority transition. Neo4j success by itself never advances a checkpoint, closes a gap, retires a dead letter, or changes generation authority.

## Adapter and identity boundary

The official driver and fixed Cypher statements live only in `newsroom.projection.neo4j._adapter`. Production code can acquire the adapter only through the private authority composition module.

The public structural facade exposes only:

- exact typed delivery;
- bounded typed structural read.

It does not expose arbitrary Cypher, arbitrary properties, caller labels, caller relation names, schema bootstrap, cleanup, sessions, drivers, or Neo4j internal IDs. Canonical Newsroom IDs are the only graph identities returned to callers. Every relation retains exact authority/event provenance needed to return to SQLite and governed-object seams.

The accepted direct relation allow-list is:

`HAS_VERSION`, `HAS_REVISION`, `HAS_REPRESENTATION`, `PRODUCED_SIGNAL`, `PROMOTED_TO_LEAD`, `DERIVED_FROM`, `CONTAINS_PAYLOAD`, `PROJECTED_FROM_EVENT`.

`RELATED_TO`, model predicates, caller labels and unregistered ontology or mapping versions are rejected by typed B1 contracts.

## Authentication and Community Edition limitation

The actual-service workflow starts Neo4j with authentication enabled. It uses a disposable CI administrator only to create a separate native `newsroom_projector` identity, then executes the B2 adapter and tests with the projector credential. The repository configuration contract rejects the bootstrap `neo4j` administrator identity for projector use. Missing or wrong credentials fail closed, and configuration, exceptions and response metadata do not disclose passwords.

Neo4j Community Edition does not provide the fine-grained role boundary required to call this database-level least privilege. Community users have implied administrative capability. The dedicated user therefore proves credential separation and supports process, network and secret-distribution controls; it does not prove fine-grained Neo4j RBAC.

Required compensating controls for this qualification target are:

- only the private projector composition receives the credential;
- no agent, source adapter, model or Graphiti module imports the writer;
- no general Cypher surface exists;
- service networking is restricted to the projector/test process;
- CI credentials are fixed disposable values and are not production credentials;
- production secrets must be supplied out of repository and omitted from logs and metadata.

## Actual-service evidence

`.github/workflows/projection-b2-neo4j.yml` starts the exact container, waits for authenticated readiness, creates the dedicated projector user, verifies the exact official driver and executes:

- B1 plus B2 unit and boundary regressions;
- authenticated compatibility and schema bootstrap;
- public structural write/read round trip;
- canonical-ID round trip without Neo4j internal IDs;
- exact duplicate replay;
- changed-digest conflict under the same delivery identity;
- generation isolation;
- wrong-credential failure;
- generation-scoped deterministic cleanup.

The workflow parses the actual-service JUnit report and fails if actual tests are skipped, replaced by a fake, or report any failure/error.

## Deferred production admission

Increment 1B2 does not settle:

- final Neo4j release and immutable image-manifest admission;
- intended-hardware performance, capacity and licence qualification;
- production TLS, firewall, service supervision and credential rotation;
- Community compensating-control acceptance by the owner;
- offline dump/load, backup encryption, key custody, restore drills, RPO or RTO;
- production monitoring, alert thresholds and incident procedures;
- B3 destructive rebuild, validation and active-generation promotion;
- Graphiti, model, prompt, embedding, vector, full-text or hybrid retrieval versions.

No live source access, Graphiti execution, model or embedding call, protected-content vector generation, Candidate/triage, Evidence Intake, publication, shadow, canary, production activation, spending or public effect is authorized by this qualification.
