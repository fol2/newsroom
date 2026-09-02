# Issue #898 research-only Rust comparator

Profiling research for [#898](https://github.com/fol2/newsroom/issues/898). This
crate is not a product dependency, Cargo workspace member, runtime route,
daemon, or CI contract. It reads a copied proving snapshot and emits an
observation-scan manifest. It has no authority-store write, credential,
provider, Neo4j, or publication capability.
