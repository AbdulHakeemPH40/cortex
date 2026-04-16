"""
ConfigTool supported settings registry.

Defines all configurable settings with their types, sources, validation, and options.
"""

import os
from typing import Any, Callable, Dict, List, Optional, TypedDict


# Defensive imports
try:
    from ...utils.config import getRemoteControlAtStartup
except ImportError:
    def getRemoteControlAtStartup():
        return False

try:
    from ...utils.configConstants import EDITOR_MODES, NOTIFICATION_CHANNELS, TEAMMATE_MODES
except ImportError:
    EDITOR_MODES = ['default', 'vim', 'emacs']
    NOTIFICATION_CHANNELS = ['terminal', 'desktop', 'mobile']
    TEAMMATE_MODES = ['tmux', 'in-process', 'auto']

try:
    from ...utils.model.modelOptions import getModelOptions
except ImportError:
    def getModelOptions():
        return [
            {'value': 'sonnet', 'description': 'Claude 3.5 Sonnet'},
            {'value': 'opus', 'description': 'Claude 3 Opus'},
            {'value': 'haiku', 'description': 'Claude 3 Haiku'},
        ]

try:
    from ...utils.model.validateModel import validateModel
except ImportError:
    async def validateModel(model_name):
        return {'valid': True}

try:
    from ...utils.theme import THEME_NAMES, THEME_SETTINGS
except ImportError:
    THEME_NAMES = ['dark', 'light', 'system']
    THEME_SETTINGS = ['dark', 'light', 'system', 'auto']


class SettingValidationResult(TypedDict):
    """Result of setting validation."""
    valid: bool
    error: Optional[str]


class SettingConfig(TypedDict, total=False):
    """Configuration for a single setting."""
    source: str  # 'global' or 'settings'
    type: str  # 'boolean' or 'string'
    description: str
    path: Optional[List[str]]
    options: Optional[List[str]]
    getOptions: Optional[Callable[[], List[str]]]
    appStateKey: Optional[str]
    validateOnWrite: Optional[Callable[[Any], Any]]  # Returns coroutine
    formatOnRead: Optional[Callable[[Any], Any]]


# AppState keys that can be synced for immediate UI effect
SyncableAppStateKey = str  # 'verbose' | 'mainLoopModel' | 'thinkingEnabled'


