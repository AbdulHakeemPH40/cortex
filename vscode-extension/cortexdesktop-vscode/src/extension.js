const vscode = require('vscode');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const http = require('node:http');
const { URL } = require('node:url');

const {
  chooseLaunchWorkspace,
  describeProviderState,
  findCommandPath,
  isPathInsideWorkspace,
  parseProfileFile,
  resolveCommandCheckPath,
} = require('./state');
const { buildControlCenterViewModel } = require('./presentation');
const { ChatController, CortexDesktopChatViewProvider, CortexDesktopChatPanelManager } = require('./chat/chatProvider');
const { SessionManager } = require('./chat/sessionManager');
const { DiffContentProvider, SCHEME: DIFF_SCHEME } = require('./chat/diffController');

const CORTEXDESKTOP_REPO_URL = 'https://github.com/';
const CORTEXDESKTOP_SETUP_URL = 'https://github.com/';
const PROFILE_FILE_NAME = '.cortex-profile.json';

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

async function isCommandAvailable(command, launchCwd) {
  return Boolean(findCommandPath(command, { cwd: launchCwd }));
}

function getExecutableFromCommand(command) {
  const normalized = String(command || '').trim();
  if (!normalized) {
    return '';
  }

  const doubleQuotedMatch = normalized.match(/^"([^"]+)"/);
  if (doubleQuotedMatch) {
    return doubleQuotedMatch[1];
  }

  const singleQuotedMatch = normalized.match(/^'([^']+)'/);
  if (singleQuotedMatch) {
    return singleQuotedMatch[1];
  }

  return normalized.split(/\s+/)[0];
}

function getWorkspacePaths() {
  return (vscode.workspace.workspaceFolders || []).map(folder => folder.uri.fsPath);
}

function getActiveWorkspacePath() {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.uri.scheme !== 'file') {
    return null;
  }

  const workspaceFolder = vscode.workspace.getWorkspaceFolder(editor.document.uri);
  return workspaceFolder ? workspaceFolder.uri.fsPath : null;
}

function getActiveFilePath() {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.uri.scheme !== 'file') {
    return null;
  }

  return editor.document.uri.fsPath || null;
}

function resolveLaunchTargets({ activeFilePath, workspacePath, workspaceSourceLabel, executable } = {}) {
  const activeFileDirectory = isPathInsideWorkspace(activeFilePath, workspacePath)
    ? path.dirname(activeFilePath)
    : null;
  const normalizedExecutable = String(executable || '').trim();
  const commandPath = normalizedExecutable
    ? resolveCommandCheckPath(normalizedExecutable, workspacePath)
    : null;
  const relativeCommandRequiresWorkspaceRoot = Boolean(
    workspacePath && commandPath && !path.isAbsolute(normalizedExecutable),
  );

  if (relativeCommandRequiresWorkspaceRoot) {
    return {
      projectAwareCwd: workspacePath,
      projectAwareCwdLabel: workspacePath,
      projectAwareSourceLabel: 'workspace root (required by relative launch command)',
      workspaceRootCwd: workspacePath,
      workspaceRootCwdLabel: workspacePath,
      launchActionsShareTarget: true,
      launchActionsShareTargetReason: 'relative-launch-command',
    };
  }

  if (activeFileDirectory) {
    return {
      projectAwareCwd: activeFileDirectory,
      projectAwareCwdLabel: activeFileDirectory,
      projectAwareSourceLabel: 'active file directory',
      workspaceRootCwd: workspacePath || null,
      workspaceRootCwdLabel: workspacePath || 'No workspace open',
      launchActionsShareTarget: false,
      launchActionsShareTargetReason: null,
    };
  }

  if (workspacePath) {
    return {
      projectAwareCwd: workspacePath,
      projectAwareCwdLabel: workspacePath,
      projectAwareSourceLabel: workspaceSourceLabel || 'workspace root',
      workspaceRootCwd: workspacePath,
      workspaceRootCwdLabel: workspacePath,
      launchActionsShareTarget: true,
      launchActionsShareTargetReason: null,
    };
  }

  return {
    projectAwareCwd: null,
    projectAwareCwdLabel: 'VS Code default terminal cwd',
    projectAwareSourceLabel: 'VS Code default terminal cwd',
    workspaceRootCwd: null,
    workspaceRootCwdLabel: 'No workspace open',
    launchActionsShareTarget: false,
    launchActionsShareTargetReason: null,
  };
}

