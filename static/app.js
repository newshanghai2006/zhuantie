const DEFAULT_PROFILE = {
  id: "default", name: "默认模型", provider: "openai_compatible",
  base_url: "https://api.openai.com/v1", model: "gpt-4.1-mini", api_key: "",
  remember_token: true, rpm: 10, tpm: 60000, input_token_budget: 12000,
  output_token_budget: 5000, temperature: 0.7, json_mode: "structured",
};

const state = {
  activeSource: "reddit", activeCategory: { reddit: "popular", quora: "popular" },
  activeCategoryName: "全站热门", categories: [], sorts: [], posts: [], selectedId: null,
  sourceCommunity: "", sourceComments: [], result: null, profiles: [],
  activeProfileId: "default", deviceId: "", sourceAvailable: true,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function refreshIcons() {
  if (window.lucide) window.lucide.createIcons({ attrs: { "aria-hidden": "true" } });
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  let payload;
  try { payload = await response.json(); } catch { throw new Error(`服务返回异常（HTTP ${response.status}）`); }
  if (!response.ok) {
    const detail = payload.detail ? `：${String(payload.detail).slice(0, 180)}` : "";
    throw new Error(`${payload.error || "请求失败"}${detail}`);
  }
  return payload;
}

let toastTimer;
function toast(message, type = "success") {
  const element = $("#toast");
  element.classList.toggle("error", type === "error");
  $("span", element).textContent = message;
  const icon = $("svg", element);
  if (icon) icon.outerHTML = `<i data-lucide="${type === "error" ? "circle-alert" : "circle-check"}"></i>`;
  refreshIcons();
  element.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove("show"), 3600);
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = value ?? "";
  return node.innerHTML;
}

function compactNumber(value) {
  const number = Number(value) || 0;
  if (number >= 1000000) return `${(number / 1000000).toFixed(1)}m`;
  if (number >= 1000) return `${(number / 1000).toFixed(1)}k`;
  return String(number);
}

