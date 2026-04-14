"""
ConfigTool - Get or set Claude Code configuration settings.

Allows the AI agent to read and modify user settings like theme, model,
permissions, and other preferences.
"""

import os
from typing import Any, Dict, Optional, TypedDict

# Defensive imports
try:
    from ...services.analytics.index import logEvent
except ImportError:
    def logEvent(event_name, properties=None):
        pass

try:
    from ...Tool import buildTool, ToolDef, ValidationResult
except ImportError:
    class ValidationResult(TypedDict, total=False):
        result: bool
        message: str
        errorCode: int
    
    def buildTool(**kwargs):
        return kwargs

try:
    from ...utils.config import getGlobalConfig, saveGlobalConfig, getRemoteControlAtStartup
except ImportError:
    def getGlobalConfig():
        return {}
    
    def saveGlobalConfig(update_fn):
        pass
    
    def getRemoteControlAtStartup():
        return False

try:
    from ...utils.errors import errorMessage
except ImportError:
    def errorMessage(error):
        return str(error)

try:
    from ...utils.log import logError
except ImportError:
    def logError(error):
        print(f"Error: {error}")

try:
    from ...utils.settings.settings import getInitialSettings, updateSettingsForSource
except ImportError:
    def getInitialSettings():
        return {}
    
    def updateSettingsForSource(source, update):
        return {'error': None}

try:
    from ...utils.slowOperations import jsonStringify
except ImportError:
    import json
    def jsonStringify(obj, **kwargs):
        return json.dumps(obj, default=str, **kwargs)

try:
    from .constants import CONFIG_TOOL_NAME
except ImportError:
    CONFIG_TOOL_NAME = 'Config'

try:
    from .prompt import DESCRIPTION, generatePrompt
except ImportError:
    DESCRIPTION = 'Get or set Claude Code configuration settings.'
    
    def generatePrompt():
        return DESCRIPTION

try:
    from .supportedSettings import (
        getConfig,
        getOptionsForSetting,
        getPath,
        isSupported,
        SUPPORTED_SETTINGS,
    )
except ImportError:
    SUPPORTED_SETTINGS = {}
    
    def isSupported(key):
        return key in SUPPORTED_SETTINGS
    
    def getConfig(key):
        return SUPPORTED_SETTINGS.get(key)
    
    def getPath(key):
        config = getConfig(key)
        return config.get('path', key.split('.')) if config else key.split('.')
    
    def getOptionsForSetting(key):
        config = getConfig(key)
        if not config:
            return None
        if 'options' in config:
            return list(config['options'])
        if 'getOptions' in config and callable(config['getOptions']):
            return config['getOptions']()
        return None

try:
    from .UI import renderToolResultMessage, renderToolUseMessage, renderToolUseRejectedMessage
except ImportError:
    def renderToolUseMessage(*args, **kwargs):
        return ''
    
    def renderToolResultMessage(*args, **kwargs):
        return ''
    
    def renderToolUseRejectedMessage(*args, **kwargs):
        return ''


class Input(TypedDict, total=False):
    """Input schema for ConfigTool."""
    setting: str
    value: Optional[Any]


class Output(TypedDict, total=False):
    """Output schema for ConfigTool."""
    success: bool
    operation: Optional[str]  # 'get' or 'set'
    setting: Optional[str]
    value: Optional[Any]
    previousValue: Optional[Any]
    newValue: Optional[Any]
    error: Optional[str]


def getValue(source: str, path: list) -> Any:
    """Get value from config source by path."""
    if source == 'global':
        config = getGlobalConfig()
        key = path[0] if path else None
        if not key:
            return None
        return config.get(key)
    
    # Settings source
    settings = getInitialSettings()
    current = settings
    for key in path:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def buildNestedObject(path: list, value: Any) -> dict:
    """Build nested object from path and value."""
    if len(path) == 0:
        return {}
    
    key = path[0]
    if len(path) == 1:
        return {key: value}
    
    return {key: buildNestedObject(path[1:], value)}


