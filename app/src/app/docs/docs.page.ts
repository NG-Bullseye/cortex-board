import { Component } from '@angular/core';

interface SystemNode {
  name: string;
  type: 'mcp' | 'agent' | 'ui' | 'infra' | 'sensor';
  port?: number;
  status?: string;
  description: string;
  tools?: string[];
  schedule?: string;
  outputs?: string[];
}

interface DataFlow {
  name: string;
  steps: string[];
}

interface Endpoint {
  method: string;
  path: string;
  description: string;
}

interface ServiceEndpoints {
  name: string;
  port: number;
  baseUrl: string;
  endpoints: Endpoint[];
}

interface ModuleInfo {
  name: string;
  lines: number;
  responsibility: string;
}

interface DesignPattern {
  name: string;
  where: string;
  description: string;
}

@Component({
  selector: 'app-docs',
  templateUrl: 'docs.page.html',
  styleUrls: ['docs.page.scss'],
  standalone: false,
})
export class DocsPage {
  activeTab: 'architecture' | 'agents' | 'flows' | 'repos' | 'endpoints' | 'codebase' = 'architecture';

  mcpServers: SystemNode[] = [
    {
      name: 'ha-functions-mcp',
      type: 'mcp',
      port: 8901,
      description: 'HA tool bridge: dynamic tools from functions.txt, entity management, syslog, Spotify, snapshots',
      tools: ['ha__snapshot', 'ha__list_automations', 'ha__execute_services', 'ha__spotify_*', 'ha__trace_entity', 'ha__log', 'ha__logs', 'meta__*'],
    },
    {
      name: 'cortex-mcp',
      type: 'mcp',
      port: 8900,
      description: 'Cortex Engine: JSON slot configs, predict/apply, CYD slots, feed, REST API, dashboard',
      tools: ['cortex__predict', 'cortex__apply', 'cortex__read', 'cortex__status', 'cortex__blackout', 'cortex__rebound', 'cyd__set_slot', 'cyd__get_slots'],
    },
    {
      name: 'claude-chat',
      type: 'mcp',
      port: 8765,
      description: 'Telegram session handler, message buffer, HA conversation bridge',
      tools: ['/chat', '/health'],
    },
    {
      name: 'speech-mcp',
      type: 'mcp',
      port: 8902,
      description: 'Unified STT/TTS: WhisperX + Qwen3, Athom USB Mic',
      tools: ['speech__listen', 'speech__transcribe', 'speech__tts', 'speech__record_start', 'speech__record_stop'],
    },
    {
      name: 'worker-mcp',
      type: 'mcp',
      port: 8903,
      description: 'Self-healing agent: bug analysis (Haiku) + fix execution',
      tools: ['worker__analyze', 'worker__approve', 'worker__reject', 'worker__quick_fix', 'worker__jobs'],
    },
    {
      name: 'nmap-mcp',
      type: 'mcp',
      description: 'Network scanning',
      tools: ['nmap__scan'],
    },
    {
      name: 'gdrive-mcp',
      type: 'mcp',
      description: 'Google Drive access',
      tools: ['gdrive__list', 'gdrive__download'],
    },
    {
      name: 'location-osm',
      type: 'mcp',
      description: 'Geocoding via OpenStreetMap',
      tools: ['location__geocode'],
    },
  ];

  agents: SystemNode[] = [
    {
      name: 'Cortex Slot Trigger',
      type: 'agent',
      description: 'Daemon: sleeps until next slot, runs predict, calls Haiku controller, applies corrections. Orchestrates watchdog + management agents.',
      schedule: 'daemon (systemd)',
      outputs: ['HA services (light/music)', 'Telegram logbook', 'Syslog'],
    },
    {
      name: 'Watchdog Agent',
      type: 'agent',
      description: 'Protocol-based health checks: Docker, HA API, container logs, lights-away. Diff engine only alerts on NEW issues.',
      schedule: 'every slot (~30min)',
      outputs: ['Feed (CYD)', 'Telegram', 'watchdog_alerts.md', 'Syslog'],
    },
    {
      name: 'Management Agent',
      type: 'agent',
      description: 'Personal assistant: Calendar, DVB departures, CYD display, Telegram briefings (8/14/18h). Includes Active Thinking (Claude Haiku).',
      schedule: 'every slot (~30min)',
      outputs: ['CYD display', 'Telegram briefing', 'Feed', 'brain.md', 'Syslog'],
    },
    {
      name: 'Active Thinking',
      type: 'agent',
      description: 'LLM reasoning: user-state detection, anomaly scan, brain.md update. Part of Management Agent.',
      schedule: '23:00 Mo-Do+So, 05:00 Fr-Sa',
      outputs: ['run_DATE.md', 'brain.md', 'Telegram', 'Anomaly fixes'],
    },
    {
      name: 'Telegram Bot',
      type: 'agent',
      description: 'AppDaemon app: message buffering, /c commands, voice transcription relay.',
      schedule: 'always-on (AppDaemon)',
      outputs: ['telegram_buffer.txt', 'HA events'],
    },
  ];