function relativeTime(iso) {
  if (!iso) return "";
  const seconds = Math.max(1, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 3600) return `${Math.max(1, Math.floor(seconds / 60))} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

function makeId() {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function bytesToBase64(bytes) {
  let binary = "";
  bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
  return btoa(binary);
}

function base64ToBytes(value) {
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
}

async function deviceCryptoKey() {
  const material = new TextEncoder().encode(`yilang-profile:${state.deviceId}`);
  const digest = await crypto.subtle.digest("SHA-256", material);
  return crypto.subtle.importKey("raw", digest, "AES-GCM", false, ["encrypt", "decrypt"]);
}

async function encryptSecret(value) {
  if (!value) return "";
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encrypted = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await deviceCryptoKey(), new TextEncoder().encode(value));
  return `${bytesToBase64(iv)}.${bytesToBase64(new Uint8Array(encrypted))}`;
}

async function decryptSecret(value) {
  if (!value) return "";
  try {
    const [iv, encrypted] = value.split(".");
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: base64ToBytes(iv) }, await deviceCryptoKey(), base64ToBytes(encrypted));
    return new TextDecoder().decode(plain);
  } catch { return ""; }
}

function currentProfile() {
  return state.profiles.find((profile) => profile.id === state.activeProfileId) || state.profiles[0];
}

async function loadProfiles() {
  state.deviceId = localStorage.getItem("yilang-device-id") || makeId();
  localStorage.setItem("yilang-device-id", state.deviceId);
  let stored = null;
  try { stored = JSON.parse(localStorage.getItem("yilang-model-profiles-v2") || "null"); } catch { /* ignore invalid state */ }
  if (stored?.profiles?.length) {
    state.profiles = await Promise.all(stored.profiles.map(async (profile) => ({
      ...DEFAULT_PROFILE, ...profile, api_key: await decryptSecret(profile.api_key_encrypted),
    })));
    state.activeProfileId = state.profiles.some((profile) => profile.id === stored.active_profile_id)
      ? stored.active_profile_id : state.profiles[0].id;
  } else {
    let legacy = {};
    try { legacy = JSON.parse(localStorage.getItem("yilang-model-settings") || "{}"); } catch { /* ignore */ }
    state.profiles = [{ ...DEFAULT_PROFILE, ...legacy }];
  }
  renderProfileSelect();
  renderProfileForm();
}

async function persistProfiles() {
  const profiles = await Promise.all(state.profiles.map(async (profile) => {
    const { api_key: apiKey, ...safeProfile } = profile;
    return { ...safeProfile, api_key_encrypted: profile.remember_token ? await encryptSecret(apiKey) : "" };
  }));
  localStorage.setItem("yilang-model-profiles-v2", JSON.stringify({
    version: 2, device_id: state.deviceId, active_profile_id: state.activeProfileId, profiles,
  }));
  localStorage.removeItem("yilang-model-settings");
}

function renderProfileSelect() {
  $("#profileSelect").innerHTML = state.profiles.map((profile) => `
    <option value="${escapeHtml(profile.id)}" ${profile.id === state.activeProfileId ? "selected" : ""}>${escapeHtml(profile.name)}</option>
  `).join("");
  $("#deleteProfileButton").disabled = state.profiles.length <= 1;
  $("#activeProfileLabel").textContent = currentProfile()?.name || "模型设置";
}

function renderProfileForm() {
  const profile = currentProfile();
  if (!profile) return;
  $("#profileNameInput").value = profile.name;
  $("#providerInput").value = profile.provider;
  $("#baseUrlInput").value = profile.base_url;
  $("#modelInput").value = profile.model;
  $("#apiKeyInput").value = profile.api_key || "";
  $("#rememberTokenInput").checked = profile.remember_token !== false;
  $("#rpmInput").value = profile.rpm;
  $("#tpmInput").value = profile.tpm;
  $("#inputBudgetInput").value = profile.input_token_budget;
  $("#outputBudgetInput").value = profile.output_token_budget;
  $("#jsonModeInput").value = profile.json_mode;
  $("#temperatureInput").value = profile.temperature;
  $("#temperatureOutput").value = Number(profile.temperature).toFixed(1);
  $("#deviceIdText").textContent = state.deviceId.slice(0, 8);
  updateProviderHint(false);
}

function updateProfileFromForm() {
  const profile = currentProfile();
  if (!profile) return;
  Object.assign(profile, {
    name: $("#profileNameInput").value.trim() || "未命名模型",
    provider: $("#providerInput").value,
    base_url: $("#baseUrlInput").value.trim().replace(/\/$/, ""),
    model: $("#modelInput").value.trim(), api_key: $("#apiKeyInput").value.trim(),
    remember_token: $("#rememberTokenInput").checked,
    rpm: Math.max(1, Math.min(600, Number($("#rpmInput").value) || 10)),
    tpm: Math.max(1000, Math.min(10000000, Number($("#tpmInput").value) || 60000)),
    input_token_budget: Math.max(1500, Math.min(64000, Number($("#inputBudgetInput").value) || 12000)),
    output_token_budget: Math.max(512, Math.min(16000, Number($("#outputBudgetInput").value) || 5000)),
    temperature: Number($("#temperatureInput").value), json_mode: $("#jsonModeInput").value,
  });
}

function updateProviderHint(changeDefaults = true) {
  const anthropic = $("#providerInput").value === "anthropic";
  $("#apiUrlHint").textContent = anthropic ? "Claude Messages API 地址" : "兼容 OpenAI Chat Completions 的接口地址";
  $("#jsonModeInput").disabled = anthropic;
  if (changeDefaults && ["https://api.openai.com/v1", "https://api.anthropic.com/v1"].includes($("#baseUrlInput").value)) {
    $("#baseUrlInput").value = anthropic ? "https://api.anthropic.com/v1" : "https://api.openai.com/v1";
    $("#modelInput").value = anthropic ? "claude-sonnet-4-5" : "gpt-4.1-mini";
  }
}

async function saveSettings(event) {
  event.preventDefault();
  updateProfileFromForm();
  await persistProfiles();
  renderProfileSelect();
  $("#settingsDialog").close();
  toast("模型配置已保存在此设备");
}

function addProfile() {
  updateProfileFromForm();
  const profile = { ...DEFAULT_PROFILE, id: makeId(), name: `模型配置 ${state.profiles.length + 1}` };
  state.profiles.push(profile);
  state.activeProfileId = profile.id;
  renderProfileSelect();
  renderProfileForm();
  $("#profileNameInput").select();
}

async function deleteProfile() {
  if (state.profiles.length <= 1 || !window.confirm(`删除“${currentProfile().name}”配置？`)) return;
  state.profiles = state.profiles.filter((profile) => profile.id !== state.activeProfileId);
  state.activeProfileId = state.profiles[0].id;
  await persistProfiles();
  renderProfileSelect();
  renderProfileForm();
}

async function loadCategories() {
  try {
    const data = await api(`/api/categories?source=${state.activeSource}`);
    state.sourceAvailable = data.available !== false;
    state.categories = data.categories;
    state.sorts = data.sorts;
    const categoryKey = state.activeSource === "reddit" ? "community" : "topic";
    if (!state.categories.some((item) => item[categoryKey] === state.activeCategory[state.activeSource])) {
      state.activeCategory[state.activeSource] = state.categories[0][categoryKey];
    }
    state.activeCategoryName = state.categories.find((item) => item[categoryKey] === state.activeCategory[state.activeSource])?.name || "内容发现";
    $("#feedTitle").textContent = state.activeCategoryName;
    renderCategories();
    renderSorts();
  } catch (error) {
    $("#categoryList").innerHTML = `<div class="empty-state"><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function renderCategories() {
  const categoryKey = state.activeSource === "reddit" ? "community" : "topic";
  const prefix = state.activeSource === "reddit" ? "r/" : "topic/";
  $("#categoryList").innerHTML = state.categories.map((category) => `
    <button class="category-item ${category[categoryKey] === state.activeCategory[state.activeSource] ? "active" : ""}" type="button" data-category="${escapeHtml(category[categoryKey])}" data-name="${escapeHtml(category.name)}">
      <span>${escapeHtml(category.name)}</span><small>${prefix}${escapeHtml(category[categoryKey])}</small>
    </button>`).join("");
  $$(".category-item").forEach((button) => button.addEventListener("click", () => {
    state.activeCategory[state.activeSource] = button.dataset.category;
    state.activeCategoryName = button.dataset.name;
    $("#feedTitle").textContent = state.activeCategoryName;
    renderCategories();
    loadPosts();
  }));
}

function renderSorts() {
  const previous = $("#sortSelect").value;
  $("#sortSelect").innerHTML = state.sorts.map((sort) => `
    <option value="${escapeHtml(sort.id)}" ${sort.disabled ? "disabled" : ""} title="${escapeHtml(sort.reason || "")}">${escapeHtml(sort.name)}${sort.disabled ? "（不可用）" : ""}</option>`).join("");
  if (state.sorts.some((sort) => sort.id === previous && !sort.disabled)) $("#sortSelect").value = previous;
}

function showPostSkeletons() {
  $("#postList").innerHTML = `<div class="skeleton post-skeleton"></div><div class="skeleton post-skeleton"></div><div class="skeleton post-skeleton"></div>`;
  $("#feedCount").textContent = `正在连接 ${state.activeSource === "reddit" ? "Reddit" : "Quora"}...`;
}

async function loadPosts(force = false) {
  showPostSkeletons();
  const sort = $("#sortSelect").value;
  const period = $("#periodSelect").value;
  $("#periodControl").hidden = state.activeSource !== "reddit" || sort !== "top";
  if (!state.sourceAvailable) {
    state.posts = [];
    $("#feedCount").textContent = "需要授权连接器";
    $("#feedUpdated").textContent = "";
    $("#postList").innerHTML = `<div class="empty-state"><i data-lucide="plug-zap"></i><strong>Quora 连接器未配置</strong><p>设置 QUORA_API_BASE_URL 后即可自动发现并导入已授权内容。</p></div>`;
    refreshIcons();
    return;
  }
  try {
    const query = state.activeSource === "reddit"
      ? new URLSearchParams({ community: state.activeCategory.reddit, sort, period, limit: "25" })
      : new URLSearchParams({ topic: state.activeCategory.quora, sort, limit: "20" });
    if (force) query.set("refresh", "1");
    const path = state.activeSource === "reddit" ? `/api/reddit/posts?${query}` : `/api/quora/posts?${query}`;
    const data = await api(path);
    state.posts = data.posts;
    renderPosts();
    const fallback = state.posts.some((post) => post.feed_fallback || post.search_fallback);
    const note = state.activeSource === "quora" ? " · 授权连接器" : fallback ? " · RSS 模式" : "";
    $("#feedCount").textContent = `${state.posts.length} 篇可用内容${note}`;
    $("#feedUpdated").textContent = `更新于 ${new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
  } catch (error) {
    state.posts = [];
    $("#feedCount").textContent = "加载失败";
    $("#postList").innerHTML = `<div class="empty-state"><i data-lucide="wifi-off"></i><strong>暂时无法读取内容源</strong><p>${escapeHtml(error.message)}</p></div>`;
    refreshIcons();
    toast(error.message, "error");
  }
}

function renderPosts() {
  if (!state.posts.length) {
    $("#postList").innerHTML = `<div class="empty-state"><i data-lucide="inbox"></i><strong>当前没有可用内容</strong><p>切换门类或排序后再试。</p></div>`;
    refreshIcons();
    return;
  }
  $("#postList").innerHTML = state.posts.map((post) => {
    const image = post.thumbnail ? `<img class="post-image" src="${escapeHtml(post.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : "";
    const excerpt = post.body ? `<p class="post-excerpt">${escapeHtml(post.body)}</p>` : "";
    const prefix = post.source === "quora" ? "Quora · " : `r/${escapeHtml(post.community)} · `;
    const metrics = [
      post.score ? `<span><i data-lucide="arrow-big-up"></i>${compactNumber(post.score)}</span>` : "",
      post.comments_count ? `<span><i data-lucide="message-circle"></i>${compactNumber(post.comments_count)}</span>` : "",
      post.view_count ? `<span><i data-lucide="eye"></i>${compactNumber(post.view_count)}</span>` : "",
    ].join("");
    return `<button class="post-card ${image ? "" : "no-image"} ${post.id === state.selectedId ? "selected" : ""}" type="button" data-post-id="${escapeHtml(post.id)}">
      <span class="post-copy"><span class="post-community">${prefix}${escapeHtml(relativeTime(post.created_at))}</span>
      <h2>${escapeHtml(post.title)}</h2>${excerpt}<span class="post-stats">${metrics}<span>${post.source === "quora" ? "问答" : post.is_text ? "讨论" : "链接"}</span></span></span>${image}</button>`;
  }).join("");
  $$(".post-card").forEach((card) => card.addEventListener("click", () => selectPost(card.dataset.postId)));
  $$(".post-image").forEach((image) => image.addEventListener("error", () => { image.closest(".post-card")?.classList.add("no-image"); image.remove(); }));
  refreshIcons();
}

