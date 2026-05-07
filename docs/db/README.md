# KnowNet DB Design

This folder is the active database design reference.

Phase 29 is intentionally documentation-first. It does not rewrite the live
SQLite schema. It decides what should be preserved, rebuilt, simplified, or
discarded before DB v2 work starts.

## Principles

- SQLite remains the database.
- Clean structure is preferred over compatibility with early phase leftovers.
- Durable operator/AI data is preserved unless reset is explicitly chosen.
- Derived indexes, generated packets, caches, and old compatibility bridges may
  be rebuilt or removed.
- Use established standards where they fit; do not invent heavier machinery.
- Do not add server databases, background infrastructure, or enterprise
  migration complexity.

## Documents

- [Schema Inventory](SCHEMA_INVENTORY.md): current tables and reset/migration
  classification.
- [DB v2 Blueprint](DB_V2_BLUEPRINT.md): target entity boundaries, mapping,
  reset/migration strategy, and next implementation step.