function createLspBridge() {
  let server = null;
  let runningPort = null;
  let config = {
    enabled: false,
    port: 53999,
    authToken: '',
  };

  function loadConfig() {
    const cfg = vscode.workspace.getConfiguration('cortexdesktop');
    const enabled = Boolean(cfg.get('lspBridge.enabled', false));
    const port = Number(cfg.get('lspBridge.port', 53999));
    const authToken = String(cfg.get('lspBridge.authToken', '') || '').trim();
    return {
      enabled,
      port: Number.isFinite(port) ? port : 53999,
      authToken,
    };
  }

  function serializePosition(pos) {
    return pos ? { line: pos.line, character: pos.character } : null;
  }

  function serializeRange(range) {
    if (!range) return null;
    return {
      start: serializePosition(range.start),
      end: serializePosition(range.end),
    };
  }

  function serializeUri(uri) {
    return uri ? uri.toString() : null;
  }

  function serializeLocation(loc) {
    if (!loc) return null;
    return {
      uri: serializeUri(loc.uri),
      range: serializeRange(loc.range),
    };
  }

  function serializeLocationLink(link) {
    if (!link) return null;
    return {
      targetUri: serializeUri(link.targetUri),
      targetRange: serializeRange(link.targetRange),
      targetSelectionRange: serializeRange(link.targetSelectionRange),
      originSelectionRange: serializeRange(link.originSelectionRange),
    };
  }

  function serializeDocumentSymbol(symbol) {
    return {
      name: symbol.name,
      detail: symbol.detail || '',
      kind: symbol.kind,
      tags: symbol.tags || [],
      range: serializeRange(symbol.range),
      selectionRange: serializeRange(symbol.selectionRange),
      children: Array.isArray(symbol.children) ? symbol.children.map(serializeDocumentSymbol) : [],
    };
  }

  function serializeSymbolInformation(symbol) {
    return {
      name: symbol.name,
      kind: symbol.kind,
      tags: symbol.tags || [],
      containerName: symbol.containerName || '',
      location: serializeLocation(symbol.location),
    };
  }

  function serializeDiagnostic(d) {
    return {
      range: serializeRange(d.range),
      severity: d.severity ?? null,
      code: d.code ?? null,
      source: d.source ?? null,
      message: d.message ?? '',
    };
  }

  function normalizeUri(payload) {
    const rawUri = payload && typeof payload.uri === 'string' ? payload.uri : null;
    if (rawUri) {
      return vscode.Uri.parse(rawUri);
    }
    const rawPath = payload && typeof payload.path === 'string' ? payload.path : null;
    if (rawPath) {
      return vscode.Uri.file(rawPath);
    }
    return null;
  }

  function normalizePosition(payload) {
    const pos = payload && payload.position ? payload.position : null;
    const line = pos && Number.isFinite(pos.line) ? pos.line : null;
    const character = pos && Number.isFinite(pos.character) ? pos.character : null;
    if (line === null || character === null) return null;
    return new vscode.Position(line, character);
  }

  function sendJson(res, statusCode, payload) {
    const body = Buffer.from(JSON.stringify(payload));
    res.writeHead(statusCode, {
      'Content-Type': 'application/json; charset=utf-8',
      'Content-Length': body.length,
      'Cache-Control': 'no-store',
    });
    res.end(body);
  }

  function readJson(req, maxBytes = 1_000_000) {
    return new Promise((resolve, reject) => {
      let total = 0;
      const chunks = [];
      req.on('data', chunk => {
        total += chunk.length;
        if (total > maxBytes) {
          reject(new Error('Payload too large'));
          req.destroy();
          return;
        }
        chunks.push(chunk);
      });
      req.on('end', () => {
        if (chunks.length === 0) {
          resolve({});
          return;
        }
        const raw = Buffer.concat(chunks).toString('utf8');
        try {
          resolve(JSON.parse(raw));
        } catch {
          reject(new Error('Invalid JSON'));
        }
      });
      req.on('error', reject);
    });
  }

  function isAuthorized(req) {
    if (!config.authToken) return true;
    const header = String(req.headers.authorization || '');
    return header === `Bearer ${config.authToken}`;
  }

  async function handleHealth(_payload) {
    return { ok: true, port: runningPort };
  }

  async function handleDiagnostics(payload) {
    const uri = normalizeUri(payload);
    if (uri) {
      const diagnostics = vscode.languages.getDiagnostics(uri).map(serializeDiagnostic);
      return { uri: uri.toString(), diagnostics };
    }
    const entries = vscode.languages.getDiagnostics().map(([docUri, list]) => ({
      uri: docUri.toString(),
      diagnostics: list.map(serializeDiagnostic),
    }));
    return { diagnostics: entries };
  }

  async function handleDocumentSymbols(payload) {
    const uri = normalizeUri(payload);
    if (!uri) {
      throw new Error('Missing uri');
    }
    await vscode.workspace.openTextDocument(uri);
    const result = await vscode.commands.executeCommand('vscode.executeDocumentSymbolProvider', uri);
    const symbols = Array.isArray(result) ? result : [];
    const isDocumentSymbol = symbols.length > 0 && typeof symbols[0]?.range === 'object';
    return {
      uri: uri.toString(),
      symbols: isDocumentSymbol
        ? symbols.map(serializeDocumentSymbol)
        : symbols.map(serializeSymbolInformation),
      format: isDocumentSymbol ? 'DocumentSymbol[]' : 'SymbolInformation[]',
    };
  }

  async function handleDefinition(payload) {
    const uri = normalizeUri(payload);
    const position = normalizePosition(payload);
    if (!uri || !position) throw new Error('Missing uri or position');
    await vscode.workspace.openTextDocument(uri);
    const result = await vscode.commands.executeCommand('vscode.executeDefinitionProvider', uri, position);
    const locations = Array.isArray(result) ? result : result ? [result] : [];
    const isLink = locations.length > 0 && locations[0] && typeof locations[0] === 'object' && 'targetUri' in locations[0];
    return {
      uri: uri.toString(),
      position: serializePosition(position),
      locations: isLink ? locations.map(serializeLocationLink) : locations.map(serializeLocation),
      format: isLink ? 'LocationLink[]' : 'Location[]',
    };
  }

  async function handleReferences(payload) {
    const uri = normalizeUri(payload);
    const position = normalizePosition(payload);
    const includeDeclaration = Boolean(payload && payload.includeDeclaration);
    if (!uri || !position) throw new Error('Missing uri or position');
    await vscode.workspace.openTextDocument(uri);
    const result = await vscode.commands.executeCommand(
      'vscode.executeReferenceProvider',
      uri,
      position,
      { includeDeclaration },
    );
    const locations = Array.isArray(result) ? result : [];
    return {
      uri: uri.toString(),
      position: serializePosition(position),
      includeDeclaration,
      locations: locations.map(serializeLocation),
    };
  }

  async function handleHover(payload) {
    const uri = normalizeUri(payload);
    const position = normalizePosition(payload);
    if (!uri || !position) throw new Error('Missing uri or position');
    await vscode.workspace.openTextDocument(uri);
    const result = await vscode.commands.executeCommand('vscode.executeHoverProvider', uri, position);
    const hovers = Array.isArray(result) ? result : [];
    const normalized = hovers.map(h => ({
      range: serializeRange(h.range),
      contents: Array.isArray(h.contents)
        ? h.contents.map(c => (typeof c === 'string' ? c : c.value ?? String(c)))
        : [],
    }));
    return { uri: uri.toString(), position: serializePosition(position), hovers: normalized };
  }

  function route(pathname) {
    switch (pathname) {
      case '/health':
        return handleHealth;
      case '/diagnostics':
        return handleDiagnostics;
      case '/documentSymbols':
        return handleDocumentSymbols;
      case '/definition':
        return handleDefinition;
      case '/references':
        return handleReferences;
      case '/hover':
        return handleHover;
      default:
        return null;
    }
  }

  async function start() {
    if (server) return;
    if (!config.enabled) return;
    server = http.createServer(async (req, res) => {
      try {
        if (req.method !== 'POST') {
          sendJson(res, 405, { ok: false, error: 'Method not allowed' });
          return;
        }
        if (!isAuthorized(req)) {
          sendJson(res, 401, { ok: false, error: 'Unauthorized' });
          return;
        }
        const url = new URL(req.url || '/', 'http://127.0.0.1');
        const handler = route(url.pathname);
        if (!handler) {
          sendJson(res, 404, { ok: false, error: 'Not found' });
          return;
        }
        const payload = await readJson(req);
        const result = await handler(payload);
        sendJson(res, 200, { ok: true, result });
      } catch (err) {
        sendJson(res, 500, { ok: false, error: String(err && err.message ? err.message : err) });
      }
    });

    await new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(config.port, '127.0.0.1', () => {
        runningPort = config.port;
        resolve();
      });
    });
  }

  async function stop() {
    if (!server) return;
    const toClose = server;
    server = null;
    runningPort = null;
    await new Promise(resolve => {
      toClose.close(() => resolve());
    });
  }

  async function refreshConfig() {
    const next = loadConfig();
    const needsRestart = server && (
      next.port !== config.port ||
      next.authToken !== config.authToken ||
      !next.enabled
    );
    config = next;
    if (needsRestart) {
      await stop();
    }
    if (config.enabled && !server) {
      try {
        await start();
      } catch (err) {
        await vscode.window.showErrorMessage(
          `Cortex Desktop LSP bridge failed to start on port ${config.port}: ${String(err && err.message ? err.message : err)}`,
        );
        await stop();
      }
    }
  }

  return {
    refreshConfig,
    dispose: () => {
      void stop();
    },
  };
}

