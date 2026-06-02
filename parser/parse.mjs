#!/usr/bin/env node
/**
 * parse.mjs — Claude Code Usage Tracker parser.
 *
 * Reads ~/.claude/projects/ ** /*.jsonl into SQLite at ~/.claude/usage/usage.db.
 *
 * Design points (carried over from analyze-sessions.mjs):
 *   - One API response is split into multiple `type:"assistant"` JSONL entries,
 *     each carrying the same requestId / message.id but only the LAST carries
 *     the final output_tokens. We dedupe per file by requestId, keeping the
 *     row with max output_tokens, then UPSERT with MAX() across runs.
 *   - Subagent transcripts live at <project>/<sessionId>/subagents/agent-*.jsonl
 *     with sibling *.meta.json giving {agentType}. parent session_id is the
 *     <sessionId> dir.
 *   - Resumed sessions can replay history into a new .jsonl. The UNIQUE
 *     constraint on turns.request_id handles dedupe across runs and files.
 *
 * Self-tracking: a session is flagged is_tracker_overhead=1 when the first
 * non-meta user message starts with /usage, /usage-report, /usage-doc, or
 * /stage. Those tokens roll up under stage '_tracker_overhead_'.
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import readline from 'node:readline'
import Database from 'better-sqlite3'

const HOME = os.homedir()
// Data dir resolution MUST mirror Python's paths.py so the parser (writer) and
// the CLI/dashboard (reader) agree on where usage.db lives:
//   CU_DATA_DIR  >  ${CLAUDE_PLUGIN_ROOT}/data  >  legacy ~/.claude/usage
const USAGE_DIR = process.env.CU_DATA_DIR
  ? process.env.CU_DATA_DIR
  : process.env.CLAUDE_PLUGIN_ROOT
    ? path.join(process.env.CLAUDE_PLUGIN_ROOT, 'data')
    : path.join(HOME, '.claude', 'usage')
const PROJECTS_DIR = path.join(HOME, '.claude', 'projects')
const DB_PATH = path.join(USAGE_DIR, 'usage.db')
const STAGE_MAP_PATH = path.join(USAGE_DIR, 'stage_map.json')
const PROJECTS_PATH = path.join(USAGE_DIR, 'projects.json')

const TRACKER_CMD_RE = /^\s*\/(usage|usage-report|usage-doc|stage|project)\b/
const AGENT_LABEL_RE = /^agent-a([a-zA-Z_][\w-]*?)-[0-9a-f]{6,}$/
// Claude Code worktree convention: <parent-encoded-dir>--claude-worktrees-<branch>
// or <parent-encoded-dir>-claude-worktrees-<branch>. We strip the worktree
// suffix to find the parent project's encoded dir.
const WORKTREE_RE = /^(.+?)-{1,2}claude-worktrees-(.+)$/

// ---------------------------------------------------------------------------
// DB setup
// ---------------------------------------------------------------------------
const db = new Database(DB_PATH)
db.pragma('journal_mode = WAL')
db.pragma('foreign_keys = ON')

db.exec(`
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  project_path TEXT,
  project_dir TEXT,
  started_at TEXT,
  ended_at TEXT,
  parent_session_id TEXT,
  agent_type TEXT,
  is_tracker_overhead INTEGER DEFAULT 0,
  first_user_message TEXT
);
-- Schema migration: add project_dir if upgrading from an earlier version.
-- SQLite ignores the error if the column already exists.

CREATE TABLE IF NOT EXISTS turns (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  request_id TEXT UNIQUE,
  ts TEXT,
  model TEXT,
  input_tokens INTEGER DEFAULT 0,
  cache_creation_tokens INTEGER DEFAULT 0,
  cache_creation_1h_tokens INTEGER DEFAULT 0,
  cache_read_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  service_tier TEXT
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_ts ON turns(ts);

CREATE TABLE IF NOT EXISTS session_stage (
  session_id TEXT PRIMARY KEY,
  stage TEXT NOT NULL,
  source TEXT NOT NULL,
  classified_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_stage_stage ON session_stage(stage);

CREATE TABLE IF NOT EXISTS skill_invocations (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  skill_name TEXT NOT NULL,
  ts TEXT,
  UNIQUE(session_id, skill_name, ts)
);
CREATE INDEX IF NOT EXISTS idx_skill_name ON skill_invocations(skill_name);

CREATE TABLE IF NOT EXISTS parse_state (
  file_path TEXT PRIMARY KEY,
  last_byte_size INTEGER,
  last_mtime_ms INTEGER,
  last_parsed_at TEXT
);

-- Registered Claude Code projects/products. One row per product (mirrored from
-- projects.json so SQL queries can JOIN against it).
CREATE TABLE IF NOT EXISTS projects (
  name TEXT PRIMARY KEY,
  root_path TEXT,
  match_patterns TEXT,       -- JSON array of substrings
  docs_relpath TEXT DEFAULT 'docs/usage',
  created_at TEXT,
  notes TEXT
);

-- Per-session tool-use histogram: how many times each tool was called.
CREATE TABLE IF NOT EXISTS session_tools (
  session_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  count INTEGER DEFAULT 0,
  PRIMARY KEY (session_id, tool_name)
);
CREATE INDEX IF NOT EXISTS idx_session_tools_name ON session_tools(tool_name);

-- All distinct cwds the session passed through (cd's, worktrees, subdirs).
CREATE TABLE IF NOT EXISTS session_cwds (
  session_id TEXT NOT NULL,
  cwd TEXT NOT NULL,
  PRIMARY KEY (session_id, cwd)
);

-- All distinct git branches observed during the session.
CREATE TABLE IF NOT EXISTS session_branches (
  session_id TEXT NOT NULL,
  git_branch TEXT NOT NULL,
  PRIMARY KEY (session_id, git_branch)
);

-- Per-session attributionSkill / attributionPlugin counts (Claude Code's own
-- accounting of which plugin/skill drove each turn).
CREATE TABLE IF NOT EXISTS session_attribution (
  session_id TEXT NOT NULL,
  attribution_plugin TEXT,
  attribution_skill TEXT,
  count INTEGER DEFAULT 0,
  PRIMARY KEY (session_id, attribution_plugin, attribution_skill)
);
`)

// Migration guard for existing DBs: add cache_creation_1h_tokens if it doesn't exist.
try {
  db.prepare('ALTER TABLE turns ADD COLUMN cache_creation_1h_tokens INTEGER DEFAULT 0').run()
} catch (_) { /* column already exists in this DB */ }

