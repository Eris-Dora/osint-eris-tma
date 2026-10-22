(() => {
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;

  if (tg) {
    tg.ready();
    tg.expand();
  }

  // Дефолтный адрес бэкенда (можно передать через ?api=https://... или сохранить в настройках UI)
  const urlParams = new URLSearchParams(window.location.search);
  const queryFromUrl = urlParams.get("q") || "";
  const apiFromUrl = urlParams.get("api") || "";

  const STORAGE_KEY_API = "osint_nexus_api_base_url";
  let apiBaseUrl = (apiFromUrl || localStorage.getItem(STORAGE_KEY_API) || "http://localhost:8000").replace(/\/$/, "");

  // DOM-элементы
  const apiStatusDot = document.getElementById("apiStatusDot");
  const settingsToggleBtn = document.getElementById("settingsToggleBtn");
  const apiConfigPanel = document.getElementById("apiConfigPanel");
  const apiBaseUrlInput = document.getElementById("apiBaseUrlInput");
  const saveApiUrlBtn = document.getElementById("saveApiUrlBtn");
  const apiHealthStatus = document.getElementById("apiHealthStatus");

  const searchForm = document.getElementById("searchForm");
  const searchInput = document.getElementById("searchInput");
  const clearInputBtn = document.getElementById("clearInputBtn");
  const categoryTabs = document.getElementById("categoryTabs");
  const statusMessage = document.getElementById("statusMessage");
  const elapsedBadge = document.getElementById("elapsedBadge");
  const skeletonContainer = document.getElementById("skeletonContainer");
  const resultsContainer = document.getElementById("resultsContainer");

  let activeCategory = "all";
  let cachedResults = [];

  apiBaseUrlInput.value = apiBaseUrl;

  function haptic(type = "light") {
    try {
      if (tg && tg.HapticFeedback) {
        tg.HapticFeedback.impactOccurred(type);
      }
    } catch (_) {}
  }

  // Проверка доступности нашего FastAPI бэкенда (/health)
  async function checkBackendHealth() {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 5000);
      const res = await fetch(`${apiBaseUrl}/health`, { signal: controller.signal });
      clearTimeout(timer);

      if (res.ok) {
        apiStatusDot.classList.remove("offline");
        apiHealthStatus.textContent = `✅ Бэкенд активен (${apiBaseUrl})`;
        return true;
      }
    } catch (_) {}

    apiStatusDot.classList.add("offline");
    apiHealthStatus.textContent = `⚠️ Бэкенд спит или не указан (активен автономный режим браузера)`;
    return false;
  }

  // Переключение панели настроек API
  settingsToggleBtn.addEventListener("click", () => {
    haptic("light");
    apiConfigPanel.classList.toggle("hidden");
  });

  saveApiUrlBtn.addEventListener("click", async () => {
    haptic("medium");
    const val = apiBaseUrlInput.value.trim().replace(/\/$/, "");
    if (val) {
      apiBaseUrl = val;
      localStorage.setItem(STORAGE_KEY_API, apiBaseUrl);
      await checkBackendHealth();
      apiConfigPanel.classList.add("hidden");
    }
  });

  // Очистка поля ввода
  searchInput.addEventListener("input", () => {
    clearInputBtn.classList.toggle("hidden", !searchInput.value.trim());
  });

  clearInputBtn.addEventListener("click", () => {
    haptic("light");
    searchInput.value = "";
    clearInputBtn.classList.add("hidden");
    searchInput.focus();
  });

  // Быстрые чипсы для теста
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      haptic("light");
      const sample = chip.getAttribute("data-sample") || "";
      searchInput.value = sample;
      clearInputBtn.classList.remove("hidden");
      executeSearch(sample);
    });
  });

  // Переключение вкладок категорий
  categoryTabs.addEventListener("click", (e) => {
    const btn = e.target.closest(".tab-btn");
    if (!btn) return;
    haptic("light");

    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");

    activeCategory = btn.getAttribute("data-category") || "all";
    renderFilteredCards();
  });

  // Отправка формы поиска
  searchForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const query = searchInput.value.trim();
    if (query.length < 2) return;
    haptic("medium");
    executeSearch(query);
  });

  // Автономный резервный поиск напрямую из браузера (если сервер Render еще просыпается)
  async function runClientFallbackSearch(query) {
    const started = performance.now();
    const tasks = [
      fetch(`https://hn.algolia.com/api/v1/search?query=${encodeURIComponent(query)}&hitsPerPage=8`)
        .then((r) => (r.ok ? r.json() : { hits: [] }))
        .then((d) =>
          (d.hits || []).map((h) => ({
            title: h.title || h.story_title || "HackerNews Mention",
            url: h.url || `https://news.ycombinator.com/item?id=${h.objectID}`,
            snippet: (h.comment_text || `Автор: ${h.author} | Points: ${h.points || 0}`).slice(0, 220),
            source: "HackerNews",
            category: "forums",
            date: (h.created_at || "").slice(0, 10),
          }))
        )
        .catch(() => []),

      fetch(`https://api.github.com/search/repositories?q=${encodeURIComponent(query)}&per_page=6`)
        .then((r) => (r.ok ? r.json() : { items: [] }))
        .then((d) =>
          (d.items || []).map((repo) => ({
            title: repo.full_name,
            url: repo.html_url,
            snippet: repo.description || `Язык: ${repo.language || "N/A"} · ⭐ ${repo.stargazers_count}`,
            source: "GitHub",
            category: "forums",
            date: (repo.updated_at || "").slice(0, 10),
          }))
        )
        .catch(() => []),

      fetch(`https://www.reddit.com/search.json?q=${encodeURIComponent(query)}&limit=8`)
        .then((r) => (r.ok ? r.json() : { data: { children: [] } }))
        .then((d) =>
          ((d.data && d.data.children) || []).map((c) => ({
            title: c.data.title,
            url: `https://www.reddit.com${c.data.permalink}`,
            snippet: (c.data.selftext || `Сабреддит: r/${c.data.subreddit}`).slice(0, 220),
            source: `Reddit · r/${c.data.subreddit}`,
            category: "socials",
            date: "",
          }))
        )
        .catch(() => []),
    ];

    const batches = await Promise.all(tasks);
    const results = batches.flat();
    const counts = {
      all: results.length,
      mentions: results.filter((i) => i.category === "mentions").length,
      socials: results.filter((i) => i.category === "socials").length,
      forums: results.filter((i) => i.category === "forums").length,
    };

    return {
      query,
      elapsed_seconds: ((performance.now() - started) / 1000).toFixed(2),
      counts,
      results,
    };
  }

  async function executeSearch(query) {
    statusMessage.textContent = `Сканирую источники по «${query}»...`;
    elapsedBadge.classList.add("hidden");
    resultsContainer.classList.add("hidden");
    skeletonContainer.classList.remove("hidden");

    try {
      let data = null;
      try {
        const res = await fetch(`${apiBaseUrl}/api/search?q=${encodeURIComponent(query)}&category=all`);
        if (res.ok) {
          data = await res.json();
          apiStatusDot.classList.remove("offline");
        }
      } catch (_) {
        apiStatusDot.classList.add("offline");
      }

      if (!data) {
        data = await runClientFallbackSearch(query);
      }

      cachedResults = data.results || [];
      updateTabCounts(data.counts || {});

      elapsedBadge.textContent = `${data.elapsed_seconds || 0}s`;
      elapsedBadge.classList.remove("hidden");
      statusMessage.textContent = `Найдено совпадений: ${cachedResults.length}`;

      renderFilteredCards();

      if (tg && tg.MainButton) {
        tg.MainButton.setText(`НАЙДЕНО РЕЗУЛЬТАТОВ: ${cachedResults.length}`);
        tg.MainButton.show();
        tg.MainButton.onClick(() => tg.close());
      }
    } catch (err) {
      statusMessage.textContent = `Ошибка при сканировании: ${err.message}`;
    } finally {
      skeletonContainer.classList.add("hidden");
      resultsContainer.classList.remove("hidden");
    }
  }

  function updateTabCounts(counts) {
    document.getElementById("count-all").textContent = counts.all ?? cachedResults.length;
    document.getElementById("count-mentions").textContent = counts.mentions ?? 0;
    document.getElementById("count-socials").textContent = counts.socials ?? 0;
    document.getElementById("count-forums").textContent = counts.forums ?? 0;
  }

  function renderFilteredCards() {
    const list =
      activeCategory === "all"
        ? cachedResults
        : cachedResults.filter((item) => item.category === activeCategory);

    if (!list.length) {
      resultsContainer.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">📭</div>
          <h2>В этой категории пусто</h2>
          <p>Попробуйте переключиться на вкладку «Все» или уточнить поисковый запрос.</p>
        </div>
      `;
      return;
    }

    resultsContainer.innerHTML = list
      .map((item) => {
        const safeTitle = escapeHtml(item.title || "Без названия");
        const safeSnippet = escapeHtml(item.snippet || "Описание отсутствует");
        const safeSource = escapeHtml(item.source || "Web");
        const safeDate = escapeHtml(item.date || "");
        const safeUrl = escapeHtml(item.url || "#");
        const domain = extractDomain(item.url || "");

        return `
          <article class="result-card">
            <div class="card-header">
              <span class="source-tag">${safeSource}</span>
              ${safeDate ? `<span class="date-tag">${safeDate}</span>` : ""}
            </div>
            <a class="card-title" href="${safeUrl}" target="_blank" rel="noopener noreferrer">${safeTitle}</a>
            <p class="card-snippet">${safeSnippet}</p>
            <div class="card-footer">
              <span class="card-domain">${escapeHtml(domain)}</span>
              <a class="open-link" href="${safeUrl}" target="_blank" rel="noopener noreferrer">Открыть ↗</a>
            </div>
          </article>
        `;
      })
      .join("");
  }

  function extractDomain(url) {
    try {
      return new URL(url).hostname.replace(/^www\./, "");
    } catch (_) {
      return url;
    }
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // Первичная инициализация при открытии Mini App
  checkBackendHealth();
  if (queryFromUrl && queryFromUrl.trim().length >= 2) {
    searchInput.value = queryFromUrl.trim();
    clearInputBtn.classList.remove("hidden");
    executeSearch(queryFromUrl.trim());
  }
})();