async def checkPermissions(input_data: Input):
    """Check permissions for config operations."""
    # Auto-allow reading configs
    if input_data.get('value') is None:
        return {'behavior': 'allow', 'updatedInput': input_data}
    
    return {
        'behavior': 'ask',
        'message': f'Set {input_data["setting"]} to {jsonStringify(input_data["value"])}',
    }


def isReadOnly(input_data: Input) -> bool:
    """Check if operation is read-only (get vs set)."""
    return input_data.get('value') is None


def toAutoClassifierInput(input_data: Input) -> str:
    """Convert input to auto-classifier format."""
    if input_data.get('value') is None:
        return input_data['setting']
    return f'{input_data["setting"]} = {input_data["value"]}'


async def call(input_data: Input, context) -> Dict[str, Any]:
    """Execute ConfigTool - get or set configuration settings."""
    setting = input_data['setting']
    value = input_data.get('value')
    
    # 1. Check if setting is supported
    if not isSupported(setting):
        return {
            'data': {
                'success': False,
                'error': f'Unknown setting: "{setting}"',
            },
        }
    
    config = getConfig(setting)
    path = getPath(setting)
    
    # 2. GET operation
    if value is None:
        currentValue = getValue(config['source'], path)
        displayValue = config.get('formatOnRead', lambda v: v)(currentValue) if config.get('formatOnRead') else currentValue
        
        return {
            'data': {
                'success': True,
                'operation': 'get',
                'setting': setting,
                'value': displayValue,
            },
        }
    
    # 3. SET operation
    
    # Handle "default" — unset the config key so it falls back to the
    # platform-aware default (determined by the bridge feature gate).
    if (
        setting == 'remoteControlAtStartup' and
        isinstance(value, str) and
        value.lower().strip() == 'default'
    ):
        def remove_key(prev):
            if prev.get('remoteControlAtStartup') is None:
                return prev
            next_config = prev.copy()
            del next_config['remoteControlAtStartup']
            return next_config
        
        saveGlobalConfig(remove_key)
        resolved = getRemoteControlAtStartup()
        
        # Sync to AppState so useReplBridge reacts immediately
        context.setAppState(lambda prev: {
            **prev,
            'replBridgeEnabled': resolved,
            'replBridgeOutboundOnly': False,
        } if prev.get('replBridgeEnabled') != resolved or prev.get('replBridgeOutboundOnly') else prev)
        
        return {
            'data': {
                'success': True,
                'operation': 'set',
                'setting': setting,
                'value': resolved,
            },
        }
    
    finalValue = value
    
    # Coerce and validate boolean values
    if config.get('type') == 'boolean':
        if isinstance(value, str):
            lower = value.lower().strip()
            if lower == 'true':
                finalValue = True
            elif lower == 'false':
                finalValue = False
        
        if not isinstance(finalValue, bool):
            return {
                'data': {
                    'success': False,
                    'operation': 'set',
                    'setting': setting,
                    'error': f'{setting} requires true or false.',
                },
            }
    
    # Check options
    options = getOptionsForSetting(setting)
    if options and str(finalValue) not in options:
        return {
            'data': {
                'success': False,
                'operation': 'set',
                'setting': setting,
                'error': f'Invalid value "{value}". Options: {", ".join(options)}',
            },
        }
    
    # Async validation (e.g., model API check)
    if config.get('validateOnWrite'):
        result = await config['validateOnWrite'](finalValue)
        if not result.get('valid'):
            return {
                'data': {
                    'success': False,
                    'operation': 'set',
                    'setting': setting,
                    'error': result.get('error'),
                },
            }
    
    previousValue = getValue(config['source'], path)
    
    # 4. Write to storage
    try:
        if config['source'] == 'global':
            key = path[0]
            if not key:
                return {
                    'data': {
                        'success': False,
                        'operation': 'set',
                        'setting': setting,
                        'error': 'Invalid setting path',
                    },
                }
            
            def update_global(prev):
                if prev.get(key) == finalValue:
                    return prev
                return {**prev, key: finalValue}
            
            saveGlobalConfig(update_global)
        else:
            update = buildNestedObject(path, finalValue)
            result = updateSettingsForSource('userSettings', update)
            if result.get('error'):
                return {
                    'data': {
                        'success': False,
                        'operation': 'set',
                        'setting': setting,
                        'error': result['error'].get('message'),
                    },
                }
        
        # 5a. Voice needs notifyChange so applySettingsChange resyncs
        # AppState.settings (useVoiceEnabled reads settings.voiceEnabled)
        # and the settings cache resets for the next /voice read.
        voice_mode_enabled = os.environ.get('VOICE_MODE', '').lower() in ('true', '1', 'yes')
        if voice_mode_enabled and setting == 'voiceEnabled':
            try:
                from ...utils.settings.changeDetector import settingsChangeDetector
                settingsChangeDetector.notifyChange('userSettings')
            except ImportError:
                pass
        
        # 5b. Sync to AppState if needed for immediate UI effect
        if config.get('appStateKey'):
            appKey = config['appStateKey']
            context.setAppState(lambda prev: {
                **prev,
                appKey: finalValue,
            } if prev.get(appKey) != finalValue else prev)
        
        # Sync remoteControlAtStartup to AppState so the bridge reacts
        # immediately (the config key differs from the AppState field name,
        # so the generic appStateKey mechanism can't handle this).
        if setting == 'remoteControlAtStartup':
            resolved = getRemoteControlAtStartup()
            context.setAppState(lambda prev: {
                **prev,
                'replBridgeEnabled': resolved,
                'replBridgeOutboundOnly': False,
            } if prev.get('replBridgeEnabled') != resolved or prev.get('replBridgeOutboundOnly') else prev)
        
        logEvent('tengu_config_tool_changed', {
            'setting': setting,
            'value': str(finalValue),
        })
        
        return {
            'data': {
                'success': True,
                'operation': 'set',
                'setting': setting,
                'previousValue': previousValue,
                'newValue': finalValue,
            },
        }
    
    except Exception as error:
        logError(error)
        return {
            'data': {
                'success': False,
                'operation': 'set',
                'setting': setting,
                'error': errorMessage(error),
            },
        }