// Idempotent migrations: add columns if they don't exist yet.
// SQLite ALTER TABLE has no IF NOT EXISTS for columns, so we try/catch.
for (const col of [
  "ALTER TABLE sessions ADD COLUMN project_dir TEXT",
  "ALTER TABLE sessions ADD COLUMN ai_title TEXT",
  "ALTER TABLE sessions ADD COLUMN project_name TEXT",
  "ALTER TABLE sessions ADD COLUMN worktree_branch TEXT",
  "ALTER TABLE sessions ADD COLUMN subagent_description TEXT",
]) {
  try { db.prepare(col).run() } catch { /* column already exists */ }
}
db.exec(`
CREATE INDEX IF NOT EXISTS idx_sessions_project_dir ON sessions(project_dir);
CREATE INDEX IF NOT EXISTS idx_sessions_project_name ON sessions(project_name);
CREATE INDEX IF NOT EXISTS idx_sessions_ai_title ON sessions(ai_title);
`)

const stmt = {
  upsertSession: db.prepare(`
    INSERT INTO sessions (session_id, project_path, project_dir, started_at, ended_at, parent_session_id, agent_type, is_tracker_overhead, first_user_message, ai_title, project_name, worktree_branch, subagent_description)
    VALUES (@session_id, @project_path, @project_dir, @started_at, @ended_at, @parent_session_id, @agent_type, @is_tracker_overhead, @first_user_message, @ai_title, @project_name, @worktree_branch, @subagent_description)
    ON CONFLICT(session_id) DO UPDATE SET
      project_path = COALESCE(excluded.project_path, sessions.project_path),
      project_dir = COALESCE(excluded.project_dir, sessions.project_dir),
      started_at = COALESCE(MIN(sessions.started_at, excluded.started_at), excluded.started_at),
      ended_at = COALESCE(MAX(sessions.ended_at, excluded.ended_at), excluded.ended_at),
      parent_session_id = COALESCE(excluded.parent_session_id, sessions.parent_session_id),
      agent_type = COALESCE(excluded.agent_type, sessions.agent_type),
      is_tracker_overhead = MAX(sessions.is_tracker_overhead, excluded.is_tracker_overhead),
      first_user_message = COALESCE(sessions.first_user_message, excluded.first_user_message),
      ai_title = COALESCE(excluded.ai_title, sessions.ai_title),
      project_name = COALESCE(excluded.project_name, sessions.project_name),
      worktree_branch = COALESCE(excluded.worktree_branch, sessions.worktree_branch),
      subagent_description = COALESCE(excluded.subagent_description, sessions.subagent_description)
  `),
  upsertTurn: db.prepare(`
    INSERT INTO turns (session_id, request_id, ts, model, input_tokens, cache_creation_tokens, cache_creation_1h_tokens, cache_read_tokens, output_tokens, service_tier)
    VALUES (@session_id, @request_id, @ts, @model, @input_tokens, @cache_creation_tokens, @cache_creation_1h_tokens, @cache_read_tokens, @output_tokens, @service_tier)
    ON CONFLICT(request_id) DO UPDATE SET
      output_tokens = MAX(turns.output_tokens, excluded.output_tokens),
      input_tokens = MAX(turns.input_tokens, excluded.input_tokens),
      cache_creation_tokens = MAX(turns.cache_creation_tokens, excluded.cache_creation_tokens),
      cache_creation_1h_tokens = MAX(turns.cache_creation_1h_tokens, excluded.cache_creation_1h_tokens),
      cache_read_tokens = MAX(turns.cache_read_tokens, excluded.cache_read_tokens),
      model = COALESCE(excluded.model, turns.model),
      service_tier = COALESCE(excluded.service_tier, turns.service_tier)
  `),
  insertStageIfAbsent: db.prepare(`
    INSERT OR IGNORE INTO session_stage (session_id, stage, source, classified_at)
    VALUES (@session_id, @stage, @source, @classified_at)
  `),
  insertSkill: db.prepare(`
    INSERT OR IGNORE INTO skill_invocations (session_id, skill_name, ts)
    VALUES (@session_id, @skill_name, @ts)
  `),
  upsertParseState: db.prepare(`
    INSERT INTO parse_state (file_path, last_byte_size, last_mtime_ms, last_parsed_at)
    VALUES (@file_path, @last_byte_size, @last_mtime_ms, @last_parsed_at)
    ON CONFLICT(file_path) DO UPDATE SET
      last_byte_size = excluded.last_byte_size,
      last_mtime_ms = excluded.last_mtime_ms,
      last_parsed_at = excluded.last_parsed_at
  `),
  getParseState: db.prepare(`SELECT last_byte_size, last_mtime_ms FROM parse_state WHERE file_path = ?`),

  upsertSessionTool: db.prepare(`
    INSERT INTO session_tools (session_id, tool_name, count)
    VALUES (@session_id, @tool_name, @count)
    ON CONFLICT(session_id, tool_name) DO UPDATE SET count = excluded.count
  `),
  insertCwdIfAbsent: db.prepare(`
    INSERT OR IGNORE INTO session_cwds (session_id, cwd) VALUES (@session_id, @cwd)
  `),
  insertBranchIfAbsent: db.prepare(`
    INSERT OR IGNORE INTO session_branches (session_id, git_branch) VALUES (@session_id, @git_branch)
  `),
  upsertAttribution: db.prepare(`
    INSERT INTO session_attribution (session_id, attribution_plugin, attribution_skill, count)
    VALUES (@session_id, @attribution_plugin, @attribution_skill, @count)
    ON CONFLICT(session_id, attribution_plugin, attribution_skill) DO UPDATE SET count = excluded.count
  `),
  upsertProjectRegistry: db.prepare(`
    INSERT INTO projects (name, root_path, match_patterns, docs_relpath, created_at, notes)
    VALUES (@name, @root_path, @match_patterns, @docs_relpath, @created_at, @notes)
    ON CONFLICT(name) DO UPDATE SET
      root_path = excluded.root_path,
      match_patterns = excluded.match_patterns,
      docs_relpath = COALESCE(excluded.docs_relpath, projects.docs_relpath),
      notes = COALESCE(excluded.notes, projects.notes)
  `),
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function loadStageMap() {
  try {
    const raw = JSON.parse(fs.readFileSync(STAGE_MAP_PATH, 'utf8'))
    return raw.mappings || {}
  } catch {
    return {}
  }
}

const stageMap = loadStageMap()

// ---------------------------------------------------------------------------
// Projects registry
// ---------------------------------------------------------------------------
function loadProjects() {
  try {
    const raw = JSON.parse(fs.readFileSync(PROJECTS_PATH, 'utf8'))
    return raw.projects || {}
  } catch {
    return {}
  }
}

// Mirror projects.json into the SQLite registry. Idempotent; safe to run each parse.
function syncProjectsRegistry() {
  const projects = loadProjects()
  const now = new Date().toISOString()
  for (const [name, cfg] of Object.entries(projects)) {
    if (name.startsWith('_')) continue
    stmt.upsertProjectRegistry.run({
      name,
      root_path: cfg.root_path || null,
      match_patterns: JSON.stringify(cfg.match_patterns || []),
      docs_relpath: cfg.docs_relpath || 'docs/usage',
      created_at: cfg.created_at || now,
      notes: cfg.notes || null,
    })
  }
  return projects
}

const projects = syncProjectsRegistry()

// Strip Claude Code's worktree suffix to find the parent project's encoded dir.
// Example: '-Users-me-proj-myapp--claude-worktrees-spike-x' -> {
//   parent: '-Users-me-proj-myapp', branch: 'spike-x'
// }
function unwrapWorktree(projectDir) {
  if (!projectDir) return { parent: projectDir, branch: null }
  const m = projectDir.match(WORKTREE_RE)
  if (!m) return { parent: projectDir, branch: null }
  return { parent: m[1], branch: m[2] }
}

// Find which registered project (if any) owns this session. We match against
// the worktree's parent dir so worktrees automatically roll up.
function resolveProjectName(projectPath, projectDir) {
  const { parent, branch } = unwrapWorktree(projectDir)
  const parentDecoded = decodeProjectPath(parent)
  for (const [name, cfg] of Object.entries(projects)) {
    if (name.startsWith('_')) continue
    const patterns = cfg.match_patterns || []
    for (const needle of patterns) {
      if (
        (projectPath && projectPath.includes(needle)) ||
        (projectDir && projectDir.includes(needle)) ||
        (parent && parent.includes(needle)) ||
        (parentDecoded && parentDecoded.includes(needle))
      ) {
        return { name, worktree_branch: branch }
      }
    }
  }
  return { name: null, worktree_branch: branch }
}

// Substring-matches the stage_map needle against BOTH the decoded path
// (user-friendly) and the encoded directory name (canonical on disk).
// This is necessary because Claude Code's cwd-encoding (path sep -> "-") is
// lossy for directories that actually contain a dash or a space.
function matchStage(projectPath, projectDir) {
  for (const [needle, stage] of Object.entries(stageMap)) {
    if (needle.startsWith('_')) continue
    if ((projectPath && projectPath.includes(needle)) ||
        (projectDir && projectDir.includes(needle))) {
      return stage
    }
  }
  return null
}

// Claude Code encodes cwd by replacing each path separator with '-'.
// Example: -Users-kpujari-Documents-Claude-Projects-agrisync -> /Users/kpujari/Documents/Claude/Projects/agrisync
// This is lossy (real '-' in dir names collides) but matches Claude Code's own scheme.
function decodeProjectPath(encoded) {
  if (!encoded) return null
  return encoded.replace(/-/g, '/')
}

function* walk(dir) {
  let ents
  try {
    ents = fs.readdirSync(dir, { withFileTypes: true })
  } catch {
    return
  }
  for (const e of ents) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) yield* walk(p)
    else if (e.isFile() && e.name.endsWith('.jsonl')) yield p
  }
}

