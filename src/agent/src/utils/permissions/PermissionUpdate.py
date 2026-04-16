"""
Permission update orchestration for Cortex AI Agent IDE.

Applies and persists permission updates to context and settings.
Coordinates between in-memory context and disk persistence.

Multi-LLM Support: Works with all providers as it's provider-agnostic
permission update management.

Features:
- Apply updates to permission context (in-memory)
- Persist updates to settings files (disk)
- Extract rules from update lists
- Create rule suggestions for directories

Example:
    >>> from PermissionUpdate import apply_permission_update
    >>> update = PermissionUpdateAddRules(...)
    >>> new_context = apply_permission_update(context, update)
"""

import json
import logging
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from .PermissionUpdateSchema import (
    PermissionUpdate,
    PermissionUpdateDestination,
    PermissionUpdateAddRules,
)
from .permissionRuleParser import (
    permission_rule_value_from_string,
    permission_rule_value_to_string,
)
from .permissionsLoader import (
    add_permission_rules_to_settings,
    get_settings_for_source,
    update_settings_for_source,
    EditableSettingSource,
)

if TYPE_CHECKING:
    pass  # Type checking imports are handled above


# ============================================================================
# Rule Extraction
# ============================================================================

def extract_rules(updates: list[PermissionUpdate] | None) -> list[PermissionRuleValue]:
    """
    Extracts all rule values from permission updates.
    
    Args:
        updates: List of permission updates
        
    Returns:
        List of PermissionRuleValue objects
    """
    if not updates:
        return []
    
    all_rules: list[PermissionRuleValue] = []
    
    for update in updates:
        if update.type == 'addRules':
            all_rules.extend(update.rules)
    
    return all_rules


def has_rules(updates: list[PermissionUpdate] | None) -> bool:
    """
    Checks if updates contain any rules.
    
    Args:
        updates: List of permission updates
        
    Returns:
        True if updates contain rules
    """
    return len(extract_rules(updates)) > 0


# ============================================================================
# Update Application
# ============================================================================

def apply_permission_update(
    context: 'ToolPermissionContext',
    update: PermissionUpdate,
) -> 'ToolPermissionContext':
    """
    Applies a single permission update to the context.
    
    Args:
        context: Current permission context
        update: Permission update to apply
        
    Returns:
        Updated permission context
    """
    if update.type == 'setMode':
        logging.debug(f"Applying permission update: Setting mode to '{update.mode.value}'")
        return {
            **context,
            'mode': update.mode,
        }
    
    elif update.type == 'addRules':
        rule_strings = [
            permission_rule_value_to_string(rule)
            for rule in update.rules
        ]
        logging.debug(
            f"Applying permission update: Adding {len(update.rules)} "
            f"{update.behavior} rule(s) to destination '{update.destination}': "
            f"{json.dumps(rule_strings)}"
        )
        
        # Determine which collection to update
        rule_kind = (
            'alwaysAllowRules'
            if update.behavior == 'allow'
            else 'alwaysDenyRules'
            if update.behavior == 'deny'
            else 'alwaysAskRules'
        )
        
        existing_rules = context.get(rule_kind, {})
        destination_rules = existing_rules.get(update.destination, [])
        
        return {
            **context,
            rule_kind: {
                **existing_rules,
                update.destination: [*destination_rules, *rule_strings],
            },
        }
    
    elif update.type == 'replaceRules':
        rule_strings = [
            permission_rule_value_to_string(rule)
            for rule in update.rules
        ]
        logging.debug(
            f"Replacing all {update.behavior} rules for destination "
            f"'{update.destination}' with {len(update.rules)} rule(s): "
            f"{json.dumps(rule_strings)}"
        )
        
        # Determine which collection to update
        rule_kind = (
            'alwaysAllowRules'
            if update.behavior == 'allow'
            else 'alwaysDenyRules'
            if update.behavior == 'deny'
            else 'alwaysAskRules'
        )
        
        existing_rules = context.get(rule_kind, {})
        
        return {
            **context,
            rule_kind: {
                **existing_rules,
                update.destination: rule_strings,
            },
        }
    
    elif update.type == 'addDirectories':
        dir_word = 'directory' if len(update.directories) == 1 else 'directories'
        logging.debug(
            f"Applying permission update: Adding {len(update.directories)} "
            f"{dir_word} with destination '{update.destination}': "
            f"{json.dumps(update.directories)}"
        )
        
        new_dirs = dict(context.get('additionalWorkingDirectories', {}))
        for directory in update.directories:
            new_dirs[directory] = {
                'path': directory,
                'source': update.destination,
            }
        
        return {
            **context,
            'additionalWorkingDirectories': new_dirs,
        }
    
    elif update.type == 'removeRules':
        rule_strings = [
            permission_rule_value_to_string(rule)
            for rule in update.rules
        ]
        logging.debug(
            f"Applying permission update: Removing {len(update.rules)} "
            f"{update.behavior} rule(s) from source '{update.destination}': "
            f"{json.dumps(rule_strings)}"
        )
        
        # Determine which collection to update
        rule_kind = (
            'alwaysAllowRules'
            if update.behavior == 'allow'
            else 'alwaysDenyRules'
            if update.behavior == 'deny'
            else 'alwaysAskRules'
        )
        
        existing_rules = context.get(rule_kind, {})
        destination_rules = existing_rules.get(update.destination, [])
        rules_to_remove = set(rule_strings)
        
        filtered_rules = [
            rule for rule in destination_rules
            if rule not in rules_to_remove
        ]
        
        return {
            **context,
            rule_kind: {
                **existing_rules,
                update.destination: filtered_rules,
            },
        }
    
    elif update.type == 'removeDirectories':
        dir_word = 'directory' if len(update.directories) == 1 else 'directories'
        logging.debug(
            f"Applying permission update: Removing {len(update.directories)} "
            f"{dir_word}: {json.dumps(update.directories)}"
        )
        
        new_dirs = dict(context.get('additionalWorkingDirectories', {}))
        for directory in update.directories:
            new_dirs.pop(directory, None)
        
        return {
            **context,
            'additionalWorkingDirectories': new_dirs,
        }
    
    # Unknown update type
    return context