def mapToolResultToToolResultBlockParam(content: Output, toolUseID: str) -> Dict[str, Any]:
    """Map tool output to Anthropic API tool result block."""
    if content.get('success'):
        if content.get('operation') == 'get':
            return {
                'tool_use_id': toolUseID,
                'type': 'tool_result',
                'content': f'{content["setting"]} = {jsonStringify(content["value"])}',
            }
        return {
            'tool_use_id': toolUseID,
            'type': 'tool_result',
            'content': f'Set {content["setting"]} to {jsonStringify(content["newValue"])}',
        }
    
    return {
        'tool_use_id': toolUseID,
        'type': 'tool_result',
        'content': f'Error: {content.get("error")}',
        'is_error': True,
    }


# Build the tool definition
ConfigTool = buildTool(
    name=CONFIG_TOOL_NAME,
    searchHint='get or set Claude Code settings (theme, model)',
    maxResultSizeChars=100_000,
    description=lambda: DESCRIPTION,
    prompt=generatePrompt,
    userFacingName=lambda: 'Config',
    shouldDefer=True,
    isConcurrencySafe=lambda: True,
    isReadOnly=isReadOnly,
    toAutoClassifierInput=toAutoClassifierInput,
    checkPermissions=checkPermissions,
    renderToolUseMessage=renderToolUseMessage,
    renderToolResultMessage=renderToolResultMessage,
    renderToolUseRejectedMessage=renderToolUseRejectedMessage,
    call=call,
    mapToolResultToToolResultBlockParam=mapToolResultToToolResultBlockParam,
)
