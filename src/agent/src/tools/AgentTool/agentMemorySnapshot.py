# agent_memory_snapshot.py
"""
Agent Memory Snapshot - Snapshot management for Cortex IDE agent memory.

Handles snapshot creation, synchronization, and initialization for agent memory.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import TypedDict, Literal, Optional

from .agentMemory import AgentMemoryScope, get_agent_memory_dir


SNAPSHOT_BASE = "agent-memory-snapshots"
SNAPSHOT_JSON = "snapshot.json"
SYNCED_JSON = ".snapshot-synced.json"


class SnapshotMeta(TypedDict):
    """Snapshot metadata schema."""
    updatedAt: str


class SyncedMeta(TypedDict):
    """Synced metadata schema."""
    syncedFrom: str


def get_snapshot_dir_for_agent(agent_type: str) -> str:
    """
    Returns the path to the snapshot directory for an agent in the current project.
    e.g., <cwd>/.cortex/agent-memory-snapshots/<agentType>/
    """
    return str(Path(get_cwd(), ".cortex", SNAPSHOT_BASE, agent_type))


def get_snapshot_json_path(agent_type: str) -> str:
    """Get path to snapshot JSON file."""
    return str(Path(get_snapshot_dir_for_agent(agent_type), SNAPSHOT_JSON))


def get_synced_json_path(agent_type: str, scope: AgentMemoryScope) -> str:
    """Get path to synced JSON file."""
    return str(Path(get_agent_memory_dir(agent_type, scope), SYNCED_JSON))


async def read_json_file(
    path: str,
    schema_type: str,
) -> dict | None:
    """
    Read and parse a JSON file with schema validation.
    Returns None if file doesn't exist or parsing fails.
    """
    try:
        content = await asyncio.to_thread(Path(path).read_text, encoding="utf-8")
        data = json_parse(content)
        
        # Basic schema validation (simplified from Zod)
        if schema_type == "snapshot_meta":
            if isinstance(data, dict) and "updatedAt" in data and isinstance(data["updatedAt"], str):
                return data
        elif schema_type == "synced_meta":
            if isinstance(data, dict) and "syncedFrom" in data and isinstance(data["syncedFrom"], str):
                return data
        
        return None
    except Exception:
        return None


async def copy_snapshot_to_local(
    agent_type: str,
    scope: AgentMemoryScope,
) -> None:
    """Copy snapshot files to local agent memory directory."""
    snapshot_mem_dir = Path(get_snapshot_dir_for_agent(agent_type))
    local_mem_dir = Path(get_agent_memory_dir(agent_type, scope))
    
    local_mem_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        files = await asyncio.to_thread(lambda: list(snapshot_mem_dir.iterdir()))
        for file_path in files:
            if not file_path.is_file() or file_path.name == SNAPSHOT_JSON:
                continue
            
            content = await asyncio.to_thread(file_path.read_text, encoding="utf-8")
            target_path = local_mem_dir / file_path.name
            await asyncio.to_thread(target_path.write_text, content, encoding="utf-8")
    except Exception as e:
        log_for_debugging(f"Failed to copy snapshot to local agent memory: {e}")


async def save_synced_meta(
    agent_type: str,
    scope: AgentMemoryScope,
    snapshot_timestamp: str,
) -> None:
    """Save synchronization metadata."""
    synced_path = Path(get_synced_json_path(agent_type, scope))
    local_mem_dir = Path(get_agent_memory_dir(agent_type, scope))
    
    local_mem_dir.mkdir(parents=True, exist_ok=True)
    
    meta: SyncedMeta = {"syncedFrom": snapshot_timestamp}
    
    try:
        await asyncio.to_thread(
            synced_path.write_text, 
            json_stringify(meta),
            encoding="utf-8"
        )
    except Exception as e:
        log_for_debugging(f"Failed to save snapshot sync metadata: {e}")


class CheckResult(TypedDict, total=False):
    """Result type for check_agent_memory_snapshot."""
    action: Literal["none", "initialize", "prompt-update"]
    snapshotTimestamp: Optional[str]


async def check_agent_memory_snapshot(
    agent_type: str,
    scope: AgentMemoryScope,
) -> CheckResult:
    """
    Check if a snapshot exists and whether it's newer than what we last synced.
    
    Returns:
        - action: 'none' - no snapshot or already synced
        - action: 'initialize' - first-time setup needed
        - action: 'prompt-update' - snapshot is newer than local
    """
    snapshot_meta = await read_json_file(
        get_snapshot_json_path(agent_type),
        "snapshot_meta",
    )
    
    if not snapshot_meta:
        return {"action": "none"}
    
    local_mem_dir = Path(get_agent_memory_dir(agent_type, scope))
    
    # Check if local memory exists
    has_local_memory = False
    try:
        dirents = await asyncio.to_thread(lambda: list(local_mem_dir.iterdir()))
        has_local_memory = any(
            d.is_file() and d.name.endswith(".md") 
            for d in dirents
        )
    except FileNotFoundError:
        # Directory doesn't exist
        pass
    
    if not has_local_memory:
        return {
            "action": "initialize",
            "snapshotTimestamp": snapshot_meta["updatedAt"]
        }
    
    # Check if snapshot is newer than last synced
    synced_meta = await read_json_file(
        get_synced_json_path(agent_type, scope),
        "synced_meta",
    )
    
    if (
        not synced_meta
        or datetime.fromisoformat(snapshot_meta["updatedAt"]) 
           > datetime.fromisoformat(synced_meta["syncedFrom"])
    ):
        return {
            "action": "prompt-update",
            "snapshotTimestamp": snapshot_meta["updatedAt"],
        }
    
    return {"action": "none"}


async def initialize_from_snapshot(
    agent_type: str,
    scope: AgentMemoryScope,
    snapshot_timestamp: str,
) -> None:
    """
    Initialize local agent memory from a snapshot (first-time setup).
    """
    log_for_debugging(
        f"Initializing agent memory for {agent_type} from project snapshot"
    )
    await copy_snapshot_to_local(agent_type, scope)
    await save_synced_meta(agent_type, scope, snapshot_timestamp)


async def replace_from_snapshot(
    agent_type: str,
    scope: AgentMemoryScope,
    snapshot_timestamp: str,
) -> None:
    """
    Replace local agent memory with the snapshot.
    Removes existing .md files before copying to avoid orphans.
    """
    log_for_debugging(
        f"Replacing agent memory for {agent_type} with project snapshot"
    )
    
    local_mem_dir = Path(get_agent_memory_dir(agent_type, scope))
    
    # Remove existing .md files
    try:
        existing = await asyncio.to_thread(lambda: list(local_mem_dir.iterdir()))
        for file_path in existing:
            if file_path.is_file() and file_path.name.endswith(".md"):
                await asyncio.to_thread(file_path.unlink)
    except FileNotFoundError:
        # Directory may not exist yet
        pass
    
    await copy_snapshot_to_local(agent_type, scope)
    await save_synced_meta(agent_type, scope, snapshot_timestamp)


async def mark_snapshot_synced(
    agent_type: str,
    scope: AgentMemoryScope,
    snapshot_timestamp: str,
) -> None:
    """
    Mark the current snapshot as synced without changing local memory.
    """
    await save_synced_meta(agent_type, scope, snapshot_timestamp)