function classifyFile(p) {
  const rel = path.relative(PROJECTS_DIR, p)
  const parts = rel.split(path.sep)
  const project = parts[0]
  const subIdx = parts.indexOf('subagents')
  if (subIdx !== -1) {
    const parentSessionId = parts[subIdx - 1]
    const base = path.basename(p, '.jsonl')
    const meta = readSubagentMeta(p, base)
    return {
      project,
      sessionId: `${parentSessionId}::${base}`,
      kind: 'subagent',
      parentSessionId,
      agentType: meta.agentType,
      subagentDescription: meta.description,
    }
  }
  return {
    project,
    sessionId: path.basename(p, '.jsonl'),
    kind: 'main',
    parentSessionId: null,
    agentType: null,
    subagentDescription: null,
  }
}

function readSubagentMeta(jsonlPath, base) {
  // Sidecar .meta.json carries the agent_type and the description (the Task tool
  // prompt summary). Description fallback to 'prompt' guards against an Anthropic
  // rename. If neither file nor field exist, fall back to the filename regex.
  const metaPath = jsonlPath.replace(/\.jsonl$/, '.meta.json')
  try {
    const m = JSON.parse(fs.readFileSync(metaPath, 'utf8'))
    if (m && typeof m === 'object') {
      const agentType = typeof m.agentType === 'string' ? m.agentType : null
      const description = (typeof m.description === 'string' && m.description)
        || (typeof m.prompt === 'string' && m.prompt)
        || null
      if (agentType) return { agentType, description }
    }
  } catch { /* no meta */ }
  const m = base.match(AGENT_LABEL_RE)
  return { agentType: m ? m[1] : 'fork', description: null }
}

