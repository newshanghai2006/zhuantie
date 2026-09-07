const state = {
  categories: [],
  activeCategory: "popular",
  activeCategoryName: "全站热门",
  posts: [],
  selectedId: null,
  result: null,
  target: "both",
  settings: {
    base_url: "https://api.openai.com/v1",
    model: "gpt-4.1-mini",
    rpm: 10,
    temperature: 0.7,
  },
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function refreshIcons() {
  if (window.lucide) window.lucide.createIcons({ attrs: { "aria-hidden": "true" } });
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`服务返回异常（HTTP ${response.status}）`);
  }
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
  toastTimer = setTimeout(() => element.classList.remove("show"), 3200);
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
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

function readStoredSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem("yilang-model-settings") || "{}");
    state.settings = { ...state.settings, ...saved };
  } catch { /* ignore invalid local state */ }
  $("#baseUrlInput").value = state.settings.base_url;
  $("#modelInput").value = state.settings.model;
  $("#rpmInput").value = state.settings.rpm;
  $("#temperatureInput").value = state.settings.temperature;
  $("#temperatureOutput").value = Number(state.settings.temperature).toFixed(1);
}

async function loadCategories() {
  try {
    const data = await api("/api/categories");
    state.categories = data.categories;
    renderCategories();
  } catch (error) {
    $("#categoryList").innerHTML = `<div class="empty-state"><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function renderCategories() {
  $("#categoryList").innerHTML = state.categories.map((category) => `
    <button class="category-item ${category.community === state.activeCategory ? "active" : ""}" type="button" data-community="${escapeHtml(category.community)}" data-name="${escapeHtml(category.name)}">
      <span>${escapeHtml(category.name)}</span><small>r/${escapeHtml(category.community)}</small>
    </button>
  `).join("");
  $$(".category-item").forEach((button) => button.addEventListener("click", () => {
    state.activeCategory = button.dataset.community;
    state.activeCategoryName = button.dataset.name;
    $("#feedTitle").textContent = state.activeCategoryName;
    renderCategories();
    loadPosts();
  }));
}

function showPostSkeletons() {
  $("#postList").innerHTML = `<div class="skeleton post-skeleton"></div><div class="skeleton post-skeleton"></div><div class="skeleton post-skeleton"></div>`;
  $("#feedCount").textContent = "正在连接 Reddit...";
}

async function loadPosts() {
  showPostSkeletons();
  const sort = $("#sortSelect").value;
  const period = $("#periodSelect").value;
  $("#periodControl").hidden = sort !== "top";
  try {
    const query = new URLSearchParams({ community: state.activeCategory, sort, period, limit: "25" });
    const data = await api(`/api/reddit/posts?${query}`);
    state.posts = data.posts;
    renderPosts();
    const fallback = state.posts.some((post) => post.feed_fallback);
    $("#feedCount").textContent = `${state.posts.length} 篇可用热帖${fallback ? " · RSS 模式" : ""}`;
    $("#feedUpdated").textContent = `更新于 ${new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
  } catch (error) {
    state.posts = [];
    $("#feedCount").textContent = "加载失败";
    $("#postList").innerHTML = `<div class="empty-state"><i data-lucide="wifi-off"></i><strong>暂时无法读取 Reddit</strong><p>${escapeHtml(error.message)}。仍可通过“手动录入”继续创作。</p></div>`;
    refreshIcons();
    toast(error.message, "error");
  }
}

function renderPosts() {
  if (!state.posts.length) {
    $("#postList").innerHTML = `<div class="empty-state"><i data-lucide="inbox"></i><strong>当前没有可用帖子</strong><p>切换门类或排序后再试。</p></div>`;
    refreshIcons();
    return;
  }
  $("#postList").innerHTML = state.posts.map((post) => {
    const image = post.thumbnail ? `<img class="post-image" src="${escapeHtml(post.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : "";
    const excerpt = post.body ? `<p class="post-excerpt">${escapeHtml(post.body)}</p>` : "";
    return `
      <button class="post-card ${image ? "" : "no-image"} ${post.id === state.selectedId ? "selected" : ""}" type="button" data-post-id="${escapeHtml(post.id)}">
        <span class="post-copy">
          <span class="post-community">r/${escapeHtml(post.community)} · ${escapeHtml(relativeTime(post.created_at))}</span>
          <h2>${escapeHtml(post.title)}</h2>
          ${excerpt}
          <span class="post-stats">
            ${post.feed_fallback ? "" : `<span><i data-lucide="arrow-big-up"></i>${compactNumber(post.score)}</span><span><i data-lucide="message-circle"></i>${compactNumber(post.comments_count)}</span>`}
            <span>${post.is_text ? "讨论" : "链接"}</span>
          </span>
        </span>
        ${image}
      </button>`;
  }).join("");
  $$(".post-card").forEach((card) => card.addEventListener("click", () => selectPost(card.dataset.postId)));
  $$(".post-image").forEach((image) => image.addEventListener("error", () => {
    image.closest(".post-card")?.classList.add("no-image");
    image.remove();
  }));
  refreshIcons();
}

async function selectPost(id) {
  const post = state.posts.find((item) => item.id === id);
  if (!post) return;
  state.selectedId = id;
  renderPosts();
  setSelectedStatus("正在读取正文与热门评论...", false);
  try {
    const data = await api(`/api/reddit/post?url=${encodeURIComponent(post.permalink)}`);
    fillSource(data.post, "Reddit");
    if (window.innerWidth <= 860) $("#workspacePanel").scrollIntoView({ behavior: "smooth", block: "start" });
    toast(data.post.detail_fallback ? "帖子已载入；Reddit 限流，热门评论暂不可用" : "帖子已载入创作台");
  } catch (error) {
    fillSource({ ...post, comments: [] }, "Reddit");
    toast(`正文详情读取失败，已载入列表内容：${error.message}`, "error");
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
  const comments = post.comments || [];
  $("#commentsInput").value = comments.map((item) => item.body).join("\n\n");
  $("#commentCount").textContent = `${comments.length} 条`;
  setSelectedStatus(post.title || "已载入手动内容", false);
  switchWorkspace("source");
}

function switchSource(tab) {
  $$(".source-tab").forEach((button) => button.classList.toggle("active", button.dataset.sourceTab === tab));
  $$(".source-view").forEach((view) => view.classList.remove("active"));
  $(`#${tab}View`).classList.add("active");
}

function switchWorkspace(tab) {
  $$(".workspace-tab").forEach((button) => button.classList.toggle("active", button.dataset.workspaceTab === tab));
  $("#sourceEditor").classList.toggle("active", tab === "source");
  $("#resultView").classList.toggle("active", tab === "result");
}

function inferPlatform(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host.includes("reddit.com") || host === "redd.it") return "Reddit";
    if (host.includes("quora.com")) return "Quora";
    if (host.includes("ycombinator.com")) return "Hacker News";
  } catch { /* form validation handles malformed URLs */ }
  return "其他海外论坛";
}

async function importLink(event) {
  event.preventDefault();
  const url = $("#sourceUrl").value.trim();
  const platform = inferPlatform(url);
  const submit = $("button[type=submit]", event.currentTarget);
  submit.disabled = true;
  try {
    if (platform === "Reddit") {
      const data = await api(`/api/reddit/post?url=${encodeURIComponent(url)}`);
      fillSource(data.post, platform);
      toast("Reddit 帖子导入成功");
    } else {
      clearSource(false);
      $("#platformInput").value = platform;
      $("#urlInput").value = url;
      setSelectedStatus(`${platform} 链接已保留，请粘贴标题与正文`, false);
      switchWorkspace("source");
      $("#titleInput").focus();
      toast("链接已载入，请补充原帖内容");
    }
    if (window.innerWidth <= 860) $("#workspacePanel").scrollIntoView({ behavior: "smooth" });
  } catch (error) {
    toast(error.message, "error");
  } finally {
    submit.disabled = false;
  }
}

function clearSource(confirmFirst = true) {
  const hasContent = $("#titleInput").value || $("#bodyInput").value;
  if (confirmFirst && hasContent && !window.confirm("清空当前来源内容和生成结果？")) return;
  state.selectedId = null;
  state.result = null;
  ["#urlInput", "#titleInput", "#bodyInput", "#commentsInput"].forEach((id) => { $(id).value = ""; });
  $("#commentCount").textContent = "0 条";
  $("#resultBadge").hidden = true;
  $("#downloadButton").disabled = true;
  $("#resultContent").hidden = true;
  $("#resultEmpty").hidden = false;
  setSelectedStatus("选择一篇热帖，或直接录入内容", true);
  renderPosts();
}

function commentsFromEditor() {
  return $("#commentsInput").value.split(/\n\s*\n/).map((body) => body.trim()).filter(Boolean).map((body) => ({ body, score: 0 }));
}

async function generate() {
  const title = $("#titleInput").value.trim();
  const body = $("#bodyInput").value.trim();
  if (!title && !body) {
    toast("请先选择帖子或填写标题、正文", "error");
    $("#titleInput").focus();
    return;
  }
  const apiKey = $("#apiKeyInput").value.trim();
  const isLocal = /localhost|127\.0\.0\.1/.test(state.settings.base_url);
  if (!apiKey && !isLocal) {
    $("#settingsDialog").showModal();
    toast("请先填写模型 API Token", "error");
    return;
  }
  const targets = state.target === "both" ? ["xiaohongshu", "toutiao"] : [state.target];
  const button = $("#generateButton");
  button.classList.add("loading");
  button.disabled = true;
  const label = $("span", button);
  const originalLabel = label.textContent;
  label.textContent = "正在理解与改编...";
  const icon = $("svg", button);
  if (icon) icon.outerHTML = `<i data-lucide="loader-circle"></i>`;
  refreshIcons();
  try {
    const result = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({
        source: {
          platform: $("#platformInput").value,
          url: $("#urlInput").value.trim(),
          title,
          body,
          comments: commentsFromEditor(),
        },
        targets,
        config: { ...state.settings, api_key: apiKey },
      }),
    });
    state.result = result;
    renderResult();
    switchWorkspace("result");
    toast("内容生成完成");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.classList.remove("loading");
    button.disabled = false;
    label.textContent = originalLabel;
    const currentIcon = $("svg", button);
    if (currentIcon) currentIcon.outerHTML = `<i data-lucide="sparkles"></i>`;
    refreshIcons();
  }
}

