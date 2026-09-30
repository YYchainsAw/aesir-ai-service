"""调试与控制台路由（SDD T015，US7 可解释的调试数据源）。

- ``GET /v1/console/state``：当前注册表、指定角色的运行状态摘要。
- ``GET /v1/console/memory``：查看指定角色的三级长期记忆（调试用，US1 验收）。
- ``POST /v1/console/memory/reset``：清空指定角色的会话与长期记忆。

Phase 2 骨架：长期记忆重置（T029）与情绪/关系阶段查询（T077）随后接入；
当前返回的就地状态以「如实汇报骨架能力」为限，不虚构未实现字段。
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.services.companion.profile_repository import (
    UnknownCompanionError,
    get_registered_profile,
    list_registered_companions,
)
from app.services.companion.session_memory import get_session_memory
from app.services.memory.store import MemoryStoreError, get_memory_store
from app.services.tactical.policy import get_policy

router = APIRouter(prefix="/v1/console", tags=["console"])


class MemoryEntryView(BaseModel):
    """调试视图：单条长期记忆的精简字段。"""

    model_config = ConfigDict(extra="forbid")
    content: str
    importance: str
    source: str
    real_time: str


class ConsoleStateResponse(BaseModel):

    model_config = ConfigDict(extra="forbid")
    registered_companions: list[str]
    companion_id: str
    display_name: str
    memory_backend: str          # 当前记忆后端说明（长期记忆 T025 落地后更新）
    session_memory_turns: int    # 会话记忆窗口配置
    tactical_policy_revision: str
    # ---- US7（T077）调试视图：场景 / 情绪 / 关系 / 记忆 / 版本 ----
    persona_revision: str                 # 人设 YAML 的 profile_version
    agency_policy_revision: str           # 自主行为策略版本
    relationship_stage: str               # 关系阶段（体系故障为空字符串）
    relationship_stage_display: str       # FIX-05：关系阶段中文展示名
    relationship_value: float | None      # 关系数值（同上为 None）
    last_scene: str                      # 最近一次快照的活动场景（重启后为空）
    last_emotion_id: str                  # 最近一次输出表现的表情 ID（同上）
    last_seen: str                        # 最近一次观测时间 ISO-8601 UTC（重启后为空）
    recent_memory: list[MemoryEntryView]  # 近期记忆摘要（按重要性取前 5）


class MemoryResetRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")
    companion_id: str = Field(min_length=1)


class MemoryResetResponse(BaseModel):

    model_config = ConfigDict(extra="forbid")
    companion_id: str
    reset: bool
    cleared_sessions: int       # 实际清除的会话分区数（含 0：无会话也是成功）


@router.get("/state", response_model=ConsoleStateResponse)
def console_state(companion_id: str) -> ConsoleStateResponse:
    try:
        profile = get_registered_profile(companion_id)
    except UnknownCompanionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    game_id = profile.game_name.lower()

    # US7（T077）：关系（故障降级为空阶段/None，不阻塞调试台）
    from app.services.relationship.policy import get_stage_display_name
    from app.services.relationship.state import (
        RelationshipStoreError,
        get_relationship_store,
    )

    try:
        rel = get_relationship_store(companion_id, game_id=game_id).state()
        relationship_stage, relationship_value = rel.stage, rel.value
    except RelationshipStoreError:
        relationship_stage, relationship_value = "", None
    relationship_stage_display = get_stage_display_name(relationship_stage)

    # 近期记忆摘要（检索预算内的条目按重要性取前 5；故障为空列表）
    try:
        from app.services.memory.retrieval import retrieve

        recent = retrieve(get_memory_store(companion_id, game_id=game_id))[:5]
    except MemoryStoreError:
        recent = []

    from app.services.agency.behavior_catalog import get_agency_policy
    from app.services.console.runtime_state import get_observation

    observation = get_observation(companion_id)

    return ConsoleStateResponse(
        registered_companions=list_registered_companions(),
        companion_id=profile.companion_id,
        display_name=profile.display_name,
        memory_backend="四级存储：短期窗口 / 经历摘要 / 长期档案 / 模糊印象",
        session_memory_turns=get_settings().dialogue_history_turns,
        tactical_policy_revision=get_policy().revision,
        persona_revision=str(profile.raw.get("profile_version", "")),
        agency_policy_revision=get_agency_policy().revision,
        relationship_stage=relationship_stage,
        relationship_stage_display=relationship_stage_display,
        relationship_value=relationship_value,
        last_scene=observation.scene,
        last_emotion_id=observation.emotion_id,
        last_seen=observation.last_seen,
        recent_memory=[
            MemoryEntryView(
                content=e.content, importance=e.importance,
                source=e.source, real_time=e.real_time,
            )
            for e in recent
        ],
    )


class TopicImpressionView(BaseModel):
    """调试视图：单条模糊印象（主题 × 提及频率）。"""

    model_config = ConfigDict(extra="forbid")
    topic: str
    mention_count: int
    weight: float
    last_seen: str
    origin: str


class MemoryViewResponse(BaseModel):
    """长期记忆全量视图（GET /v1/console/memory），含模糊印象层。"""

    model_config = ConfigDict(extra="forbid")
    companion_id: str
    counts: dict[str, int]           # short_term / summaries / archive / impressions 各层条数
    short_term: list[MemoryEntryView]
    summaries: list[MemoryEntryView]
    archive: list[MemoryEntryView]
    impressions: list[TopicImpressionView]


@router.get("/memory", response_model=MemoryViewResponse)
def view_memory(companion_id: str) -> MemoryViewResponse:
    try:
        profile = get_registered_profile(companion_id)
    except UnknownCompanionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    try:
        snapshot = get_memory_store(companion_id, game_id=profile.game_name.lower()).snapshot()
    except MemoryStoreError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    def _view(entry) -> MemoryEntryView:
        return MemoryEntryView(
            content=entry.content, importance=entry.importance,
            source=entry.source, real_time=entry.real_time,
        )

    return MemoryViewResponse(
        companion_id=companion_id,
        counts={
            "short_term": len(snapshot.short_term),
            "summaries": len(snapshot.summaries),
            "archive": len(snapshot.archive),
            "impressions": len(snapshot.impressions),
        },
        short_term=[_view(e) for e in snapshot.short_term],
        summaries=[_view(e) for e in snapshot.summaries],
        archive=[_view(e) for e in snapshot.archive],
        impressions=[
            TopicImpressionView(
                topic=i.topic, mention_count=i.mention_count,
                weight=i.weight, last_seen=i.last_seen, origin=i.origin,
            )
            for i in snapshot.impressions
        ],
    )


@router.post("/memory/reset", response_model=MemoryResetResponse)
def reset_memory(request: MemoryResetRequest) -> MemoryResetResponse:
    try:
        profile = get_registered_profile(request.companion_id)
    except UnknownCompanionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    # 记忆重置（FR-010 / T029）：清空长期记忆 + 会话记忆分区。
    # 长期记忆故障时仍算部分成功：会话记忆已清，长期记忆保持原样并如实返回。
    memory = get_session_memory(get_settings().dialogue_history_turns)
    cleared = memory.clear(request.companion_id)
    long_term_reset = True
    try:
        get_memory_store(request.companion_id, game_id=profile.game_name.lower()).clear()
    except MemoryStoreError:
        long_term_reset = False
    return MemoryResetResponse(
        companion_id=request.companion_id, reset=long_term_reset, cleared_sessions=cleared
    )


# ---------------------------------------------------------------------------
# EXT-06：调试台 Web UI（单页 HTML，原生 JS，无外部依赖）
# ---------------------------------------------------------------------------

_CONSOLE_UI_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Aesir 调试台</title>
<style>
  :root { --bg:#0f172a; --panel:#1e293b; --text:#e2e8f0; --muted:#94a3b8; --accent:#38bdf8; --danger:#ef4444; --success:#22c55e; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--text); line-height:1.5; }
  header { padding:1rem 1.5rem; background:var(--panel); border-bottom:1px solid #334155; display:flex; align-items:center; gap:1rem; flex-wrap:wrap; }
  header h1 { margin:0; font-size:1.25rem; }
  header select, header button, header label { font-size:0.95rem; }
  header select { padding:0.35rem 0.6rem; border-radius:0.375rem; border:1px solid #475569; background:#0f172a; color:var(--text); }
  header button { padding:0.4rem 0.8rem; border:0; border-radius:0.375rem; background:var(--accent); color:#0f172a; cursor:pointer; }
  header button:hover { opacity:0.9; }
  header label { display:flex; align-items:center; gap:0.4rem; color:var(--muted); }
  #last-update { margin-left:auto; color:var(--muted); font-size:0.85rem; }
  main { padding:1.5rem; display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:1rem; max-width:1400px; margin:0 auto; }
  .card { background:var(--panel); border-radius:0.5rem; padding:1rem; border:1px solid #334155; }
  .card h2 { margin:0 0 0.75rem; font-size:1rem; color:var(--accent); }
  .kv { display:flex; justify-content:space-between; padding:0.4rem 0; border-bottom:1px solid #334155; }
  .kv:last-child { border-bottom:0; }
  .kv .k { color:var(--muted); }
  .kv .v { font-weight:500; }
  .badge { display:inline-block; padding:0.15rem 0.5rem; border-radius:999px; background:#334155; font-size:0.8rem; }
  .progress { height:0.6rem; background:#334155; border-radius:999px; overflow:hidden; margin-top:0.5rem; }
  .progress > div { height:100%; background:var(--accent); }
  .memory-tier { margin-bottom:0.75rem; }
  .memory-tier summary { cursor:pointer; color:var(--accent); font-weight:500; }
  .memory-list { max-height:12rem; overflow:auto; margin-top:0.5rem; padding-left:0; list-style:none; }
  .memory-list li { padding:0.5rem; background:#0f172a; border-radius:0.375rem; margin-bottom:0.4rem; font-size:0.9rem; }
  .memory-list .meta { color:var(--muted); font-size:0.75rem; margin-top:0.25rem; }
  .error { color:var(--danger); }
</style>
</head>
<body>
<header>
  <h1>🛡️ Aesir 调试台</h1>
  <select id="companion-select"><option value="">加载中…</option></select>
  <button id="refresh-btn">刷新</button>
  <label><input type="checkbox" id="auto-refresh" checked> 自动刷新（2s）</label>
  <span id="last-update">未刷新</span>
</header>
<main id="main">
  <p class="error" id="loading">请选择角色并刷新。</p>
</main>
<script>
const basePath = window.location.pathname.replace(/\\/ui\\/?$/, '');
const api = p => `${basePath}${p}`;
let autoTimer = null;

async function fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

function fmt(v) { return v === '' || v == null ? '—' : v; }

function renderCard(title, rows) {
  const items = rows.map(([k, v]) => `<div class="kv"><span class="k">${k}</span><span class="v">${v}</span></div>`).join('');
  return `<div class="card"><h2>${title}</h2>${items}</div>`;
}

function render() {
  const companionId = document.getElementById('companion-select').value;
  if (!companionId) return;
  document.getElementById('loading').textContent = '加载中…';
  Promise.all([
    fetchJson(api(`/state?companion_id=${encodeURIComponent(companionId)}`)),
    fetchJson(api(`/memory?companion_id=${encodeURIComponent(companionId)}`))
  ]).then(([state, memory]) => {
    const html = [];
    html.push(renderCard('运行时状态', [
      ['角色', `${fmt(state.display_name)} <span class="badge">${fmt(state.companion_id)}</span>`],
      ['活动场景', fmt(state.last_scene)],
      ['当前情绪', fmt(state.last_emotion_id)],
      ['最近观测', fmt(state.last_seen)]
    ]));
    html.push(`<div class="card"><h2>关系状态</h2>
      <div class="kv"><span class="k">阶段</span><span class="v">${fmt(state.relationship_stage_display)} <span class="badge">${fmt(state.relationship_stage)}</span></span></div>
      <div class="kv"><span class="k">数值</span><span class="v">${state.relationship_value == null ? '—' : state.relationship_value}</span></div>
      <div class="progress"><div style="width:${state.relationship_value == null ? 0 : state.relationship_value}%"></div></div>
    </div>`);
    html.push(`<div class="card"><h2>记忆总览</h2>
      <div class="kv"><span class="k">短期</span><span class="v">${memory.counts.short_term}</span></div>
      <div class="kv"><span class="k">摘要</span><span class="v">${memory.counts.summaries}</span></div>
      <div class="kv"><span class="k">档案</span><span class="v">${memory.counts.archive}</span></div>
      <div class="kv"><span class="k">印象</span><span class="v">${memory.counts.impressions}</span></div>
    </div>`);
    const recent = (state.recent_memory || []).map(m => `<li>${escapeHtml(m.content)}<div class="meta">${m.importance} · ${m.source} · ${m.real_time}</div></li>`).join('');
    html.push(`<div class="card"><h2>近期记忆</h2><ul class="memory-list">${recent || '<li>无</li>'}</ul></div>`);
    html.push(renderCard('策略版本', [
      ['人设版本', fmt(state.persona_revision)],
      ['战术策略', fmt(state.tactical_policy_revision)],
      ['自主行为策略', fmt(state.agency_policy_revision)],
      ['记忆后端', fmt(state.memory_backend)],
      ['会话窗口', fmt(state.session_memory_turns)]
    ]));
    html.push(`<div class="card"><h2>完整记忆</h2>
      ${['short_term','summaries','archive','impressions'].map(tier => {
        const items = (memory[tier] || []).map(m => `<li>${escapeHtml(m.content || m.topic || '')}<div class="meta">${m.importance || `mention ${m.mention_count}, weight ${m.weight?.toFixed?.(2)}`} · ${m.source || m.origin} · ${m.real_time || m.last_seen}</div></li>`).join('');
        return `<details class="memory-tier"><summary>${tier} (${memory.counts[tier]})</summary><ul class="memory-list">${items || '<li>无</li>'}</ul></details>`;
      }).join('')}
    </div>`);
    document.getElementById('main').innerHTML = html.join('');
    document.getElementById('last-update').textContent = '更新于 ' + new Date().toLocaleTimeString();
  }).catch(err => {
    document.getElementById('main').innerHTML = `<p class="error">加载失败：${escapeHtml(err.message)}</p>`;
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function loadCompanions() {
  fetchJson(api('/state?companion_id=companion.alice')).then(state => {
    const sel = document.getElementById('companion-select');
    sel.innerHTML = state.registered_companions.map(id => `<option value="${id}" ${id==='companion.alice'?'selected':''}>${id}</option>`).join('');
    render();
  }).catch(() => {
    document.getElementById('companion-select').innerHTML = '<option value="">无法加载</option>';
  });
}

document.getElementById('refresh-btn').addEventListener('click', render);
document.getElementById('companion-select').addEventListener('change', render);
document.getElementById('auto-refresh').addEventListener('change', e => {
  if (autoTimer) { clearInterval(autoTimer); autoTimer = null; }
  if (e.target.checked) autoTimer = setInterval(render, 2000);
});

loadCompanions();
autoTimer = setInterval(render, 2000);
</script>
</body>
</html>"""


@router.get("/ui", response_class=HTMLResponse)
def console_ui() -> str:
    """EXT-06：单页调试台 UI，实时展示角色状态、关系、记忆与策略版本。"""
    return _CONSOLE_UI_HTML
