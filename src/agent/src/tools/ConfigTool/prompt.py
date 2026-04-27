"""
ConfigTool prompts and description.
"""

import os

DESCRIPTION = 'Get or set Claude Code configuration settings.'


def generatePrompt() -> str:
    """Generate the prompt documentation from the registry."""
    try:
        from .supportedSettings import SUPPORTED_SETTINGS, getOptionsForSetting
    except ImportError:
        SUPPORTED_SETTINGS = {}
        
        def getOptionsForSetting(key):
            return None
    
    globalSettings = []
    projectSettings = []
    
    for key, config in SUPPORTED_SETTINGS.items():
        # Skip model - it gets its own section with dynamic options
        if key == 'model':
            continue
        
        # Voice settings are registered at build-time but gated by GrowthBook
        # at runtime. Hide from model prompt when the kill-switch is on.
        voice_mode_enabled = os.environ.get('VOICE_MODE', '').lower() in ('true', '1', 'yes')
        if voice_mode_enabled and key == 'voiceEnabled':
            # Check if voice is actually enabled via growthbook
            try:
                from ...voice.voiceModeEnabled import isVoiceGrowthBookEnabled
                if not isVoiceGrowthBookEnabled():
                    continue
            except ImportError:
                pass
        
        options = getOptionsForSetting(key)
        line = f'- {key}'
        
        if options:
            quoted_options = [f'"{o}"' for o in options]
            line += f': {", ".join(quoted_options)}'
        elif config.get('type') == 'boolean':
            line += ': true/false'
        
        line += f' - {config["description"]}'
        
        if config['source'] == 'global':
            globalSettings.append(line)
        else:
            projectSettings.append(line)
    
    modelSection = generateModelSection()
    
    return f"""Get or set Claude Code configuration settings.

View or change Claude Code settings. Use when the user requests configuration changes, asks about current settings, or when adjusting a setting would benefit them.


## Usage
- **Get current value:** Omit the "value" parameter
- **Set new value:** Include the "value" parameter

## Configurable settings list
The following settings are available for you to change:

### Global Settings (stored in ~/.cortex.json)
{chr(10).join(globalSettings)}

### Project Settings (stored in settings.json)
{chr(10).join(projectSettings)}

{modelSection}
## Examples
- Get theme: {{ "setting": "theme" }}
- Set dark theme: {{ "setting": "theme", "value": "dark" }}
- Enable vim mode: {{ "setting": "editorMode", "value": "vim" }}
- Enable verbose: {{ "setting": "verbose", "value": true }}
- Change model: {{ "setting": "model", "value": "opus" }}
- Change permission mode: {{ "setting": "permissions.defaultMode", "value": "plan" }}
"""


def generateModelSection() -> str:
    """Generate model options section."""
    try:
        from ...utils.model.modelOptions import getModelOptions
        
        options = getModelOptions()
        lines = []
        for o in options:
            value = 'null/"default"' if o.get('value') is None else f'"{o["value"]}"'
            description = o.get('descriptionForModel') or o.get('description', '')
            lines.append(f'  - {value}: {description}')
        
        return f"""## Model
- model - Override the default model. Available options:
{chr(10).join(lines)}"""
    
    except Exception:
        return """## Model
- model - Override the default model (sonnet, opus, haiku, best, or full model ID)"""
