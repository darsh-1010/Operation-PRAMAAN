"""One-time deploy of contracts/PramanAnchor.json to the chain in CHAIN_RPC_URL, signed by
ANCHOR_PRIVATE_KEY (which becomes the contract owner — the only account allowed to anchor).
Prints the address to put in ANCHOR_CONTRACT_ADDRESS. Idempotent: does nothing if a contract
already exists at ANCHOR_CONTRACT_ADDRESS, so docker-compose can run it on every `up`.

    python deploy_contract.py --deploy        # real chains need --deploy; local Anvil doesn't
    docker compose run --rm risk-scoring-engine python deploy_contract.py

Deploying again creates a NEW, empty contract: every earlier anchor stays verifiable only
against the old address. Don't redeploy once real decisions have been anchored.
"""
import os
import sys

from web3 import Web3

from chain import ARTIFACT, _DEV_CHAIN_ID, _PUBLIC_DEV_KEY


def main() -> None:
    rpc = os.environ.get("CHAIN_RPC_URL", "").strip()
    key = os.environ.get("ANCHOR_PRIVATE_KEY", "").strip()
    if not rpc or not key:
        sys.exit("Set CHAIN_RPC_URL and ANCHOR_PRIVATE_KEY first (see .env.example).")
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        sys.exit(f"Cannot reach {rpc}")
    if key.lower() == _PUBLIC_DEV_KEY and w3.eth.chain_id != _DEV_CHAIN_ID:
        sys.exit("Refusing to deploy with the public Anvil dev key on a non-dev chain.")

    existing = os.environ.get("ANCHOR_CONTRACT_ADDRESS", "").strip()
    if existing and w3.eth.get_code(Web3.to_checksum_address(existing)):
        print(f"PramanAnchor already deployed at {existing} — nothing to do.")
        return
    if w3.eth.chain_id != _DEV_CHAIN_ID and "--deploy" not in sys.argv:
        # docker-compose runs this on every `up`; on a real chain, never auto-create contracts.
        print(f"No contract at ANCHOR_CONTRACT_ADDRESS on chain {w3.eth.chain_id}. "
              "Run `python deploy_contract.py --deploy` once, by hand, to create it.")
        return

    account = w3.eth.account.from_key(key)
    print(f"chain {w3.eth.chain_id}, deployer {account.address}, balance {w3.from_wei(w3.eth.get_balance(account.address), 'ether')}")
    factory = w3.eth.contract(abi=ARTIFACT["abi"], bytecode=ARTIFACT["bytecode"])
    tx = factory.constructor().build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address, "latest"),
        "chainId": w3.eth.chain_id,
    })
    tx_hash = w3.eth.send_raw_transaction(account.sign_transaction(tx).raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    if receipt["status"] != 1:
        sys.exit(f"Deploy reverted: {tx_hash.hex()}")
    print(f"PramanAnchor deployed at block {receipt['blockNumber']}")
    print(f"ANCHOR_CONTRACT_ADDRESS={receipt['contractAddress']}")
    if existing and existing.lower() != receipt["contractAddress"].lower():
        print(f"WARNING: .env points at {existing} — update ANCHOR_CONTRACT_ADDRESS to the address above.")


if __name__ == "__main__":
    main()