def apply_permission_updates(
    context: 'ToolPermissionContext',
    updates: list[PermissionUpdate],
) -> 'ToolPermissionContext':
    """
    Applies multiple permission updates to the context.
    
    Args:
        context: Current permission context
        updates: Permission updates to apply
        
    Returns:
        Updated permission context
    """
    updated_context = context
    
    for update in updates:
        updated_context = apply_permission_update(updated_context, update)
    
    return updated_context


# ============================================================================
# Persistence Support
# ============================================================================

def supports_persistence(
    destination: PermissionUpdateDestination,
) -> bool:
    """
    Checks if destination supports persistence.
    
    Args:
        destination: Update destination
        
    Returns:
        True if destination can persist to disk
    """
    return destination in (
        'localSettings',
        'userSettings',
        'projectSettings',
    )


def persist_permission_update(update: PermissionUpdate) -> None:
    """
    Persists a permission update to the appropriate settings source.
    
    Args:
        update: Permission update to persist
    """
    if not supports_persistence(update.destination):
        return
    
    logging.debug(
        f"Persisting permission update: {update.type} to source '{update.destination}'"
    )
    
    if update.type == 'addRules':
        logging.debug(
            f"Persisting {len(update.rules)} {update.behavior} "
            f"rule(s) to {update.destination}"
        )
        add_permission_rules_to_settings(
            rule_values=update.rules,
            rule_behavior=update.behavior,
            source=update.destination,
        )
    
    elif update.type == 'addDirectories':
        dir_word = 'directory' if len(update.directories) == 1 else 'directories'
        logging.debug(
            f"Persisting {len(update.directories)} {dir_word} to {update.destination}"
        )
        
        existing_settings = get_settings_for_source(update.destination)
        existing_dirs = (
            existing_settings.get('permissions', {}).get('additionalDirectories', [])
            if existing_settings else []
        )
        
        # Add new directories, avoiding duplicates
        dirs_to_add = [
            d for d in update.directories
            if d not in existing_dirs
        ]
        
        if dirs_to_add:
            updated_dirs = [*existing_dirs, *dirs_to_add]
            update_settings_for_source(
                update.destination,
                {'permissions': {'additionalDirectories': updated_dirs}},
            )
    
    elif update.type == 'removeRules':
        logging.debug(
            f"Removing {len(update.rules)} {update.behavior} "
            f"rule(s) from {update.destination}"
        )
        
        existing_settings = get_settings_for_source(update.destination)
        existing_permissions = (
            existing_settings.get('permissions', {})
            if existing_settings else {}
        )
        existing_rules = existing_permissions.get(update.behavior, [])
        
        # Convert rules to normalized strings for comparison
        rules_to_remove = {
            permission_rule_value_to_string(rule)
            for rule in update.rules
        }
        
        filtered_rules = [
            rule for rule in existing_rules
            if permission_rule_value_to_string(
                permission_rule_value_from_string(rule)
            ) not in rules_to_remove
        ]
        
        update_settings_for_source(
            update.destination,
            {'permissions': {update.behavior: filtered_rules}},
        )
    
    elif update.type == 'removeDirectories':
        dir_word = 'directory' if len(update.directories) == 1 else 'directories'
        logging.debug(
            f"Removing {len(update.directories)} {dir_word} from {update.destination}"
        )
        
        existing_settings = get_settings_for_source(update.destination)
        existing_dirs = (
            existing_settings.get('permissions', {}).get('additionalDirectories', [])
            if existing_settings else []
        )
        
        dirs_to_remove = set(update.directories)
        filtered_dirs = [
            d for d in existing_dirs
            if d not in dirs_to_remove
        ]
        
        update_settings_for_source(
            update.destination,
            {'permissions': {'additionalDirectories': filtered_dirs}},
        )
    
    elif update.type == 'setMode':
        logging.debug(
            f"Persisting mode '{update.mode.value}' to {update.destination}"
        )
        update_settings_for_source(
            update.destination,
            {'permissions': {'defaultMode': update.mode.value}},
        )
    
    elif update.type == 'replaceRules':
        logging.debug(
            f"Replacing all {update.behavior} rules in {update.destination} "
            f"with {len(update.rules)} rule(s)"
        )
        
        rule_strings = [
            permission_rule_value_to_string(rule)
            for rule in update.rules
        ]
        
        update_settings_for_source(
            update.destination,
            {'permissions': {update.behavior: rule_strings}},
        )


