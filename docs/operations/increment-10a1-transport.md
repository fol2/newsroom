# Increment 10A1 transport contracts

`newsroom.increment10.transport` defines immutable semantic submission and attempt observations for the exact local-fixture destination. Submission identity is derived from Candidate Version, Handoff digest, accepted plan digest and destination, independently of transient request IDs.

Intent must be persisted before any later adapter effect. Responses must correlate to the exact request. Uncertain states reconcile only through the dedicated late-acknowledgement transition. Terminal records are immutable. The module exposes no I/O adapter: acknowledgement grants no evidence, editorial, publication or production authority.