async function selectPost(id) {
  const post = state.posts.find((item) => item.id === id);
  if (!post) return;
  state.selectedId = id;
  renderPosts();
  setSelectedStatus("正在读取正文与评论...", false);
  try {
    const query = new URLSearchParams({ source: post.source || state.activeSource, url: post.permalink });
    const data = await api(`/api/source/post?${query}`);
    fillSource(data.post, post.source === "quora" ? "Quora" : "Reddit");
    if (window.innerWidth <= 860) $("#workspacePanel").scrollIntoView({ behavior: "smooth", block: "start" });
    toast(data.post.detail_fallback ? "已自动载入公开摘要；完整评论暂不可用" : "帖子正文与评论已自动载入");
  } catch (error) {
    fillSource({ ...post, comments: [] }, post.source === "quora" ? "Quora" : "Reddit");
    toast(`已载入列表摘要：${error.message}`, "error");
  }
}

function setSelectedStatus(text, empty) {
  const box = $("#selectedStatus");
  box.classList.toggle("empty", empty);
  $("span", box).textContent = text;
}

function fillSource(post, platform) {
  $("#platformInput").value = platform || "其他海外论坛";
  $("#urlInput").value = post.permalink || post.url || "";
  $("#titleInput").value = post.title || "";
  $("#bodyInput").value = post.body || "";
  state.sourceCommunity = post.community || platform || "";
  state.sourceComments = post.comments || [];
  $("#commentsInput").value = state.sourceComments.map((item) => item.body).join("\n\n");
  $("#commentCount").textContent = `${state.sourceComments.length} 条`;
  setSelectedStatus(post.title || "已载入内容", false);
  switchWorkspace("source");
}