function renderResult() {
  const result = state.result;
  $("#resultEmpty").hidden = true;
  $("#resultContent").hidden = false;
  $("#summaryText").textContent = result.original_summary || "";
  $("#complianceText").textContent = result.compliance_check || "完全合规";
  const sections = [
    ["xiaohongshu", "xhs"],
    ["toutiao", "toutiao"],
  ];
  sections.forEach(([key, prefix]) => {
    const value = result[key] || {};
    $(`#${prefix}Result`).hidden = !value.title && !value.content;
    $(`#${prefix}Title`).textContent = value.title || "";
    $(`#${prefix}Content`).textContent = value.content || "";
  });
  $("#promptList").innerHTML = (result.image_prompts || []).map((item, index) => `
    <article class="prompt-item">
      <div class="prompt-item-head"><strong>${index + 1}. ${escapeHtml(item.scene_description || "配图")}</strong><button type="button" data-prompt-index="${index}" title="复制提示词" aria-label="复制提示词"><i data-lucide="copy"></i></button></div>
      <p>${escapeHtml(item.prompt_en || "")}</p>
    </article>
  `).join("");
  $$("[data-prompt-index]").forEach((button) => button.addEventListener("click", () => copyText(result.image_prompts[Number(button.dataset.promptIndex)].prompt_en)));
  $("#resultBadge").hidden = false;
  $("#downloadButton").disabled = false;
  refreshIcons();
}

