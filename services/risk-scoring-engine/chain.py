"""The only code that talks to the blockchain: a thin web3.py wrapper around the
PramanAnchor contract (contracts/PramanAnchor.sol). Works unchanged against any EVM chain —
local Anvil, Polygon Amoy/mainnet, or a permissioned Hyperledger Besu network — only the
env vars below change.

    CHAIN_RPC_URL           JSON-RPC endpoint (blank = ledger disabled, screening unaffected)
    ANCHOR_CONTRACT_ADDRESS deployed PramanAnchor (python deploy_contract.py prints it)
    ANCHOR_PRIVATE_KEY      the contract owner's key — the one secret in this whole feature
    CHAIN_EXPLORER_URL      optional, e.g. https://amoy.polygonscan.com, for links in the UI
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from web3 import Web3

logger = logging.getLogger("risk_engine.chain")

ARTIFACT = json.loads((Path(__file__).parent / "contracts" / "PramanAnchor.json").read_text())

# Anvil/Hardhat's default account #0. Public knowledge — anyone can sign with it, so it must
# never be accepted anywhere but a local dev chain (chain id 31337).
_PUBLIC_DEV_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_DEV_CHAIN_ID = 31337
RECEIPT_TIMEOUT_SECONDS = 120


class ChainError(RuntimeError):
    pass


class Chain:
    def __init__(self, w3: Web3, contract_address: str, private_key: str, explorer_url: str = "") -> None:
        self.w3 = w3
        self.chain_id = w3.eth.chain_id
        if private_key.lower() == _PUBLIC_DEV_KEY and self.chain_id != _DEV_CHAIN_ID:
            raise ChainError(f"refusing the public Anvil dev key on chain {self.chain_id} — set a real ANCHOR_PRIVATE_KEY")
        self.account = w3.eth.account.from_key(private_key)
        self.address = Web3.to_checksum_address(contract_address)
        if not w3.eth.get_code(self.address):
            raise ChainError(f"no contract deployed at {self.address} on chain {self.chain_id} — run deploy_contract.py")
        self.contract = w3.eth.contract(address=self.address, abi=ARTIFACT["abi"])
        owner = self.contract.functions.owner().call()
        if owner != self.account.address:
            raise ChainError(f"signer {self.account.address} is not the contract owner {owner}")
        self.explorer_url = explorer_url.rstrip("/")

    def get_batch(self, batch_id: int) -> Optional[dict]:
        """What the chain says batch_id sealed, or None if it was never anchored. This — not
        the DB's own copy of the root — is what verification trusts."""
        root, leaf_count, timestamp = self.contract.functions.getBatch(batch_id).call()
        if timestamp == 0:
            return None
        return {"root": root.hex().removeprefix("0x"), "leaf_count": leaf_count, "timestamp": timestamp}

    def last_batch_id(self) -> int:
        return self.contract.functions.lastBatchId().call()

    def send_anchor(self, batch_id: int, root_hex: str, leaf_count: int, attempt: int = 0) -> str:
        """Signs and broadcasts anchor(); returns the tx hash without waiting for it to mine.
        Uses the CONFIRMED nonce, so a retry replaces a stuck earlier attempt instead of queueing
        behind it — fees are bumped 25% per attempt (nodes require >=10% to accept a replacement)."""
        tx = self.contract.functions.anchor(batch_id, bytes.fromhex(root_hex), leaf_count).build_transaction({
            "from": self.account.address,
            "nonce": self.w3.eth.get_transaction_count(self.account.address, "latest"),
            "chainId": self.chain_id,
        })
        bump = 1.25 ** attempt
        for key in ("maxFeePerGas", "maxPriorityFeePerGas", "gasPrice"):
            if key in tx:
                tx[key] = int(tx[key] * bump)
        signed = self.account.sign_transaction(tx)
        return _hex(self.w3.eth.send_raw_transaction(signed.raw_transaction))

    def wait_receipt(self, tx_hash: str, timeout: int = RECEIPT_TIMEOUT_SECONDS) -> dict:
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
        if receipt["status"] != 1:
            raise ChainError(f"anchor tx {tx_hash} reverted")
        return {"tx_hash": _hex(tx_hash), "block_number": receipt["blockNumber"]}

    def find_anchor_tx(self, batch_id: int, lookback_blocks: int = 10_000) -> Optional[dict]:
        """Recovers the tx for a batch from the Anchored event (batchId is indexed) — used when
        we crashed after broadcasting but before saving the tx hash."""
        latest = self.w3.eth.block_number
        logs = self.contract.events.Anchored.get_logs(
            argument_filters={"batchId": batch_id},
            from_block=max(0, latest - lookback_blocks), to_block=latest,
        )
        if not logs:
            return None
        return {"tx_hash": _hex(logs[0]["transactionHash"]), "block_number": logs[0]["blockNumber"]}

    def confirmations(self, block_number: int) -> int:
        return self.w3.eth.block_number - block_number + 1

    def tx_url(self, tx_hash: Optional[str]) -> Optional[str]:
        return f"{self.explorer_url}/tx/{tx_hash}" if self.explorer_url and tx_hash else None

    def status(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "latest_block": self.w3.eth.block_number,
            "last_batch_id": self.last_batch_id(),
            "contract_address": self.address,
            "signer_address": self.account.address,
            "signer_balance_wei": str(self.w3.eth.get_balance(self.account.address)),
            "explorer_url": self.explorer_url or None,
            "contract_url": f"{self.explorer_url}/address/{self.address}" if self.explorer_url else None,
        }


def _hex(value) -> str:
    text = value.hex() if hasattr(value, "hex") else str(value)
    return text if text.startswith("0x") else "0x" + text


def from_env() -> Optional[Chain]:
    """The configured chain, or None when CHAIN_RPC_URL is blank (ledger off). A set-but-broken
    config raises — misconfiguration must be loud, not a silently unanchored audit trail."""
    rpc = os.environ.get("CHAIN_RPC_URL", "").strip()
    if not rpc:
        logger.warning("CHAIN_RPC_URL not set — blockchain anchoring DISABLED; decisions are stored but not anchored.")
        return None
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 15}))
    if not w3.is_connected():
        raise ChainError(f"cannot reach chain RPC at {rpc}")
    return Chain(
        w3,
        os.environ.get("ANCHOR_CONTRACT_ADDRESS", "").strip(),
        os.environ.get("ANCHOR_PRIVATE_KEY", "").strip(),
        os.environ.get("CHAIN_EXPLORER_URL", "").strip(),
    )
