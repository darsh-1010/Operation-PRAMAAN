# Blockchain decision ledger

Every finalized screening decision (ACCEPT / MANUAL_REVIEW / REJECT / timeout) is made
**tamper-evident**: if anyone later edits, deletes, inserts or back-dates a stored decision,
`GET /ledger/verify/{uuid}` reports it as `TAMPERED`.

It does **not** stop deletion (that's what Postgres backups are for), and it does **not** make
a wrong AI decision right: it proves what was decided and when.

## How it works

```
decision finalized ─► _persist() (main.py)
                       risk_results row + canonical JSON + leaf = sha256(0x00 ‖ canonical)
every ANCHOR_INTERVAL_SECONDS, one worker (Postgres advisory lock) in anchor.py:
  1. unbatched rows ─► Merkle tree (ledger.py, RFC 6962 domain separation) ─► 32-byte root
  2. PramanAnchor.anchor(batchId, root, leafCount) on-chain  (chain.py)
  3. anchor_batches row: PENDING ─► CONFIRMED (+ tx hash, block)
GET /ledger/verify/{uuid}:
  row columns == sealed JSON?  ─► re-hash leaf ─► rebuild batch root from ALL batch records
  ─► compare with the root the CHAIN holds for that batch id (never the DB's own copy)
```

| File | Job |
|---|---|
| `ledger.py` | canonical JSON, leaf hash, Merkle root / proof (stdlib only) |
| `ledger_db.py` | batch + lookup SQL |
| `chain.py` | the only web3 code: send/read the contract |
| `anchor.py` | background worker, crash-safe retries |
| `ledger_routes.py` | `GET /ledger/verify/{uuid}`, `/ledger/status`, `/ledger/batches[/{id}]` |
| `contracts/PramanAnchor.sol` (+ compiled `.json`) | owner-only, append-only, strictly sequential batch ids |
| `deploy_contract.py` | one-time deploy (auto on local Anvil only) |
| `test_ledger.py` | Merkle maths + end-to-end on a real in-process EVM, incl. 3 insider-tampering attacks |

## What goes on-chain

Only `(batchId, merkleRoot, leafCount)`. No names, document numbers, photos or even screening
uuids. The sealed record in Postgres holds uuid, score, decision, flags, reason codes and a
timestamp, and nothing identifying. This is what keeps it compatible with the DPDP Act's
erasure/correction rights: personal data stays off-chain and deletable, and the chain only holds
hashes that reveal nothing.

## Running it

**Local (docker compose):** nothing to do. `anvil` (a local EVM chain) starts, `ledger-deploy`
deploys the contract to the deterministic dev address, and the risk engine anchors every 30s.
Open the frontend's **Blockchain Ledger** tab.

**Polygon Amoy testnet (public, free, clickable explorer links for a demo):**
1. Create a new wallet and fund it from a faucet (e.g. https://faucet.polygon.technology).
2. In `.env`: `CHAIN_RPC_URL=https://rpc-amoy.polygon.technology`,
   `CHAIN_EXPLORER_URL=https://amoy.polygonscan.com`, `ANCHOR_PRIVATE_KEY=<new key>`,
   `ANCHOR_CONFIRMATIONS=3`, and clear `ANCHOR_CONTRACT_ADDRESS`.
3. `python deploy_contract.py --deploy` → paste the printed address into `ANCHOR_CONTRACT_ADDRESS`.
4. `export PRAMAN_CHAIN_RPC_URL=https://rpc-amoy.polygon.technology` before `docker compose up`.

**Production:** the same code runs on any EVM chain. For government data, use a permissioned
Hyperledger Besu (QBFT) network whose ≥4 validators are run by *different* organisations
(e.g. SSB, MHA, NIC, an auditor), or MeitY's Vishvasya/NBF blockchain-as-a-service. If one team
runs every node, the chain is only as trustworthy as that team.

## Demo: catching a corrupt insider

```bash
docker compose exec postgres psql -U postgres -c \
  "UPDATE risk_results SET decision='PASS' WHERE session_id='<uuid>';"
```
Click **Re-verify** on that case, or verify the uuid in the Ledger tab: it turns **Tampering
detected**, and the trace shows which check broke.

## Operating notes / limits

- **Window of exposure:** a decision is only protected once its batch is anchored (≤ one
  interval + block time). Anyone with DB write access before then can alter it undetected.
  Shorten `ANCHOR_INTERVAL_SECONDS` to shrink that window (cost ≈ 1 tx per interval).
- **Halt on discrepancy:** if the chain holds a different root for a batch than the DB, the
  worker stops anchoring and reports the error rather than "repairing" it. That mismatch is
  evidence. Investigate before doing anything.
- **Never redeploy the contract** once real batches are anchored: old anchors live at the old
  address.
- **The signing key is the crown jewel.** Anyone holding it can anchor forged batches *going
  forward* (but can't rewrite past ones). Use a KMS/HSM in production.
- **Alert on** `praman_audit_persist_failures_total > 0` (a decision that never reached the audit
  table can never be anchored) and on `/ledger/status.last_error`.
- `/ledger/*` is unauthenticated, like every endpoint in this repo today. Put it behind auth
  before exposing it beyond the checkpoint network.
