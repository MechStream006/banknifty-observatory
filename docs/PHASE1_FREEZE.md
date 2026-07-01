# Phase-1 Architecture Freeze

**Status:** FROZEN
**Scope:** the immutable observation record contract and its persistence/provenance guarantees.
**Governing principle:** *harden the record, not the runtime.* Freeze the data contract; evolve everything around it additively.

The one irreplaceable asset of this observatory is the historical observation
corpus. This document records what is frozen, the invariants that keep the
corpus interpretable for 5–10 years, and the conditions under which the freeze
remains valid.

---

## 1. What is frozen

The following are the frozen Phase-1 contract. Changing any of them is a
schema event governed by §3.

- **`ObservationRecord`** — the per-tick record shape (`lib/discovery/_models.py`).
- **`OptionQuote`** — the per-contract structured identity (underlying, expiry,
  strike, option_side) plus metrics (oi, volume, ltp). Deliberately
  **option-specific** (Decision 1); future instrument classes get their own
  typed shapes, not a shared generic base.
- **`SnapshotMeta`** — per-snapshot context including `schema_version`,
  `collection_contract_version`, and `chain_step_size`.
- **`SnapshotContinuity`** — snapshot-to-snapshot linkage
  (previous_snapshot_id, previous_timestamp, expected/actual interval, status).
- **Version axes** — `OBSERVATION_SCHEMA_VERSION` (=2),
  `COLLECTION_CONTRACT_VERSION` (=1), and the config `schema_version`.
- **Persistence contract** — append-only JSONL, one line per record, durably
  persisted (`write → flush → fsync`), partitioned by **IST trading day**
  (deterministic, host-timezone independent).

---

## 2. The three sign-off decisions

### Decision 1 — `OptionQuote` stays option-specific
`OptionQuote` is **not** generalized into a base class for futures/VIX. The
corpus is defined by serialized shape, not the Python class hierarchy; a generic
base would either bloat option records with null derivative fields or share
nothing meaningful. Futures have a reserved, typed home (`futures_result`).
Each instrument class earns its own honest shape when it arrives.

### Decision 2 — Run manifest is two-phase
The provenance manifest (`lib/discovery/manifest.py`) is written twice to the
same `{run_id}.json`:
1. **`running`** — before the poll loop, with all statically-known provenance.
2. **`completed` / `aborted`** — after the run, with `ended_at` and tick outcome.

`run_id` equals the `session_id` stamped on every record, so a run killed
between the two writes leaves a `status="running"` manifest that is **still
joinable to the records it produced** — an explicit "started but did not finish"
record, never an orphan. *(Mandatory before unattended production — now implemented.)*

### Decision 3 — No `record_type` discriminator, under a documented invariant
A per-record `record_type` tag is **rejected** as complexity the current design
does not need, conditioned on the invariant in §4. `schema_version` +
`collection_contract_version` are sufficient because the raw stream carries
exactly one record type.

---

## 3. Schema compatibility policy (enforced)

Enforced by `tests/unit/test_discovery/test_schema_policy.py` and documented in
`lib/discovery/_models.py`.

- **Additive-only within a schema version.** New optional fields (with defaults)
  may be added without a version bump. Two records sharing a `schema_version`
  may carry different key sets; an older record simply lacks the newer keys.
- **Breaking changes require a version bump.** Removing a field, renaming a
  field, or changing the meaning/units of an existing field **requires an
  `OBSERVATION_SCHEMA_VERSION` increment.**
- **Readers must tolerate unknown fields.** Any consumer ignores keys it does
  not recognize rather than failing, so newer records stay readable by older
  tooling.

---

## 4. Single-record-type invariant (Decision 3 condition)

> **`raw/*.jsonl` contains exactly one record type: `ObservationRecord`.**
> New instrument classes (futures, and any future addition) are **nested into
> `ObservationRecord`** (e.g. via the reserved `futures_result` slot) and
> versioned through `OBSERVATION_SCHEMA_VERSION`. A genuinely distinct record
> kind must be written to a **separate stream/directory** — never mixed into
> the observation stream.

This invariant is what makes the absence of a `record_type` discriminator safe.
**If this invariant is ever violated, `record_type` must be introduced**, and
that introduction is itself a schema event (§3). The provenance manifest is a
separate artifact in `manifests/` and does not violate this invariant.

---

## 5. Freeze Condition 5 — Corpus immutability & parser compatibility

The persistence layer is **immutable and append-only for the life of the corpus.**

- **The corpus is never rewritten.** Historical JSONL files are never edited,
  reformatted, back-filled, or migrated in place. Once a record is written and
  fsynced, it is permanent.
- **Additive evolution only.** The record evolves solely by the additive policy
  in §3. There is no "clean-up pass" over old data.
- **`schema_version` governs parser behavior.** A reader selects how to
  interpret a record from its embedded `schema_version` (and, where relevant,
  `collection_contract_version`) — not from ambient assumptions about the file's
  age or contents.
- **Older parsers are never retrofitted to rewrite historical data.** New
  parser versions read old records under their original schema; they do not
  "upgrade" stored records to a newer shape. Transformation, when needed,
  produces **derived** artifacts in separate locations, leaving the raw corpus
  untouched.

---

## 6. Conditions under which the freeze remains valid

The freeze is valid so long as all of the following hold:

1. **Manifest orphan-window closed (Decision 2).** Two-phase manifest is in
   place; it must remain in place before/through unattended production. *(Done.)*
2. **Single-record-type invariant (§4) documented and honored.** Violating it
   requires introducing `record_type` as a schema event.
3. **Additive-only policy (§3) holds without exception.** Any removal/rename/
   semantic change bumps `OBSERVATION_SCHEMA_VERSION`.
4. **Corpus immutability (§5) holds.** No in-place rewrite of historical data,
   ever; parsers dispatch on `schema_version`.
5. **Live-validation assumptions confirmed** against a full session: `fsync`
   behavior on the production EBS volume, presence of the raw `ltp` key, and the
   ±50% snapshot-continuity tolerance. Tuning the tolerance is a runtime
   constant change, not a schema change, and does not break the freeze.

Break any of these and the architecture is no longer validly "Phase-1 frozen"
until the corresponding schema/version action is taken.

---

## 7. Version axes (reference)

| Axis | Constant / source | Governs |
|---|---|---|
| Observation schema | `OBSERVATION_SCHEMA_VERSION` (=2) | record **layout** |
| Collection contract | `COLLECTION_CONTRACT_VERSION` (=1) | what the collector **observed** |
| Config schema | `BNO_CONFIG_SCHEMA_VERSION` (=2) | **configuration** contract |

The three axes are independent: a record may keep its layout while the
observation intent changes, and vice versa.
