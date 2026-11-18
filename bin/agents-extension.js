#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");

const repoRoot = path.resolve(__dirname, "..");

const ITEMS = {
  "mineru-pdf-router": {
    kind: "plugin",
    source: path.join(repoRoot, "mineru-pdf-router"),
    category: "Productivity",
  },
  "opencode-delegator": {
    kind: "plugin",
    source: path.join(repoRoot, "opencode-delegator"),
    category: "Productivity",
  },
  "codex-study-mode": {
    kind: "skill",
    source: path.join(repoRoot, "codex-study-mode"),
  },
  "python-project-design": {
    kind: "skill",
    source: path.join(repoRoot, "project-storage", "python-project-design"),
  },
};

const DEFAULT_ITEMS = ["mineru-pdf-router", "opencode-delegator", "codex-study-mode", "python-project-design"];

function usage(exitCode = 0) {
  const out = exitCode === 0 ? process.stdout : process.stderr;
  out.write(`Usage:
  agents-extension install [all|item...] [--dry-run] [--codex-home <path>] [--marketplace-root <path>]
  agents-extension list

Items:
  mineru-pdf-router
  opencode-delegator
  codex-study-mode
  python-project-design

Examples:
  npx github:Zzzaurak/Agents-extension install all
  npx github:Zzzaurak/Agents-extension install mineru-pdf-router codex-study-mode
  npx github:Zzzaurak/Agents-extension install all --codex-home ~/.codex
`);
  process.exit(exitCode);
}

function expandHome(value) {
  if (!value) {
    return value;
  }
  if (value === "~") {
    return os.homedir();
  }
  if (value.startsWith("~/")) {
    return path.join(os.homedir(), value.slice(2));
  }
  return value;
}

function parseArgs(argv) {
  const args = [...argv];
  const command = args.shift();
  const options = {
    dryRun: false,
    codexHome: process.env.CODEX_HOME || path.join(os.homedir(), ".codex"),
    marketplaceRoot: process.env.CODEX_PLUGIN_MARKETPLACE_HOME || path.join(os.homedir(), ".agents", "plugins"),
    items: [],
  };

  while (args.length > 0) {
    const arg = args.shift();
    if (arg === "--help" || arg === "-h") {
      usage(0);
    }
    if (arg === "--dry-run") {
      options.dryRun = true;
      continue;
    }
    if (arg === "--codex-home") {
      const value = args.shift();
      if (!value) {
        throw new Error("--codex-home requires a path.");
      }
      options.codexHome = value;
      continue;
    }
    if (arg === "--marketplace-root") {
      const value = args.shift();
      if (!value) {
        throw new Error("--marketplace-root requires a path.");
      }
      options.marketplaceRoot = value;
      continue;
    }
    if (arg.startsWith("--codex-home=")) {
      options.codexHome = arg.slice("--codex-home=".length);
      continue;
    }
    if (arg.startsWith("--marketplace-root=")) {
      options.marketplaceRoot = arg.slice("--marketplace-root=".length);
      continue;
    }
    options.items.push(arg);
  }

  options.codexHome = path.resolve(expandHome(options.codexHome));
  options.marketplaceRoot = path.resolve(expandHome(options.marketplaceRoot));
  return { command, options };
}

function selectedItems(rawItems) {
  if (rawItems.length === 0 || rawItems.includes("all")) {
    return DEFAULT_ITEMS;
  }
  for (const item of rawItems) {
    if (!ITEMS[item]) {
      throw new Error(`Unknown item: ${item}`);
    }
  }
  return [...new Set(rawItems)];
}

function shouldSkip(name) {
  return (
    name === ".DS_Store" ||
    name === "__pycache__" ||
    name === ".git" ||
    name === "node_modules" ||
    name.endsWith(".pyc")
  );
}