  dataFlows: DataFlow[] = [
    {
      name: 'Voice Command (Alexa)',
      steps: ['Alexa', 'HA Webhook', 'Extended OpenAI Conv', 'claude-chat HTTP', 'Claude API + MCP', 'HA Services', 'Devices'],
    },
    {
      name: 'Telegram Chat',
      steps: ['User', 'Telegram Bot (AppDaemon)', 'Buffer', '/c command', 'claude-chat', 'Claude API', 'Response', 'Telegram'],
    },
    {
      name: 'Slot Trigger Loop',
      steps: ['cortex-mcp /api/next_slot', 'Sleep until slot', 'Sleep guard check', 'Away check', 'cortex__predict', 'Haiku controller', 'cortex__apply', 'HA Services'],
    },
    {
      name: 'CYD Display',
      steps: ['Agents post to feed', 'cortex-mcp /api/feed', 'ESPHome native API', 'CYD Panel'],
    },
    {
      name: 'Monitoring',
      steps: ['Watchdog Agent', 'HealthCheck Protocol (Docker/HA/Logs/Lights)', 'DiffEngine', 'Alerter (feed + telegram + syslog)'],
    },
    {
      name: 'Self-Healing',
      steps: ['Watchdog detects issue', 'CYD feed (bug button)', 'User taps', 'worker-mcp /analyze', 'Haiku diagnosis', 'User approves', '/approve executes fix'],
    },
    {
      name: 'Voice Input (Hub Mic)',
      steps: ['CYD VOICE btn', 'HA service call', 'speech-mcp /listen', 'Athom USB Mic', 'WhisperX STT', 'Transcript to CYD'],
    },
  ];

  repos = [
    { name: 'cortex-mcp (nabu-mcp)', purpose: 'Engine configs + CYD slots + feed + REST API', port: 8900, type: 'MCP (HTTP)' },
    { name: 'ha-functions-mcp', purpose: 'HA tool bridge + function executor + syslog', port: 8901, type: 'MCP (stdio)' },
    { name: 'speech-mcp', purpose: 'Unified STT/TTS interface', port: 8902, type: 'MCP (HTTP)' },
    { name: 'worker-mcp', purpose: 'Self-healing bug analysis + fix', port: 8903, type: 'MCP (HTTP)' },
    { name: 'claude-chat-service', purpose: 'HA conversation bridge', port: 8765, type: 'HTTP Service' },
    { name: 'cortex-dashboard', purpose: 'Angular web UI (Schedule/Entities/Docs)', port: 4200, type: 'SPA' },
    { name: 'nabu-website', purpose: 'Product landing page', port: null, type: 'Static HTML' },
    { name: 'nabu-cli', purpose: 'CLI wrapper', port: null, type: 'CLI' },
  ];

  infrastructure = [
    { name: 'homeassistant', port: 8123, type: 'Docker' },
    { name: 'appdaemon', port: 5050, type: 'Docker' },
    { name: 'mosquitto3', port: 1883, type: 'Docker' },
    { name: 'portainer', port: 9000, type: 'Docker' },
    { name: 'zigbee2mqtt', port: null, type: 'Docker' },
  ];