function resolveLaunchWorkspace() {
  return chooseLaunchWorkspace({
    activeWorkspacePath: getActiveWorkspacePath(),
    workspacePaths: getWorkspacePaths(),
  });
}

function getWorkspaceSourceLabel(source) {
  switch (source) {
    case 'active-workspace':
      return 'active editor workspace';
    case 'first-workspace':
      return 'first workspace folder';
    default:
      return 'no workspace open';
  }
}

function getProviderSourceLabel(source) {
  switch (source) {
    case 'profile':
      return 'saved profile';
    case 'env':
      return 'environment';
    case 'shim':
      return 'launch setting';
    default:
      return 'unknown';
  }
}

function readWorkspaceProfile(profilePath) {
  if (!profilePath || !fs.existsSync(profilePath)) {
    return {
      profile: null,
      statusLabel: 'Missing',
      statusHint: `${PROFILE_FILE_NAME} not found in the workspace root`,
      filePath: null,
    };
  }

  try {
    const raw = fs.readFileSync(profilePath, 'utf8');
    const profile = parseProfileFile(raw);
    if (!profile) {
      return {
        profile: null,
        statusLabel: 'Invalid',
        statusHint: `${profilePath} has invalid JSON or an unsupported profile`,
        filePath: profilePath,
      };
    }

    return {
      profile,
      statusLabel: 'Found',
      statusHint: profilePath,
      filePath: profilePath,
    };
  } catch (error) {
    return {
      profile: null,
      statusLabel: 'Unreadable',
      statusHint: `${profilePath} (${error instanceof Error ? error.message : 'read failed'})`,
      filePath: profilePath,
    };
  }
}

async function collectControlCenterState() {
  const configured = vscode.workspace.getConfiguration('cortexdesktop');
  const launchCommand = configured.get('launchCommand', 'cortex');
  const terminalName = configured.get('terminalName', 'Cortex Desktop');
  const shimEnabled = configured.get('useOpenAIShim', false);
  const executable = getExecutableFromCommand(launchCommand);
  const launchWorkspace = resolveLaunchWorkspace();
  const workspaceFolder = launchWorkspace.workspacePath;
  const workspaceSourceLabel = getWorkspaceSourceLabel(launchWorkspace.source);
  const launchTargets = resolveLaunchTargets({
    activeFilePath: getActiveFilePath(),
    workspacePath: workspaceFolder,
    workspaceSourceLabel,
    executable,
  });
  const installed = await isCommandAvailable(executable, launchTargets.projectAwareCwd);
  const profilePath = workspaceFolder
    ? path.join(workspaceFolder, PROFILE_FILE_NAME)
    : null;

  const profileState = workspaceFolder
    ? readWorkspaceProfile(profilePath)
    : {
        profile: null,
        statusLabel: 'No workspace',
        statusHint: 'Open a workspace folder to detect a saved profile',
        filePath: null,
      };

  const providerState = describeProviderState({
    shimEnabled,
    env: process.env,
    profile: profileState.profile,
  });

  return {
    installed,
    executable,
    launchCommand,
    terminalName,
    shimEnabled,
    workspaceFolder,
    workspaceSourceLabel,
    launchCwd: launchTargets.projectAwareCwd,
    launchCwdLabel: launchTargets.projectAwareCwdLabel,
    launchCwdSourceLabel: launchTargets.projectAwareSourceLabel,
    workspaceRootCwd: launchTargets.workspaceRootCwd,
    workspaceRootCwdLabel: launchTargets.workspaceRootCwdLabel,
    launchActionsShareTarget: launchTargets.launchActionsShareTarget,
    launchActionsShareTargetReason: launchTargets.launchActionsShareTargetReason,
    canLaunchInWorkspaceRoot: Boolean(workspaceFolder),
    profileStatusLabel: profileState.statusLabel,
    profileStatusHint: profileState.statusHint,
    workspaceProfilePath: profileState.filePath,
    providerState,
    providerSourceLabel: getProviderSourceLabel(providerState.source),
  };
}