async function switchSource(tab) {
  $$(".source-tab").forEach((button) => button.classList.toggle("active", button.dataset.sourceTab === tab));
  $$(".source-view").forEach((view) => view.classList.remove("active"));
  if (["reddit", "quora"].includes(tab)) {
    state.activeSource = tab;
    $("#discoveryView").classList.add("active");
    await loadCategories();
    await loadPosts();
  } else {
    $(`#${tab}View`).classList.add("active");
  }
}

function switchWorkspace(tab) {
  $$(".workspace-tab").forEach((button) => button.classList.toggle("active", button.dataset.workspaceTab === tab));
  $("#sourceEditor").classList.toggle("active", tab === "source");
  $("#resultView").classList.toggle("active", tab === "result");
}

async function importLink(event) {
  event.preventDefault();
  const url = $("#sourceUrl").value.trim();
  const submit = $("button[type=submit]", event.currentTarget);
  submit.disabled = true;
  try {
    const data = await api(`/api/source/import?url=${encodeURIComponent(url)}`);
    const platform = data.post.source === "quora" ? "Quora" : "Reddit";
    fillSource(data.post, platform);
    toast(data.post.detail_fallback ? "已自动导入公开摘要" : "帖子已自动导入");
    if (window.innerWidth <= 860) $("#workspacePanel").scrollIntoView({ behavior: "smooth" });
  } catch (error) { toast(error.message, "error"); } finally { submit.disabled = false; }
}