function copyDirectory(source, target, dryRun) {
  if (!fs.existsSync(source)) {
    throw new Error(`Missing source directory: ${source}`);
  }
  if (dryRun) {
    console.log(`[dry-run] replace ${target} <- ${source}`);
    return;
  }
  fs.rmSync(target, { recursive: true, force: true });
  fs.mkdirSync(target, { recursive: true });
  copyEntries(source, target);
}

function copyEntries(source, target) {
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    if (shouldSkip(entry.name)) {
      continue;
    }
    const from = path.join(source, entry.name);
    const to = path.join(target, entry.name);
    if (entry.isDirectory()) {
      fs.mkdirSync(to, { recursive: true });
      copyEntries(from, to);
      continue;
    }
    if (entry.isFile()) {
      fs.copyFileSync(from, to);
    }
  }
}

function readJson(filePath, fallback) {
  if (!fs.existsSync(filePath)) {
    return fallback;
  }
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function writeJson(filePath, value, dryRun) {
  if (dryRun) {
    console.log(`[dry-run] write ${filePath}`);
    return;
  }
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

function updateMarketplace(marketplacePath, pluginNames, dryRun) {
  const marketplace = readJson(marketplacePath, {
    name: "personal",
    interface: {
      displayName: "Personal",
    },
    plugins: [],
  });

  if (!Array.isArray(marketplace.plugins)) {
    marketplace.plugins = [];
  }
  if (!marketplace.name) {
    marketplace.name = "personal";
  }
  if (!marketplace.interface) {
    marketplace.interface = { displayName: "Personal" };
  }

  for (const name of pluginNames) {
    const item = ITEMS[name];
    const entry = {
      name,
      source: {
        source: "local",
        path: `./plugins/${name}`,
      },
      policy: {
        installation: "AVAILABLE",
        authentication: "ON_INSTALL",
      },
      category: item.category || "Productivity",
    };
    const index = marketplace.plugins.findIndex((plugin) => plugin && plugin.name === name);
    if (index === -1) {
      marketplace.plugins.push(entry);
    } else {
      marketplace.plugins[index] = {
        ...marketplace.plugins[index],
        ...entry,
      };
    }
  }

  writeJson(marketplacePath, marketplace, dryRun);
}

function install(options) {
  const names = selectedItems(options.items);
  const pluginNames = names.filter((name) => ITEMS[name].kind === "plugin");
  const skillNames = names.filter((name) => ITEMS[name].kind === "skill");
  // Codex resolves sources from the project root for .agents/plugins catalogs.
  const marketplaceParent = path.dirname(options.marketplaceRoot);
  const isCodexMarketplace = path.basename(options.marketplaceRoot) === "plugins"
    && path.basename(marketplaceParent) === ".agents";
  const marketplaceProjectRoot = isCodexMarketplace
    ? path.dirname(marketplaceParent)
    : options.marketplaceRoot;
  const pluginRoot = path.join(marketplaceProjectRoot, "plugins");
  const skillRoot = path.join(options.codexHome, "skills");

  for (const name of pluginNames) {
    copyDirectory(ITEMS[name].source, path.join(pluginRoot, name), options.dryRun);
  }
  if (pluginNames.length > 0) {
    updateMarketplace(path.join(options.marketplaceRoot, "marketplace.json"), pluginNames, options.dryRun);
  }

  for (const name of skillNames) {
    copyDirectory(ITEMS[name].source, path.join(skillRoot, name), options.dryRun);
  }

  console.log(`Installed: ${names.join(", ")}`);
  console.log(`Codex skills: ${skillRoot}`);
  console.log(`Plugin marketplace: ${path.join(options.marketplaceRoot, "marketplace.json")}`);
}

function main() {
  const { command, options } = parseArgs(process.argv.slice(2));
  if (!command || command === "--help" || command === "-h") {
    usage(0);
  }
  if (command === "list") {
    for (const [name, item] of Object.entries(ITEMS)) {
      console.log(`${name}\t${item.kind}`);
    }
    return;
  }
  if (command === "install") {
    install(options);
    return;
  }
  usage(1);
}

try {
  main();
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