async function launchCortexDesktop(options = {}) {
  const { requireWorkspace = false } = options;
  const configured = vscode.workspace.getConfiguration('cortexdesktop');
  const launchCommand = configured.get('launchCommand', 'cortex');
  const terminalName = configured.get('terminalName', 'Cortex Desktop');
  const shimEnabled = configured.get('useOpenAIShim', false);
  const executable = getExecutableFromCommand(launchCommand);
  const launchWorkspace = resolveLaunchWorkspace();

  if (requireWorkspace && !launchWorkspace.workspacePath) {
    await vscode.window.showWarningMessage(
      'Open a workspace folder before using Launch in Workspace Root.',
    );
    return;
  }

  const launchTargets = resolveLaunchTargets({
    activeFilePath: getActiveFilePath(),
    workspacePath: launchWorkspace.workspacePath,
    workspaceSourceLabel: getWorkspaceSourceLabel(launchWorkspace.source),
    executable,
  });
  const targetCwd = requireWorkspace
    ? launchTargets.workspaceRootCwd
    : launchTargets.projectAwareCwd;
  const installed = await isCommandAvailable(executable, targetCwd);

  if (!installed) {
    const action = await vscode.window.showErrorMessage(
      `Cortex Desktop command not found: ${executable}.`,
      'Open Setup Guide',
      'Open Repository',
    );

    if (action === 'Open Setup Guide') {
      await vscode.env.openExternal(vscode.Uri.parse(CORTEXDESKTOP_SETUP_URL));
    } else if (action === 'Open Repository') {
      await vscode.env.openExternal(vscode.Uri.parse(CORTEXDESKTOP_REPO_URL));
    }

    return;
  }

  const env = {};
  if (shimEnabled) {
    env.CORTEX_CODE_USE_OPENAI = '1';
  }

  const terminalOptions = {
    name: terminalName,
    env,
  };

  if (targetCwd) {
    terminalOptions.cwd = targetCwd;
  }

  const terminal = vscode.window.createTerminal(terminalOptions);
  terminal.show(true);
  terminal.sendText(launchCommand, true);
}

async function openWorkspaceProfile() {
  const state = await collectControlCenterState();

  if (!state.workspaceProfilePath) {
    await vscode.window.showInformationMessage(
      `No ${PROFILE_FILE_NAME} file was found for the current workspace.`,
    );
    return;
  }

  const document = await vscode.workspace.openTextDocument(
    vscode.Uri.file(state.workspaceProfilePath),
  );
  await vscode.window.showTextDocument(document, { preview: false });
}

function getToneClass(tone) {
  switch (tone) {
    case 'accent':
      return 'tone-accent';
    case 'positive':
      return 'tone-positive';
    case 'warning':
      return 'tone-warning';
    case 'critical':
      return 'tone-critical';
    default:
      return 'tone-neutral';
  }
}

function renderHeaderBadge(badge) {
  return `<div class="rail-pill ${getToneClass(badge.tone)}" title="${escapeHtml(badge.label)}: ${escapeHtml(badge.value)}">
    <span class="rail-label">${escapeHtml(badge.label)}</span>
    <span class="rail-value">${escapeHtml(badge.value)}</span>
  </div>`;
}

function renderSummaryCard(card) {
  const detail = card.detail || '';
  return `<section class="summary-card" aria-label="${escapeHtml(card.label)}">
    <div class="summary-label">${escapeHtml(card.label)}</div>
    <div class="summary-value" title="${escapeHtml(card.value)}">${escapeHtml(card.value)}</div>
    ${detail ? `<div class="summary-detail" title="${escapeHtml(detail)}">${escapeHtml(detail)}</div>` : ''}
  </section>`;
}

function renderDetailRow(row) {
  return `<div class="detail-row ${getToneClass(row.tone)}">
    <div class="detail-label">${escapeHtml(row.label)}</div>
    <div class="detail-summary" title="${escapeHtml(row.summary)}">${escapeHtml(row.summary)}</div>
    ${row.detail ? `<div class="detail-meta" title="${escapeHtml(row.detail)}">${escapeHtml(row.detail)}</div>` : ''}
  </div>`;
}