function clearSource(confirmFirst = true) {
  const hasContent = $("#titleInput").value || $("#bodyInput").value;
  if (confirmFirst && hasContent && !window.confirm("清空当前来源内容和生成结果？")) return;
  state.selectedId = null; state.sourceCommunity = ""; state.sourceComments = []; state.result = null;
  ["#urlInput", "#titleInput", "#bodyInput", "#commentsInput"].forEach((id) => { $(id).value = ""; });
  $("#commentCount").textContent = "0 条"; $("#resultBadge").hidden = true; $("#downloadButton").disabled = true;
  $("#resultContent").hidden = true; $("#resultEmpty").hidden = false;
  setSelectedStatus("选择一篇热帖，或直接录入内容", true);
  renderPosts();
}

function commentsFromEditor() {
  return $("#commentsInput").value.split(/\n\s*\n/).map((body) => body.trim()).filter(Boolean).map((body) => {
    const original = state.sourceComments.find((item) => item.body.trim() === body);
    return { body, score: original?.score || 0, author: original?.author || "" };
  });
}

async function generate() {
  const title = $("#titleInput").value.trim();
  const body = $("#bodyInput").value.trim();
  if (!title && !body) { toast("请先选择帖子或填写标题、正文", "error"); $("#titleInput").focus(); return; }
  const profile = currentProfile();
  const isLocal = /localhost|127\.0\.0\.1/.test(profile.base_url);
  if (!profile.api_key && !isLocal) {
    renderProfileForm(); $("#settingsDialog").showModal(); toast("请先为当前模型配置填写 API Token", "error"); return;
  }
  const button = $("#generateButton");
  button.classList.add("loading"); button.disabled = true;
  const label = $("span", button); label.textContent = "正在清洗、翻译与改编...";
  const icon = $("svg", button); if (icon) icon.outerHTML = `<i data-lucide="loader-circle"></i>`; refreshIcons();
  try {
    state.result = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({
        source: {
          platform: $("#platformInput").value, community: state.sourceCommunity, url: $("#urlInput").value.trim(),
          title, body, comments: commentsFromEditor(), comment_sort: $("#commentSortSelect").value,
          comment_limit: Number($("#commentLimitSelect").value),
        },
        config: profile,
      }),
    });
    renderResult(); switchWorkspace("result"); toast("双平台内容与中英配图 Prompt 已生成");
  } catch (error) { toast(error.message, "error"); } finally {
    button.classList.remove("loading"); button.disabled = false; label.textContent = "生成双平台内容";
    const currentIcon = $("svg", button); if (currentIcon) currentIcon.outerHTML = `<i data-lucide="sparkles"></i>`; refreshIcons();
  }
}