function extractUserText(entry) {
  const msg = entry.message
  if (!msg) return null
  if (entry.isMeta || entry.isSidechain || entry.isCompactSummary) return null
  const c = msg.content
  if (typeof c === 'string') return c
  if (Array.isArray(c)) {
    for (const item of c) {
      if (item && item.type === 'text' && typeof item.text === 'string') return item.text
    }
  }
  return null
}

// ---------------------------------------------------------------------------
// Per-file parse
// ---------------------------------------------------------------------------
async function processFile(p, stats) {
  const info = classifyFile(p)
  const rl = readline.createInterface({
    input: fs.createReadStream(p, { encoding: 'utf8' }),
    crlfDelay: Infinity,
  })

  const fileApiCalls = new Map()
  const skillInvocs = []
  const toolCounts = new Map()               // tool_name -> count (per session)
  const cwds = new Set()                     // distinct cwds touched
  const branches = new Set()                 // distinct gitBranches touched
  const attributionCounts = new Map()        // "plugin\x00skill" -> count
  let firstTs = null
  let lastTs = null
  let firstUserMessage = null
  let aiTitle = null

  for await (const line of rl) {
    if (!line) continue
    let e
    try { e = JSON.parse(line) } catch { continue }

    // Capture cross-cutting signals from any entry.
    if (typeof e.cwd === 'string' && e.cwd) cwds.add(e.cwd)
    if (typeof e.gitBranch === 'string' && e.gitBranch) branches.add(e.gitBranch)
    if (e.type === 'ai-title' && typeof e.aiTitle === 'string' && !aiTitle) {
      aiTitle = e.aiTitle.slice(0, 200)
    }
    if (e.attributionPlugin || e.attributionSkill) {
      const key = `${e.attributionPlugin || ''}\x00${e.attributionSkill || ''}`
      attributionCounts.set(key, (attributionCounts.get(key) || 0) + 1)
    }

    if (e.timestamp) {
      const ts = Date.parse(e.timestamp)
      if (!isNaN(ts)) {
        if (firstTs === null || ts < firstTs) firstTs = ts
        if (lastTs === null || ts > lastTs) lastTs = ts
      }
    }

    if (e.type === 'user' && firstUserMessage === null) {
      const text = extractUserText(e)
      if (text) firstUserMessage = text.slice(0, 500)
    }

    if (e.type === 'assistant') {
      const msg = e.message || {}
      if (Array.isArray(msg.content)) {
        for (const c of msg.content) {
          if (c && c.type === 'tool_use' && typeof c.name === 'string') {
            toolCounts.set(c.name, (toolCounts.get(c.name) || 0) + 1)
            if (c.name === 'Skill' && c.input && c.input.skill) {
              skillInvocs.push({ skill_name: String(c.input.skill), ts: e.timestamp })
            }
          }
        }
      }
      const usage = msg.usage
      if (!usage) continue
      const key = e.requestId || msg.id
      if (!key) continue
      const prev = fileApiCalls.get(key)
      const out = usage.output_tokens || 0
      if (!prev || out >= (prev.usage.output_tokens || 0)) {
        fileApiCalls.set(key, { usage, ts: e.timestamp, model: msg.model || null })
      }
    }
  }

  const isOverhead = firstUserMessage && TRACKER_CMD_RE.test(firstUserMessage) ? 1 : 0
  const projectPath = decodeProjectPath(info.project)
  // Subagent sessions inherit parent's project_dir for resolution purposes,
  // since the subagent file lives under the parent's project tree.
  const resolution = resolveProjectName(projectPath, info.project)

  const tx = db.transaction(() => {
    stmt.upsertSession.run({
      session_id: info.sessionId,
      project_path: projectPath,
      project_dir: info.project,
      started_at: firstTs ? new Date(firstTs).toISOString() : null,
      ended_at: lastTs ? new Date(lastTs).toISOString() : null,
      parent_session_id: info.parentSessionId,
      agent_type: info.agentType,
      is_tracker_overhead: isOverhead,
      first_user_message: firstUserMessage,
      ai_title: aiTitle,
      project_name: resolution.name,
      worktree_branch: resolution.worktree_branch,
      subagent_description: info.subagentDescription || null,
    })

    // Per-session tool histogram (replaces prior counts on re-parse).
    for (const [name, count] of toolCounts) {
      stmt.upsertSessionTool.run({ session_id: info.sessionId, tool_name: name, count })
    }
    for (const c of cwds) {
      stmt.insertCwdIfAbsent.run({ session_id: info.sessionId, cwd: c })
    }
    for (const b of branches) {
      stmt.insertBranchIfAbsent.run({ session_id: info.sessionId, git_branch: b })
    }
    for (const [key, count] of attributionCounts) {
      const [plugin, skill] = key.split('\x00')
      stmt.upsertAttribution.run({
        session_id: info.sessionId,
        attribution_plugin: plugin || null,
        attribution_skill: skill || null,
        count,
      })
    }

    for (const [key, { usage, ts, model }] of fileApiCalls) {
      stmt.upsertTurn.run({
        session_id: info.sessionId,
        request_id: key,
        ts: ts || null,
        model: model,
        input_tokens: usage.input_tokens || 0,
        cache_creation_tokens: usage.cache_creation_input_tokens || 0,
        cache_creation_1h_tokens: usage.cache_creation_1h_input_tokens || 0,
        cache_read_tokens: usage.cache_read_input_tokens || 0,
        output_tokens: usage.output_tokens || 0,
        service_tier: usage.service_tier || null,
      })
    }

    for (const s of skillInvocs) {
      stmt.insertSkill.run({
        session_id: info.sessionId,
        skill_name: s.skill_name,
        ts: s.ts || null,
      })
    }

    if (isOverhead) {
      stmt.insertStageIfAbsent.run({
        session_id: info.sessionId,
        stage: '_tracker_overhead_',
        source: 'overhead_detect',
        classified_at: new Date().toISOString(),
      })
    } else {
      const matched = matchStage(projectPath, info.project)
      if (matched) {
        stmt.insertStageIfAbsent.run({
          session_id: info.sessionId,
          stage: matched,
          source: 'cwd_map',
          classified_at: new Date().toISOString(),
        })
      }
    }

    stmt.upsertParseState.run({
      file_path: p,
      last_byte_size: stats.size,
      last_mtime_ms: stats.mtimeMs | 0,
      last_parsed_at: new Date().toISOString(),
    })
  })
  tx()
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
async function main() {
  const verbose = process.argv.includes('--verbose')
  const force = process.argv.includes('--force')
  const t0 = Date.now()
  let parsed = 0
  let skipped = 0

  for (const p of walk(PROJECTS_DIR)) {
    let stats
    try { stats = fs.statSync(p) } catch { continue }
    if (!force) {
      const prev = stmt.getParseState.get(p)
      if (prev && prev.last_byte_size === stats.size && prev.last_mtime_ms === (stats.mtimeMs | 0)) {
        skipped++
        continue
      }
    }
    try {
      await processFile(p, stats)
      parsed++
      if (verbose) console.error(`  parsed ${p}`)
    } catch (err) {
      console.error(`  ERROR ${p}: ${err.message}`)
    }
  }

  const elapsed = Date.now() - t0
  const counts = {
    sessions: db.prepare('SELECT COUNT(*) as c FROM sessions').get().c,
    sessions_with_project: db.prepare('SELECT COUNT(*) as c FROM sessions WHERE project_name IS NOT NULL').get().c,
    sessions_with_ai_title: db.prepare('SELECT COUNT(*) as c FROM sessions WHERE ai_title IS NOT NULL').get().c,
    turns: db.prepare('SELECT COUNT(*) as c FROM turns').get().c,
    skills: db.prepare('SELECT COUNT(*) as c FROM skill_invocations').get().c,
    staged: db.prepare('SELECT COUNT(*) as c FROM session_stage').get().c,
    projects: db.prepare('SELECT COUNT(*) as c FROM projects').get().c,
    session_tools: db.prepare('SELECT COUNT(*) as c FROM session_tools').get().c,
    session_cwds: db.prepare('SELECT COUNT(*) as c FROM session_cwds').get().c,
    session_branches: db.prepare('SELECT COUNT(*) as c FROM session_branches').get().c,
    session_attribution: db.prepare('SELECT COUNT(*) as c FROM session_attribution').get().c,
  }
  console.log(JSON.stringify({
    parsed_files: parsed,
    skipped_files: skipped,
    elapsed_ms: elapsed,
    db_counts: counts,
    db_path: DB_PATH,
  }, null, 2))
}

main().catch(e => {
  console.error(e)
  process.exit(1)
})