function renderDetailSection(section) {
  const sectionId = `section-${String(section.title || 'section').toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
  return `<section class="detail-module" aria-labelledby="${escapeHtml(sectionId)}">
    <h2 class="module-title" id="${escapeHtml(sectionId)}">${escapeHtml(section.title)}</h2>
    <div class="detail-list">${section.rows.map(renderDetailRow).join('')}</div>
  </section>`;
}

function renderActionButton(action, variant = 'secondary') {
  return `<button class="action-button ${variant}" id="${escapeHtml(action.id)}" type="button" ${action.disabled ? 'disabled aria-disabled="true"' : ''}>
    <span class="action-label">${escapeHtml(action.label)}</span>
    <span class="action-detail">${escapeHtml(action.detail)}</span>
  </button>`;
}

function renderProfileEmptyState(detail) {
  return `<div class="action-empty" role="status" aria-live="polite">
    <div class="action-empty-title">No workspace profile yet</div>
    <div class="action-empty-detail">${escapeHtml(detail)}</div>
  </div>`;
}

function getPrimaryLaunchActionDetail(status) {
  if (status.launchActionsShareTargetReason === 'relative-launch-command' && status.launchCwd) {
    return `Project-aware launch is anchored to the workspace root by the relative command · ${status.launchCwdLabel}`;
  }

  if (status.launchCwd && status.launchCwdSourceLabel === 'active file directory') {
    return `Starts beside the active file · ${status.launchCwdLabel}`;
  }

  if (status.launchCwd) {
    return `Project-aware launch. Currently resolves to ${status.launchCwdSourceLabel} · ${status.launchCwdLabel}`;
  }

  return 'Project-aware launch. Uses the VS Code default terminal cwd';
}

function getWorkspaceRootActionDetail(status, fallbackDetail) {
  if (!status.canLaunchInWorkspaceRoot) {
    return fallbackDetail;
  }

  if (status.launchActionsShareTargetReason === 'relative-launch-command') {
    return `Same workspace-root target as Launch Cortex Desktop because the relative command resolves from the workspace root · ${status.workspaceRootCwdLabel}`;
  }

  return `Always starts at the workspace root · ${status.workspaceRootCwdLabel}`;
}

function getRenderableViewModel(status) {
  const viewModel = buildControlCenterViewModel(status);
  const summaryCards = viewModel.summaryCards.map(card => {
    if (card.key !== 'launchCwd' || card.detail) {
      return card;
    }

    return {
      ...card,
      detail: status.launchCwdSourceLabel || '',
    };
  });

  return {
    ...viewModel,
    summaryCards,
    actions: {
      ...viewModel.actions,
      primary: {
        ...viewModel.actions.primary,
        detail: getPrimaryLaunchActionDetail(status),
      },
      launchRoot: {
        ...viewModel.actions.launchRoot,
        detail: getWorkspaceRootActionDetail(status, viewModel.actions.launchRoot.detail),
      },
    },
  };
}

function renderControlCenterHtml(status, options = {}) {
  const nonce = options.nonce || crypto.randomBytes(16).toString('base64');
  const platform = options.platform || process.platform;
  const viewModel = getRenderableViewModel(status);
  const profileActionOrEmpty = viewModel.actions.openProfile
    ? renderActionButton(viewModel.actions.openProfile)
    : renderProfileEmptyState(status.profileStatusHint || 'Open a workspace folder to detect a saved profile');

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <style>
    :root {
      --oc-bg: #050505;
      --oc-panel: #110d0c;
      --oc-panel-strong: #17110f;
      --oc-panel-soft: #1d1512;
      --oc-border: #645041;
      --oc-border-soft: rgba(220, 195, 170, 0.14);
      --oc-text: #f7efe5;
      --oc-text-dim: #dcc3aa;
      --oc-text-soft: #aa9078;
      --oc-accent: #d77757;
      --oc-accent-bright: #f09464;
      --oc-accent-soft: rgba(240, 148, 100, 0.18);
      --oc-positive: #e8b86b;
      --oc-warning: #f3c969;
      --oc-critical: #ff8a6c;
      --oc-focus: #ffd3a1;
    }
    * {
      box-sizing: border-box;
    }
    h1, h2, p {
      margin: 0;
    }
    html, body {
      margin: 0;
      min-height: 100%;
    }
    body {
      padding: 16px;
      font-family: var(--vscode-font-family, "Segoe UI", sans-serif);
      color: var(--oc-text);
      background:
        radial-gradient(circle at top right, rgba(240, 148, 100, 0.16), transparent 34%),
        radial-gradient(circle at 20% 0%, rgba(215, 119, 87, 0.14), transparent 28%),
        linear-gradient(180deg, #090706, #050505 58%, #090706);
      line-height: 1.45;
    }
    button {
      font: inherit;
    }
    .shell {
      position: relative;
      overflow: hidden;
      border: 1px solid var(--oc-border-soft);
      border-radius: 20px;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent 16%),
        linear-gradient(180deg, rgba(17, 13, 12, 0.98), rgba(9, 7, 6, 0.98));
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.03);
    }
    .shell::before {
      content: "";
      position: absolute;
      inset: 0 0 auto;
      height: 2px;
      background: linear-gradient(90deg, #ffb464, #f09464, #d77757, #814334);
      opacity: 0.95;
    }
    .sunset-gradient {
      background: linear-gradient(90deg, #ffb464, #f09464, #d77757, #814334);
    }
    .frame {
      display: grid;
      gap: 18px;
      padding: 18px;
    }
    .hero {
      display: grid;
      gap: 14px;
      padding: 18px;
      border-radius: 16px;
      background:
        linear-gradient(135deg, rgba(240, 148, 100, 0.06), rgba(215, 119, 87, 0.02) 55%, transparent),
        var(--oc-panel);
      border: 1px solid var(--oc-border-soft);
    }
    .hero-top {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }
    .brand {
      display: grid;
      gap: 6px;
      min-width: 0;
    }
    .eyebrow {
      font-size: 11px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--oc-text-soft);
    }
    .wordmark {
      font-size: 24px;
      line-height: 1;
      font-weight: 700;
      letter-spacing: -0.03em;
      color: var(--oc-text);
    }
    .wordmark-accent {
      color: var(--oc-accent-bright);
    }
    .headline {
      display: grid;
      gap: 4px;
      max-width: 44ch;
    }
    .headline-title {
      font-size: 15px;
      font-weight: 600;
      color: var(--oc-text);
    }
    .headline-subtitle {
      font-size: 12px;
      color: var(--oc-text-dim);
    }
    .status-rail {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      justify-content: flex-end;
      flex: 1 1 250px;
    }
    .rail-pill {
      display: grid;
      gap: 2px;
      min-width: 94px;
      padding: 8px 10px;
      border-radius: 999px;
      border: 1px solid var(--oc-border-soft);
      background: rgba(255, 255, 255, 0.02);
    }
    .rail-label {
      font-size: 10px;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--oc-text-soft);
    }
    .rail-value {
      font-size: 12px;
      font-weight: 700;
      color: var(--oc-text);
    }
    .refresh-button {
      border: 1px solid rgba(240, 148, 100, 0.28);
      border-radius: 999px;
      padding: 8px 12px;
      background: rgba(240, 148, 100, 0.08);
      color: var(--oc-text-dim);
      cursor: pointer;
      white-space: nowrap;
    }
    .summary-grid {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    }
    .summary-card {
      display: grid;
      gap: 6px;
      min-width: 0;
      padding: 14px;
      border-radius: 14px;
      background: var(--oc-panel-strong);
      border: 1px solid var(--oc-border-soft);
    }
    .summary-label,
    .detail-label,
    .module-title,
    .action-section-title,
    .support-title {
      font-size: 10px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--oc-text-soft);
    }
    .summary-value,
    .detail-summary {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 13px;
      font-weight: 600;
      color: var(--oc-text);
    }
    .summary-detail,
    .detail-meta,
    .action-detail,
    .action-empty-detail,
    .support-copy,
    .footer-note {
      font-size: 12px;
      color: var(--oc-text-dim);
    }
    .modules {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    }
    .detail-module,
    .support-card {
      display: grid;
      gap: 12px;
      padding: 16px;
      border-radius: 16px;
      background: var(--oc-panel);
      border: 1px solid var(--oc-border-soft);
    }
    .detail-list,
    .action-stack,
    .support-stack {
      display: grid;
      gap: 10px;
    }
    .detail-row {
      display: grid;
      gap: 4px;
      min-width: 0;
      padding: 12px;
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid rgba(220, 195, 170, 0.08);
    }
    .actions-layout {
      display: grid;
      gap: 14px;
      grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
      align-items: start;
    }
    .action-panel {
      display: grid;
      gap: 12px;
      padding: 16px;
      border-radius: 16px;
      background: var(--oc-panel);
      border: 1px solid var(--oc-border-soft);
    }
    .action-button {
      width: 100%;
      display: grid;
      gap: 4px;
      padding: 14px;
      text-align: left;
      border-radius: 14px;
      border: 1px solid rgba(220, 195, 170, 0.14);
      background: rgba(255, 255, 255, 0.02);
      color: var(--oc-text);
      cursor: pointer;
      transition: border-color 140ms ease, transform 140ms ease, background 140ms ease, box-shadow 140ms ease;
    }
    .action-button.primary {
      border-color: rgba(240, 148, 100, 0.44);
      background:
        linear-gradient(135deg, rgba(255, 180, 100, 0.22), rgba(215, 119, 87, 0.12) 58%, rgba(129, 67, 52, 0.12)),
        #241713;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
    }
    .action-button.secondary:hover:enabled,
    .action-button.primary:hover:enabled,
    .refresh-button:hover {
      border-color: rgba(240, 148, 100, 0.48);
      transform: translateY(-1px);
      background-color: rgba(240, 148, 100, 0.1);
    }
    .action-button:disabled {
      cursor: not-allowed;
      opacity: 0.58;
      transform: none;
    }
    .action-label,
    .action-empty-title,
    .support-link-label {
      font-size: 13px;
      font-weight: 700;
      color: var(--oc-text);
    }
    .action-empty {
      display: grid;
      gap: 4px;
      padding: 14px;
      border-radius: 14px;
      border: 1px dashed rgba(220, 195, 170, 0.16);
      background: rgba(255, 255, 255, 0.015);
    }
    .support-link {
      width: 100%;
      display: grid;
      gap: 4px;
      padding: 12px 0;
      border: 0;
      border-top: 1px solid rgba(220, 195, 170, 0.08);
      background: transparent;
      color: inherit;
      cursor: pointer;
      text-align: left;
    }
    .support-link:first-of-type {
      border-top: 0;
      padding-top: 0;
    }
    .tone-positive .rail-value,
    .tone-positive .detail-summary {
      color: var(--oc-positive);
    }
    .tone-warning .rail-value,
    .tone-warning .detail-summary {
      color: var(--oc-warning);
    }
    .tone-critical .rail-value,
    .tone-critical .detail-summary {
      color: var(--oc-critical);
    }
    .tone-accent .rail-value,
    .tone-accent .detail-summary {
      color: var(--oc-accent-bright);
    }
    .action-button:focus-visible,
    .support-link:focus-visible,
    .refresh-button:focus-visible {
      outline: 2px solid var(--oc-focus);
      outline-offset: 2px;
      box-shadow: 0 0 0 4px rgba(255, 211, 161, 0.16);
    }
    code {
      padding: 1px 6px;
      border-radius: 999px;
      border: 1px solid rgba(240, 148, 100, 0.18);
      background: rgba(240, 148, 100, 0.08);
      color: var(--oc-accent-bright);
      font-family: var(--vscode-editor-font-family, Consolas, monospace);
      font-size: 11px;
    }
    .footer-note {
      padding-top: 2px;
    }
    @media (max-width: 720px) {
      body {
        padding: 12px;
      }
      .frame,
      .hero {
        padding: 14px;
      }
      .actions-layout {
        grid-template-columns: 1fr;
      }
      .status-rail {
        justify-content: flex-start;
      }
      .rail-pill {
        min-width: 0;
      }
    }
  </style>
</head>
<body>
  <main class="shell" aria-labelledby="control-center-title">
    <div class="frame">
      <header class="hero">
        <div class="hero-top">
          <div class="brand">
            <div class="eyebrow">${escapeHtml(viewModel.header.eyebrow)}</div>
            <div class="wordmark" aria-label="Cortex Desktop wordmark">Cortex<span class="wordmark-accent">Desktop</span></div>
            <div class="headline">
              <h1 class="headline-title" id="control-center-title">${escapeHtml(viewModel.header.title)}</h1>
              <p class="headline-subtitle">${escapeHtml(viewModel.header.subtitle)}</p>
            </div>
          </div>
          <div class="status-rail" role="group" aria-label="Runtime, provider, and profile status">
            ${viewModel.headerBadges.map(renderHeaderBadge).join('')}
            <button class="refresh-button" id="refresh" type="button">Refresh</button>
          </div>
        </div>
        <section class="summary-grid" aria-label="Current launch summary">
          ${viewModel.summaryCards.map(renderSummaryCard).join('')}
        </section>
      </header>

      <section class="modules" aria-label="Control center details">
        ${viewModel.detailSections.map(renderDetailSection).join('')}
      </section>

      <section class="actions-layout" aria-label="Control center actions">
        <section class="action-panel" aria-labelledby="actions-title">
          <h2 class="action-section-title" id="actions-title">Launch & Project</h2>
          ${renderActionButton(viewModel.actions.primary, 'primary')}
          <div class="action-stack">
            ${renderActionButton(viewModel.actions.launchRoot)}
            ${profileActionOrEmpty}
          </div>
        </section>

        <section class="support-card" aria-labelledby="quick-links-title">
          <h2 class="support-title" id="quick-links-title">Quick Links</h2>
          <div class="support-copy">Settings and workspace status stay in view here. Reference links stay secondary.</div>
          <div class="support-stack">
            <button class="support-link" id="setup" type="button">
              <span class="support-link-label">Open Setup Guide</span>
              <span class="summary-detail">Jump to install and provider setup docs.</span>
            </button>
            <button class="support-link" id="repo" type="button">
              <span class="support-link-label">Open Repository</span>
              <span class="summary-detail">Browse the Cortex Desktop project.</span>
            </button>
            <button class="support-link" id="commands" type="button">
              <span class="support-link-label">Open Command Palette</span>
              <span class="summary-detail">Access VS Code and Cortex Desktop commands quickly.</span>
            </button>
          </div>
        </section>
      </section>

      <p class="footer-note">
        Quick trigger: use <code>${escapeHtml(platform === 'darwin' ? 'Cmd+Shift+P' : 'Ctrl+Shift+P')}</code> for the command palette, then refresh this panel after workspace or profile changes.
      </p>
    </div>
  </main>

  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    document.getElementById('launch').addEventListener('click', () => vscode.postMessage({ type: 'launch' }));
    document.getElementById('launchRoot').addEventListener('click', () => vscode.postMessage({ type: 'launchRoot' }));
    document.getElementById('repo').addEventListener('click', () => vscode.postMessage({ type: 'repo' }));
    document.getElementById('setup').addEventListener('click', () => vscode.postMessage({ type: 'setup' }));
    document.getElementById('commands').addEventListener('click', () => vscode.postMessage({ type: 'commands' }));
    document.getElementById('refresh').addEventListener('click', () => vscode.postMessage({ type: 'refresh' }));

    const profileButton = document.getElementById('openProfile');
    if (profileButton) {
      profileButton.addEventListener('click', () => vscode.postMessage({ type: 'openProfile' }));
    }
  </script>
</body>
</html>`;
}

