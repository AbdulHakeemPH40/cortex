/**
 * install_lsp_servers.js
 * Bootstrap script: downloads npm, then installs LSP servers for Cortex IDE.
 * Run with:  bin\node\node.exe install_lsp_servers.js
 */
const { execSync } = require('child_process');
const https = require('https');
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const PROJECT = __dirname;
const NODE = path.join(PROJECT, 'bin', 'node', 'node.exe');
const NPM_DIR = path.join(PROJECT, '_npm_bootstrap');

// Packages to install
const LSP_PACKAGES = [
  'typescript',
  'typescript-language-server',
  'bash-language-server',
  'vscode-langservers-extracted',
];

function download(url) {
  return new Promise((resolve, reject) => {
    const follow = (u) => {
      https.get(u, { headers: { 'User-Agent': 'cortex-ide' } }, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          return follow(res.headers.location);
        }
        if (res.statusCode !== 200) return reject(new Error(`HTTP ${res.statusCode} for ${u}`));
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => resolve(Buffer.concat(chunks)));
        res.on('error', reject);
      }).on('error', reject);
    };
    follow(url);
  });
}

async function getNpmTarballUrl() {
  const data = await download('https://registry.npmjs.org/npm/latest');
  const meta = JSON.parse(data.toString());
  console.log(`[+] npm version: ${meta.version}`);
  return meta.dist.tarball;
}

// Simple tar extractor for npm tarballs (handles ustar format)
function extractTar(buffer, destDir) {
  let offset = 0;
  while (offset < buffer.length - 512) {
    const header = buffer.slice(offset, offset + 512);
    if (header.every((b) => b === 0)) break; // end-of-archive

    const nameRaw = header.slice(0, 100).toString('utf8').replace(/\0/g, '');
    const prefix = header.slice(345, 500).toString('utf8').replace(/\0/g, '');
    const fullName = prefix ? prefix + '/' + nameRaw : nameRaw;
    const sizeOctal = header.slice(124, 136).toString('utf8').replace(/\0/g, '').trim();
    const size = parseInt(sizeOctal, 8) || 0;
    const type = header[156]; // 48='0' file, 53='5' dir

    offset += 512; // past header

    // Strip leading "package/" from npm tarballs
    const relPath = fullName.replace(/^package[\\/]/, '');
    const absPath = path.join(destDir, relPath);

    if (type === 53 || fullName.endsWith('/')) {
      // Directory
      fs.mkdirSync(absPath, { recursive: true });
    } else {
      // File
      fs.mkdirSync(path.dirname(absPath), { recursive: true });
      fs.writeFileSync(absPath, buffer.slice(offset, offset + size));
    }

    // Advance past file data (rounded up to 512-byte blocks)
    offset += Math.ceil(size / 512) * 512;
  }
}

async function bootstrapNpm() {
  console.log('[1/3] Downloading npm...');
  const tarballUrl = await getNpmTarballUrl();
  const tgzBuffer = await download(tarballUrl);

  console.log(`[1/3] Downloaded ${(tgzBuffer.length / 1024 / 1024).toFixed(1)} MB`);

  // Decompress .tar.gz
  const tarBuffer = zlib.gunzipSync(tgzBuffer);

  // Extract to _npm_bootstrap
  if (fs.existsSync(NPM_DIR)) fs.rmSync(NPM_DIR, { recursive: true, force: true });
  fs.mkdirSync(NPM_DIR, { recursive: true });
  extractTar(tarBuffer, NPM_DIR);

  console.log('[1/3] npm extracted to', NPM_DIR);
}

function runNpmInstall() {
  const npmCli = path.join(NPM_DIR, 'bin', 'npm-cli.js');
  if (!fs.existsSync(npmCli)) {
    throw new Error(`npm-cli.js not found at ${npmCli}`);
  }

  const pkgList = LSP_PACKAGES.join(' ');
  const cmd = `"${NODE}" "${npmCli}" install --save-dev ${pkgList}`;

  console.log(`[2/3] Installing LSP servers: ${pkgList}`);
  console.log(`      Command: ${cmd}`);

  // Add bundled node dir to PATH so postinstall scripts can find 'node'
  const nodeDir = path.dirname(NODE);
  const pathEnv = nodeDir + ';' + (process.env.PATH || '');

  execSync(cmd, {
    cwd: PROJECT,
    stdio: 'inherit',
    env: { ...process.env, PATH: pathEnv, NODE_PATH: '' },
  });

  console.log('[2/3] LSP servers installed successfully!');
}

function cleanup() {
  console.log('[3/3] Cleaning up bootstrap npm...');
  if (fs.existsSync(NPM_DIR)) {
    fs.rmSync(NPM_DIR, { recursive: true, force: true });
  }
  // Also remove the script itself
  console.log('[3/3] Done! You can now rebuild the .exe with:');
  console.log('      build_installer.bat');
}

async function main() {
  console.log('=== Cortex IDE — LSP Server Installer ===\n');
  try {
    await bootstrapNpm();
    runNpmInstall();
    cleanup();
    console.log('\n=== All LSP servers installed! ===');
    console.log('Supported languages: JavaScript, TypeScript, HTML, CSS, JSON, Bash');
  } catch (err) {
    console.error('\n[ERROR]', err.message || err);
    process.exit(1);
  }
}

main();