  serviceEndpoints: ServiceEndpoints[] = [
    {
      name: 'cortex-mcp',
      port: 8900,
      baseUrl: 'http://localhost:8900',
      endpoints: [
        { method: 'GET', path: '/health', description: 'Health check + tool count' },
        { method: 'GET', path: '/api/status', description: 'Engine zone states + logs + config summary' },
        { method: 'GET', path: '/api/schedule', description: 'Full schedule (licht + musik, both day profiles)' },
        { method: 'GET', path: '/api/tree', description: 'Config directory structure' },
        { method: 'GET', path: '/api/entities', description: 'Entity activity from engine logs' },
        { method: 'GET', path: '/api/predict', description: 'Soll vs Ist comparison (?zone=pc)' },
        { method: 'GET', path: '/api/next_slot', description: 'Next slot change time + seconds' },
        { method: 'GET', path: '/api/sleep_guard', description: 'Is user sleeping? (zone + time + lights)' },
        { method: 'GET', path: '/api/feed', description: 'Get feed messages (CYD display)' },
        { method: 'POST', path: '/api/feed', description: 'Post feed message {msg, severity, fixable}' },
        { method: 'POST', path: '/api/feed/fix', description: 'CYD bug button: forward to worker {id}' },
        { method: 'POST', path: '/api/apply', description: 'Apply entity states {entity_id: desired}' },
        { method: 'POST', path: '/api/apply_current_slot', description: 'Apply current slot config for zone' },
        { method: 'GET', path: '/api/automation/status', description: 'Is cortex-slot-trigger running?' },
        { method: 'POST', path: '/api/automation/on', description: 'Start slot trigger (requires API key)' },
        { method: 'POST', path: '/api/automation/off', description: 'Stop slot trigger (requires API key)' },
      ],
    },
    {
      name: 'ha-functions-mcp',
      port: 8901,
      baseUrl: 'stdio (MCP protocol)',
      endpoints: [
        { method: 'MCP', path: 'ha__snapshot', description: 'Position/music/lights/switches/anomalies' },
        { method: 'MCP', path: 'ha__list_automations', description: 'Categorized automation list (filter=keyword)' },
        { method: 'MCP', path: 'ha__trace_entity', description: 'State change trace with source chain' },
        { method: 'MCP', path: 'ha__log / ha__logs', description: 'Central syslog write/read' },
        { method: 'MCP', path: 'ha__manage_entity', description: 'Entity registry: list_dead/disable/delete' },
        { method: 'MCP', path: 'meta__*', description: 'CRUD for functions.txt tool definitions' },
      ],
    },
    {
      name: 'speech-mcp',
      port: 8902,
      baseUrl: 'http://localhost:8902',
      endpoints: [
        { method: 'GET', path: '/health', description: 'State: IDLE/LISTENING/PROCESSING' },
        { method: 'POST', path: '/listen', description: 'Record N seconds + transcribe {duration}' },
        { method: 'POST', path: '/record/start', description: 'Start async recording' },
        { method: 'POST', path: '/record/stop', description: 'Stop recording, return file path' },
        { method: 'POST', path: '/transcribe', description: 'Upload audio for STT (multipart)' },
        { method: 'POST', path: '/transcribe/telegram', description: 'Transcribe Telegram voice {file_id}' },
        { method: 'POST', path: '/tts', description: 'Text-to-speech {text, voice} -> WAV' },
      ],
    },
    {
      name: 'worker-mcp',
      port: 8903,
      baseUrl: 'http://localhost:8903',
      endpoints: [
        { method: 'GET', path: '/health', description: 'Status + job count' },
        { method: 'GET', path: '/jobs', description: 'Recent jobs (?limit=N)' },
        { method: 'POST', path: '/analyze', description: 'Analyze bug via Haiku {bug, context}' },
        { method: 'POST', path: '/approve', description: 'Execute proposed fix {job_id}' },
        { method: 'POST', path: '/reject', description: 'Reject fix {job_id, reason}' },
        { method: 'POST', path: '/quick-fix', description: 'Auto-analyze + fix if safe {bug}' },
      ],
    },
    {
      name: 'claude-chat',
      port: 8765,
      baseUrl: 'http://172.20.0.1:8765',
      endpoints: [
        { method: 'GET', path: '/health', description: 'Health check' },
        { method: 'POST', path: '/chat', description: 'Process message {prompt} -> {response, session_id}' },
      ],
    },
  ];

  // ─── Codebase Architecture Tab ──────────────────────────────────────────