class CortexDesktopControlCenterProvider {
  constructor() {
    this.webviewView = null;
  }

  async resolveWebviewView(webviewView) {
    this.webviewView = webviewView;
    webviewView.webview.options = { enableScripts: true };

    webviewView.onDidDispose(() => {
      if (this.webviewView === webviewView) {
        this.webviewView = null;
      }
    });

    webviewView.webview.onDidReceiveMessage(async message => {
      switch (message?.type) {
        case 'launch':
          await launchCortexDesktop();
          break;
        case 'launchRoot':
          await launchCortexDesktop({ requireWorkspace: true });
          break;
        case 'openProfile':
          await openWorkspaceProfile();
          break;
        case 'repo':
          await vscode.env.openExternal(vscode.Uri.parse(CORTEXDESKTOP_REPO_URL));
          break;
        case 'setup':
          await vscode.env.openExternal(vscode.Uri.parse(CORTEXDESKTOP_SETUP_URL));
          break;
        case 'commands':
          await vscode.commands.executeCommand('workbench.action.showCommands');
          break;
        case 'refresh':
        default:
          break;
      }

      await this.refresh();
    });

    await this.refresh();
  }

  async refresh() {
    if (!this.webviewView) {
      return;
    }

    try {
      const status = await collectControlCenterState();
      this.webviewView.webview.html = this.getHtml(status);
    } catch (error) {
      this.webviewView.webview.html = this.getErrorHtml(error);
    }
  }