def persist_permission_updates(updates: list[PermissionUpdate]) -> None:
    """
    Persists multiple permission updates to settings sources.
    Only persists updates with persistable sources.
    
    Args:
        updates: Permission updates to persist
    """
    for update in updates:
        persist_permission_update(update)


# ============================================================================
# Rule Suggestions
# ============================================================================

def create_read_rule_suggestion(
    dir_path: str,
    destination: PermissionUpdateDestination = 'session',
) -> PermissionUpdate | None:
    """
    Creates a Read rule suggestion for a directory.
    
    Args:
        dir_path: Directory path to create rule for
        destination: Destination for the rule (defaults to 'session')
        
    Returns:
        PermissionUpdate for a Read rule, or None for root directory
    """
    # Convert to POSIX format
    path_for_pattern = PurePosixPath(dir_path)
    path_str = str(path_for_pattern)
    
    # Root directory is too broad
    if path_str == '/' or path_str == '.':
        return None
    
    # For absolute paths, prepend extra / to create //path/** pattern
    if path_for_pattern.is_absolute():
        rule_content = f'/{path_str}/**'
    else:
        rule_content = f'{path_str}/**'
    
    return PermissionUpdateAddRules(
        type='addRules',
        rules=[
            PermissionRuleValue(
                tool_name='Read',
                rule_content=rule_content,
            )
        ],
        behavior='allow',
        destination=destination,
    )


# ============================================================================
# Exported Symbols
# ============================================================================

__all__ = [
    'extract_rules',
    'has_rules',
    'apply_permission_update',
    'apply_permission_updates',
    'supports_persistence',
    'persist_permission_update',
    'persist_permission_updates',
    'create_read_rule_suggestion',
]