function renderResult() {
  const result = state.result;
  $("#resultEmpty").hidden = true; $("#resultContent").hidden = false;
  $("#summaryText").textContent = result.original_summary || "";
  $("#complianceText").textContent = result.compliance_check || "完全合规";
  const meta = result.meta || {};
  $("#generationMeta").textContent = meta.estimated_input_tokens
    ? `输入约 ${compactNumber(meta.estimated_input_tokens)} Token · 使用 ${meta.comments_used || 0} 条评论 · ${meta.output_mode || "JSON"}` : "";
  [["xiaohongshu", "xhs"], ["toutiao", "toutiao"]].forEach(([key, prefix]) => {
    const value = result[key] || {};
    $(`#${prefix}Result`).hidden = !value.title && !value.content;
    $(`#${prefix}Title`).textContent = value.title || "";
    $(`#${prefix}Content`).textContent = value.content || "";
  });
  $("#promptList").innerHTML = (result.image_prompts || []).map((item, index) => `
    <article class="prompt-item"><strong>${index + 1}. ${escapeHtml(item.scene_description || "配图")}</strong>
      <div class="prompt-language"><div><span>EN · Midjourney / Flux / ChatGPT</span><button type="button" data-prompt-index="${index}" data-language="en" title="复制英文提示词" aria-label="复制英文提示词"><i data-lucide="copy"></i></button></div><p>${escapeHtml(item.prompt_en || "")}</p></div>
      <div class="prompt-language"><div><span>中文 · 豆包</span><button type="button" data-prompt-index="${index}" data-language="zh" title="复制中文提示词" aria-label="复制中文提示词"><i data-lucide="copy"></i></button></div><p>${escapeHtml(item.prompt_zh || "")}</p></div>
    </article>`).join("");
  $$("[data-prompt-index]").forEach((button) => button.addEventListener("click", () => {
    const prompt = result.image_prompts[Number(button.dataset.promptIndex)];
    copyText(button.dataset.language === "zh" ? prompt.prompt_zh : prompt.prompt_en);
  }));
  $("#resultBadge").hidden = false; $("#downloadButton").disabled = false; refreshIcons();
}

