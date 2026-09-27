// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @title PRAMAN decision anchor
/// @notice Append-only registry of Merkle roots over batches of screening decisions.
///         Only 32-byte roots go on-chain, never personal data (see ../LEDGER.md).
///         Batch ids must be strictly sequential, so a batch can never be re-anchored with a
///         different root and a missing batch shows up as a gap.
///         Compiled output lives in PramanAnchor.json (solc 0.8.26, --optimize).
contract PramanAnchor {
    address public immutable owner;
    uint64 public lastBatchId;

    struct Anchor {
        bytes32 root;
        uint32 leafCount;
        uint64 timestamp;
    }

    mapping(uint64 => Anchor) private batches;
    mapping(bytes32 => uint64) public batchOfRoot;

    event Anchored(uint64 indexed batchId, bytes32 indexed root, uint32 leafCount, uint64 timestamp);

    constructor() {
        owner = msg.sender;
    }

    function anchor(uint64 batchId, bytes32 root, uint32 leafCount) external {
        require(msg.sender == owner, "not owner");
        require(batchId == lastBatchId + 1, "batch id out of sequence");
        require(leafCount > 0, "empty batch");
        require(root != bytes32(0), "zero root");
        require(batchOfRoot[root] == 0, "root already anchored");
        lastBatchId = batchId;
        batches[batchId] = Anchor(root, leafCount, uint64(block.timestamp));
        batchOfRoot[root] = batchId;
        emit Anchored(batchId, root, leafCount, uint64(block.timestamp));
    }

    /// @return root, leafCount, timestamp (timestamp == 0 means batch not anchored)
    function getBatch(uint64 batchId) external view returns (bytes32, uint32, uint64) {
        Anchor memory a = batches[batchId];
        return (a.root, a.leafCount, a.timestamp);
    }
}