async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value || "");
    toast("已复制到剪贴板");
  } catch {
    toast("浏览器未允许访问剪贴板", "error");
  }
}

function downloadResult() {
  if (!state.result) return;
  const blob = new Blob([JSON.stringify(state.result, null, 2)], { type: "application/json;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `本土化内容_${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function saveSettings(event) {
  event.preventDefault();
  state.settings = {
    base_url: $("#baseUrlInput").value.trim().replace(/\/$/, ""),
    model: $("#modelInput").value.trim(),
    rpm: Math.max(1, Math.min(120, Number($("#rpmInput").value) || 10)),
    temperature: Number($("#temperatureInput").value),
  };
  localStorage.setItem("yilang-model-settings", JSON.stringify(state.settings));
  $("#settingsDialog").close();
  toast("模型设置已保存");
}

function bindEvents() {
  $$(".source-tab").forEach((button) => button.addEventListener("click", () => switchSource(button.dataset.sourceTab)));
  $$(".workspace-tab").forEach((button) => button.addEventListener("click", () => switchWorkspace(button.dataset.workspaceTab)));
  $$("#platformTargets button").forEach((button) => button.addEventListener("click", () => {
    state.target = button.dataset.target;
    $$("#platformTargets button").forEach((item) => item.classList.toggle("active", item === button));
  }));
  $("#sortSelect").addEventListener("change", loadPosts);
  $("#periodSelect").addEventListener("change", loadPosts);
  $("#refreshButton").addEventListener("click", loadPosts);
  $("#linkForm").addEventListener("submit", importLink);
  $("#startManualButton").addEventListener("click", () => {
    clearSource(false);
    $("#platformInput").value = "Quora";
    setSelectedStatus("手动录入模式", false);
    switchWorkspace("source");
    $("#titleInput").focus();
    if (window.innerWidth <= 860) $("#workspacePanel").scrollIntoView({ behavior: "smooth" });
  });
  $("#clearButton").addEventListener("click", () => clearSource(true));
  $("#downloadButton").addEventListener("click", downloadResult);
  $("#generateButton").addEventListener("click", generate);
  $("#settingsButton").addEventListener("click", () => $("#settingsDialog").showModal());
  $("#closeSettingsButton").addEventListener("click", () => $("#settingsDialog").close());
  $("#cancelSettingsButton").addEventListener("click", () => $("#settingsDialog").close());
  $("#settingsForm").addEventListener("submit", saveSettings);
  $("#temperatureInput").addEventListener("input", (event) => { $("#temperatureOutput").value = Number(event.target.value).toFixed(1); });
  $("#toggleTokenButton").addEventListener("click", () => {
    const input = $("#apiKeyInput");
    input.type = input.type === "password" ? "text" : "password";
  });
  $$("[data-copy]").forEach((button) => button.addEventListener("click", () => {
    const key = button.dataset.copy === "xhs" ? "xiaohongshu" : "toutiao";
    const article = state.result?.[key];
    if (article) copyText(`${article.title}\n\n${article.content}`);
  }));
  $("#commentsInput").addEventListener("input", () => { $("#commentCount").textContent = `${commentsFromEditor().length} 条`; });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !$("#settingsDialog").open) generate();
  });
  $("#collapseButton").addEventListener("click", () => document.body.classList.toggle("sidebar-collapsed"));
}

async function init() {
  refreshIcons();
  readStoredSettings();
  bindEvents();
  await loadCategories();
  await loadPosts();
}

document.addEventListener("DOMContentLoaded", init);
