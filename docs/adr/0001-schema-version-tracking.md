# ADR-0001: Track SQLite schema versions without automatic legacy baselining

**Status:** Accepted  
**Date:** 2026-09-11  
**Deciders:** ScholarDesk maintainers

## Context

`Base.metadata.create_all()` creates missing tables but never upgrades existing
tables. Earlier one-off migration scripts have no common version history, so
silently marking a real existing database as current could conceal a missing
column, index, or data transformation.

## Decision

New databases receive schema version `1` at startup. Existing databases without
a version record remain untouched and are logged as unmanaged. A future version
increase must provide an explicit migration with backup preflight, verification,
and rollback instructions. The application refuses to run a database newer than
the installed version or one pending a defined migration.

## Options Considered

### Automatic baseline of all unversioned databases

Low implementation cost, but unsafe: it can label an incomplete legacy schema
as current without performing the migration it needs.

### Fresh-database versioning with explicit legacy migration

Slightly more operational work, but preserves real data and makes every future
upgrade auditable and reversible.

## Consequences

- Fresh portable installs have a reliable schema baseline.
- Legacy databases remain available but are not silently modified.
- The next schema change must add a versioned migration command before changing
  the ORM model.