async function copyText(value) {
  try { await navigator.clipboard.writeText(value || ""); toast("已复制到剪贴板"); }
  catch { toast("浏览器未允许访问剪贴板", "error"); }
}

function downloadResult() {
  if (!state.result) return;
  const blob = new Blob([JSON.stringify(state.result, null, 2)], { type: "application/json;charset=utf-8" });
  const link = document.createElement("a"); link.href = URL.createObjectURL(blob);
  link.download = `本土化内容_${new Date().toISOString().slice(0, 10)}.json`; link.click(); URL.revokeObjectURL(link.href);
}

function bindEvents() {
  $$(".source-tab").forEach((button) => button.addEventListener("click", () => switchSource(button.dataset.sourceTab)));
  $$(".workspace-tab").forEach((button) => button.addEventListener("click", () => switchWorkspace(button.dataset.workspaceTab)));
  $("#sortSelect").addEventListener("change", () => loadPosts()); $("#periodSelect").addEventListener("change", () => loadPosts());
  $("#refreshButton").addEventListener("click", () => loadPosts(true)); $("#linkForm").addEventListener("submit", importLink);
  $("#startManualButton").addEventListener("click", () => {
    clearSource(false); $("#platformInput").value = "其他海外论坛"; setSelectedStatus("手动录入模式", false);
    switchWorkspace("source"); $("#titleInput").focus();
    if (window.innerWidth <= 860) $("#workspacePanel").scrollIntoView({ behavior: "smooth" });
  });
  $("#clearButton").addEventListener("click", () => clearSource(true)); $("#downloadButton").addEventListener("click", downloadResult);
  $("#generateButton").addEventListener("click", generate);
  $("#settingsButton").addEventListener("click", () => { renderProfileForm(); $("#settingsDialog").showModal(); });
  $("#closeSettingsButton").addEventListener("click", () => $("#settingsDialog").close());
  $("#cancelSettingsButton").addEventListener("click", () => $("#settingsDialog").close());
  $("#settingsForm").addEventListener("submit", saveSettings);
  $("#addProfileButton").addEventListener("click", addProfile); $("#deleteProfileButton").addEventListener("click", deleteProfile);
  $("#profileSelect").addEventListener("change", (event) => {
    updateProfileFromForm(); state.activeProfileId = event.target.value; renderProfileSelect(); renderProfileForm();
  });
  $("#providerInput").addEventListener("change", () => updateProviderHint(true));
  $("#temperatureInput").addEventListener("input", (event) => { $("#temperatureOutput").value = Number(event.target.value).toFixed(1); });
  $("#toggleTokenButton").addEventListener("click", () => { const input = $("#apiKeyInput"); input.type = input.type === "password" ? "text" : "password"; });
  $$("[data-copy]").forEach((button) => button.addEventListener("click", () => {
    const key = button.dataset.copy === "xhs" ? "xiaohongshu" : "toutiao"; const article = state.result?.[key];
    if (article) copyText(`${article.title}\n\n${article.content}`);
  }));
  $("#commentsInput").addEventListener("input", () => { $("#commentCount").textContent = `${commentsFromEditor().length} 条`; });
  document.addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !$("#settingsDialog").open) generate(); });
  $("#collapseButton").addEventListener("click", () => document.body.classList.toggle("sidebar-collapsed"));
}

async function init() {
  const query = new URLSearchParams(window.location.search);
  const requestedSource = query.get("source");
  if (["reddit", "quora"].includes(requestedSource)) state.activeSource = requestedSource;
  $$(".source-tab").forEach((button) => button.classList.toggle("active", button.dataset.sourceTab === state.activeSource));
  refreshIcons(); bindEvents(); await loadProfiles();
  if (query.get("settings") === "1") $("#settingsDialog").showModal();
  await loadCategories(); await loadPosts();
}

document.addEventListener("DOMContentLoaded", init);