def buildSupportedSettings() -> Dict[str, SettingConfig]:
    """Build the supported settings dictionary dynamically based on feature flags."""
    settings: Dict[str, SettingConfig] = {
        'theme': {
            'source': 'global',
            'type': 'string',
            'description': 'Color theme for the UI',
            'options': THEME_SETTINGS if os.environ.get('AUTO_THEME', '').lower() in ('true', '1', 'yes') else THEME_NAMES,
        },
        'editorMode': {
            'source': 'global',
            'type': 'string',
            'description': 'Key binding mode',
            'options': EDITOR_MODES,
        },
        'verbose': {
            'source': 'global',
            'type': 'boolean',
            'description': 'Show detailed debug output',
            'appStateKey': 'verbose',
        },
        'preferredNotifChannel': {
            'source': 'global',
            'type': 'string',
            'description': 'Preferred notification channel',
            'options': NOTIFICATION_CHANNELS,
        },
        'autoCompactEnabled': {
            'source': 'global',
            'type': 'boolean',
            'description': 'Auto-compact when context is full',
        },
        'autoMemoryEnabled': {
            'source': 'settings',
            'type': 'boolean',
            'description': 'Enable auto-memory',
        },
        'autoDreamEnabled': {
            'source': 'settings',
            'type': 'boolean',
            'description': 'Enable background memory consolidation',
        },
        'fileCheckpointingEnabled': {
            'source': 'global',
            'type': 'boolean',
            'description': 'Enable file checkpointing for code rewind',
        },
        'showTurnDuration': {
            'source': 'global',
            'type': 'boolean',
            'description': 'Show turn duration message after responses (e.g., "Cooked for 1m 6s")',
        },
        'terminalProgressBarEnabled': {
            'source': 'global',
            'type': 'boolean',
            'description': 'Show OSC 9;4 progress indicator in supported terminals',
        },
        'todoFeatureEnabled': {
            'source': 'global',
            'type': 'boolean',
            'description': 'Enable todo/task tracking',
        },
        'model': {
            'source': 'settings',
            'type': 'string',
            'description': 'Override the default model',
            'appStateKey': 'mainLoopModel',
            'getOptions': lambda: [
                o['value'] for o in getModelOptions() if o.get('value') is not None
            ],
            'validateOnWrite': lambda v: validateModel(str(v)),
            'formatOnRead': lambda v: 'default' if v is None else v,
        },
        'alwaysThinkingEnabled': {
            'source': 'settings',
            'type': 'boolean',
            'description': 'Enable extended thinking (false to disable)',
            'appStateKey': 'thinkingEnabled',
        },
        'permissions.defaultMode': {
            'source': 'settings',
            'type': 'string',
            'description': 'Default permission mode for tool usage',
            'options': ['default', 'plan', 'acceptEdits', 'dontAsk', 'auto'] if os.environ.get('TRANSCRIPT_CLASSIFIER', '').lower() in ('true', '1', 'yes') else ['default', 'plan', 'acceptEdits', 'dontAsk'],
        },
        'language': {
            'source': 'settings',
            'type': 'string',
            'description': 'Preferred language for Claude responses and voice dictation (e.g., "japanese", "spanish")',
        },
        'teammateMode': {
            'source': 'global',
            'type': 'string',
            'description': 'How to spawn teammates: "tmux" for traditional tmux, "in-process" for same process, "auto" to choose automatically',
            'options': TEAMMATE_MODES,
        },
    }
    
    # Add ant-specific settings
    if os.environ.get('USER_TYPE') == 'ant':
        settings['classifierPermissionsEnabled'] = {
            'source': 'settings',
            'type': 'boolean',
            'description': 'Enable AI-based classification for Bash(prompt:...) permission rules',
        }
    
    # Add voice mode settings
    if os.environ.get('VOICE_MODE', '').lower() in ('true', '1', 'yes'):
        settings['voiceEnabled'] = {
            'source': 'settings',
            'type': 'boolean',
            'description': 'Enable voice dictation (hold-to-talk)',
        }
    
    # Add bridge mode settings
    if os.environ.get('BRIDGE_MODE', '').lower() in ('true', '1', 'yes'):
        settings['remoteControlAtStartup'] = {
            'source': 'global',
            'type': 'boolean',
            'description': 'Enable Remote Control for all sessions (true | false | default)',
            'formatOnRead': lambda v: getRemoteControlAtStartup(),
        }
    
    # Add Kairos/push notification settings
    if (os.environ.get('KAIROS', '').lower() in ('true', '1', 'yes') or
        os.environ.get('KAIROS_PUSH_NOTIFICATION', '').lower() in ('true', '1', 'yes')):
        settings.update({
            'taskCompleteNotifEnabled': {
                'source': 'global',
                'type': 'boolean',
                'description': 'Push to your mobile device when idle after Claude finishes (requires Remote Control)',
            },
            'inputNeededNotifEnabled': {
                'source': 'global',
                'type': 'boolean',
                'description': 'Push to your mobile device when a permission prompt or question is waiting (requires Remote Control)',
            },
            'agentPushNotifEnabled': {
                'source': 'global',
                'type': 'boolean',
                'description': 'Allow Claude to push to your mobile device when it deems it appropriate (requires Remote Control)',
            },
        })
    
    return settings


# Build settings once at module load
SUPPORTED_SETTINGS = buildSupportedSettings()


def isSupported(key: str) -> bool:
    """Check if a setting key is supported."""
    return key in SUPPORTED_SETTINGS


def getConfig(key: str) -> Optional[SettingConfig]:
    """Get configuration for a setting."""
    return SUPPORTED_SETTINGS.get(key)


def getAllKeys() -> List[str]:
    """Get all supported setting keys."""
    return list(SUPPORTED_SETTINGS.keys())


def getOptionsForSetting(key: str) -> Optional[List[str]]:
    """Get available options for a setting."""
    config = SUPPORTED_SETTINGS.get(key)
    if not config:
        return None
    
    if 'options' in config:
        return list(config['options'])
    
    if 'getOptions' in config and callable(config['getOptions']):
        return config['getOptions']()
    
    return None


def getPath(key: str) -> List[str]:
    """Get the path for a setting (for nested settings)."""
    config = SUPPORTED_SETTINGS.get(key)
    if config and 'path' in config:
        return config['path']
    return key.split('.')