  cortexMcpModules: ModuleInfo[] = [
    { name: 'models.py', lines: 155, responsibility: 'Dataclasses, Enums (EntityState, DesiredState, FeedEntry, SlotInfo, Zone, Severity)' },
    { name: 'config.py', lines: 190, responsibility: 'ConfigRepository: slot parsing, $ref resolution, defaults, tree, managed entities' },
    { name: 'ha_client.py', lines: 170, responsibility: 'HAClient: injected httpx.AsyncClient, apply, detect_zone, check_sleep' },
    { name: 'feed.py', lines: 80, responsibility: 'FeedBuffer: bounded deque + JSON persistence for CYD' },
    { name: 'logging_util.py', lines: 45, responsibility: 'SyslogWriter: flock-safe JSONL append' },
    { name: 'tools.py', lines: 330, responsibility: 'CortexToolHandler: 15 MCP tools, dict dispatch' },
    { name: 'api.py', lines: 280, responsibility: 'APIRoutes: 16 REST endpoints (Starlette)' },
    { name: 'server.py', lines: 160, responsibility: 'Composition Root: DI wiring, lifespan, entry points' },
  ];

  haFunctionsMcpModules: ModuleInfo[] = [
    { name: 'ha_client.py', lines: 135, responsibility: 'HAClient: service calls, state, logbook, history, entity registry' },
    { name: 'syslog_store.py', lines: 100, responsibility: 'SyslogStore: read/write/tags, time filters, flock-safe' },
    { name: 'functions.py', lines: 310, responsibility: 'FunctionRepository + FunctionExecutor (Strategy pattern per fn_type)' },
    { name: 'handlers.py', lines: 260, responsibility: 'HandlerRegistry: meta tools, telegram, entity trace, syslog' },
    { name: 'server.py', lines: 190, responsibility: 'Composition Root: DI wiring, tool registry, entry point' },
  ];

  pythonScriptsModules: ModuleInfo[] = [
    { name: 'cortex_utils.py', lines: 87, responsibility: 'Shared: syslog, send_telegram, send_feed, ha_get_state, is_user_home' },
    { name: 'cortex_slot_trigger.py', lines: 362, responsibility: 'Daemon: slot scheduling, Haiku controller, action validation, agent orchestration' },
    { name: 'watchdog_agent.py', lines: 310, responsibility: 'HealthCheck Protocol + 4 checkers + DiffEngine + Alerter + WatchdogAgent' },
    { name: 'management_agent.py', lines: 350, responsibility: 'DataCollector + Formatter + ActiveThinking + ManagementAgent' },
  ];

  designPatterns: DesignPattern[] = [
    { name: 'Strategy', where: 'ha-functions-mcp/functions.py', description: 'FunctionExecutor dispatches per fn_type (script/rest/native/template/claude_code)' },
    { name: 'Repository', where: 'cortex-mcp/config.py, ha-functions-mcp/functions.py', description: 'ConfigRepository + FunctionRepository abstract file I/O from business logic' },
    { name: 'Dependency Injection', where: 'All modules', description: 'httpx.AsyncClient, file paths, config all injected via constructors. No global mutable state.' },
    { name: 'Protocol (Interface)', where: 'watchdog_agent.py', description: 'HealthCheck Protocol: DockerCheck, HAReachableCheck, ContainerLogCheck, LightsAwayCheck' },
    { name: 'Composition Root', where: 'server.py (both MCP servers)', description: 'Single entry point wires all dependencies. Lifespan manages httpx client lifecycle.' },
    { name: 'Dict Dispatch', where: 'tools.py, handlers.py', description: 'Tool name -> handler mapping replaces if/elif chains' },
  ];

  principles: string[] = [
    '12-Factor: All config from env vars (systemd EnvironmentFile=/home/leona/.env)',
    'No global mutable state: all state in injected objects',
    'Type-safe: frozen dataclasses with slots, StrEnum, full type hints (Python 3.12)',
    'Single Responsibility: each module has one reason to change',
    'DRY: cortex_utils.py eliminates 5x duplicated helpers across agents',
    'Fail-open: is_user_home() returns True if HA unreachable (safety default)',
    'Central logging: all agents/services write to system_log.jsonl via flock',
  ];

  getTypeColor(type: string): string {
    switch (type) {
      case 'mcp': return '#00ff41';
      case 'agent': return '#ff00ff';
      case 'ui': return '#00ccff';
      case 'infra': return '#ffb000';
      case 'sensor': return '#ff4444';
      default: return '#888';
    }
  }
}