  getErrorHtml(error) {
    const nonce = crypto.randomBytes(16).toString('base64');
    const message =
      error instanceof Error ? error.message : 'Unknown Control Center error';

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <style>
    body {
      font-family: var(--vscode-font-family);
      padding: 16px;
      color: var(--vscode-foreground);
      background: var(--vscode-sideBar-background);
    }
    .panel {
      border: 1px solid var(--vscode-errorForeground);
      border-radius: 8px;
      padding: 14px;
      background: color-mix(in srgb, var(--vscode-sideBar-background) 88%, black);
    }
    .title {
      color: var(--vscode-errorForeground);
      font-weight: 700;
      margin-bottom: 8px;
    }
    .message {
      color: var(--vscode-descriptionForeground);
      margin-bottom: 12px;
      line-height: 1.5;
    }
    button {
      border: 1px solid var(--vscode-button-border, transparent);
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      border-radius: 6px;
      padding: 8px 10px;
      cursor: pointer;
    }
  </style>
</head>
<body>
  <div class="panel">
    <div class="title">Control Center Error</div>
    <div class="message">${escapeHtml(message)}</div>
    <button id="refresh">Refresh</button>
  </div>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    document.getElementById('refresh').addEventListener('click', () => {
      vscode.postMessage({ type: 'refresh' });
    });
  </script>
</body>
</html>`;
  }

  getHtml(status) {
    const nonce = crypto.randomBytes(16).toString('base64');
    return renderControlCenterHtml(status, { nonce, platform: process.platform });
  }
}

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
  // ── Control Center (existing) ──
  const provider = new CortexDesktopControlCenterProvider();
  const refreshProvider = () => {
    void provider.refresh();
  };

  const lspBridge = createLspBridge();
  void lspBridge.refreshConfig();

  // ── Chat system ──
  const sessionManager = new SessionManager();
  const folders = vscode.workspace.workspaceFolders;
  if (folders && folders.length > 0) {
    sessionManager.setCwd(folders[0].uri.fsPath);
  }

  const chatController = new ChatController(sessionManager);
  const chatViewProvider = new CortexDesktopChatViewProvider(chatController);
  const chatPanelManager = new CortexDesktopChatPanelManager(chatController);

  // ── Diff content provider ──
  const diffProvider = new DiffContentProvider();
  const diffProviderReg = vscode.workspace.registerTextDocumentContentProvider(
    DIFF_SCHEME,
    diffProvider,
  );

  // ── Status bar ──
  const statusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100,
  );
  statusBarItem.text = '$(comment-discussion) Cortex Desktop';
  statusBarItem.tooltip = 'Open Cortex Desktop Chat';
  statusBarItem.command = 'cortexdesktop.openChat';
  statusBarItem.show();

  chatController.onDidChangeState((state) => {
    switch (state) {
      case 'streaming':
        statusBarItem.text = '$(sync~spin) Cortex Desktop';
        statusBarItem.tooltip = 'Cortex Desktop is generating...';
        break;
      case 'connected':
        statusBarItem.text = '$(comment-discussion) Cortex Desktop';
        statusBarItem.tooltip = 'Cortex Desktop connected';
        break;
      default:
        statusBarItem.text = '$(comment-discussion) Cortex Desktop';
        statusBarItem.tooltip = 'Open Cortex Desktop Chat';
        break;
    }
  });

  // ── Existing commands ──
  const startCommand = vscode.commands.registerCommand('cortexdesktop.start', async () => {
    await launchCortexDesktop();
  });

  const startInWorkspaceRootCommand = vscode.commands.registerCommand(
    'cortexdesktop.startInWorkspaceRoot',
    async () => {
      await launchCortexDesktop({ requireWorkspace: true });
    },
  );

  const openDocsCommand = vscode.commands.registerCommand('cortexdesktop.openDocs', async () => {
    await vscode.env.openExternal(vscode.Uri.parse(CORTEXDESKTOP_REPO_URL));
  });

  const openSetupDocsCommand = vscode.commands.registerCommand(
    'cortexdesktop.openSetupDocs',
    async () => {
      await vscode.env.openExternal(vscode.Uri.parse(CORTEXDESKTOP_SETUP_URL));
    },
  );

  const openWorkspaceProfileCommand = vscode.commands.registerCommand(
    'cortexdesktop.openWorkspaceProfile',
    async () => {
      await openWorkspaceProfile();
    },
  );

  const openUiCommand = vscode.commands.registerCommand('cortexdesktop.openControlCenter', async () => {
    await vscode.commands.executeCommand('workbench.view.extension.cortexdesktop');
  });

  // ── New chat commands ──
  const newChatCommand = vscode.commands.registerCommand('cortexdesktop.newChat', () => {
    chatController.stopSession();
    chatController.broadcast({ type: 'session_cleared' });
  });

  const openChatCommand = vscode.commands.registerCommand('cortexdesktop.openChat', () => {
    chatPanelManager.openPanel();
  });

  const resumeSessionCommand = vscode.commands.registerCommand('cortexdesktop.resumeSession', async () => {
    const sessions = await sessionManager.listSessions();
    if (sessions.length === 0) {
      await vscode.window.showInformationMessage('No sessions found to resume.');
      return;
    }
    const items = sessions.slice(0, 30).map(s => ({
      label: s.title || s.id,
      description: s.timeLabel,
      detail: s.preview,
      sessionId: s.id,
    }));
    const picked = await vscode.window.showQuickPick(items, {
      placeHolder: 'Select a session to resume',
    });
    if (picked) {
      chatController.stopSession();
      chatController.broadcast({ type: 'session_cleared' });
      await chatController.startSession({ sessionId: picked.sessionId });
    }
  });

  const abortChatCommand = vscode.commands.registerCommand('cortexdesktop.abortChat', () => {
    chatController.abort();
  });

  // ── Register providers ──
  const controlCenterProviderReg = vscode.window.registerWebviewViewProvider(
    'cortexdesktop.controlCenter',
    provider,
  );

  const chatViewProviderReg = vscode.window.registerWebviewViewProvider(
    'cortexdesktop.chat',
    chatViewProvider,
    { webviewOptions: { retainContextWhenHidden: true } },
  );

  const profileWatcher = vscode.workspace.createFileSystemWatcher(`**/${PROFILE_FILE_NAME}`);

  context.subscriptions.push(
    // existing
    startCommand,
    startInWorkspaceRootCommand,
    openDocsCommand,
    openSetupDocsCommand,
    openWorkspaceProfileCommand,
    openUiCommand,
    controlCenterProviderReg,
    // new chat
    newChatCommand,
    openChatCommand,
    resumeSessionCommand,
    abortChatCommand,
    chatViewProviderReg,
    diffProviderReg,
    statusBarItem,
    // watchers
    profileWatcher,
    vscode.workspace.onDidChangeConfiguration(event => {
      if (event.affectsConfiguration('cortexdesktop')) {
        refreshProvider();
        void lspBridge.refreshConfig();
      }
    }),
    vscode.workspace.onDidChangeWorkspaceFolders((e) => {
      refreshProvider();
      const folders = vscode.workspace.workspaceFolders;
      if (folders && folders.length > 0) {
        sessionManager.setCwd(folders[0].uri.fsPath);
      }
    }),
    vscode.window.onDidChangeActiveTextEditor(refreshProvider),
    profileWatcher.onDidCreate(refreshProvider),
    profileWatcher.onDidChange(refreshProvider),
    profileWatcher.onDidDelete(refreshProvider),
    // disposables
    { dispose: () => chatController.dispose() },
    { dispose: () => chatPanelManager.dispose() },
    { dispose: () => diffProvider.dispose() },
    { dispose: () => lspBridge.dispose() },
  );
}

function deactivate() {}

module.exports = {
  activate,
  deactivate,
  CortexDesktopControlCenterProvider,
  renderControlCenterHtml,
  resolveLaunchTargets,
  ChatController,
  CortexDesktopChatViewProvider,
  CortexDesktopChatPanelManager,
};
