/**
 * 小米招聘官网 - 职位搜索（transfer-hr searchJobPage API）
 */
(function () {
  if (document.body.dataset.page !== 'opportunities') return;

  const list = document.querySelector('.jobs-list');
  if (!list) return;

  const prevBtn = document.getElementById('jobsPrev');
  const nextBtn = document.getElementById('jobsNext');
  const pageInfo = document.getElementById('jobsPageInfo');
  const countEl = document.getElementById('jobCount');
  const searchInput = document.querySelector('.jobs-search-input');
  const heroSearch = document.querySelector('[data-hero-search]');
  const heroForm = heroSearch ? heroSearch.closest('form') : null;

  const JOB_API_BASE = window.JOB_API || (
    location.hostname === 'localhost' || location.hostname === '127.0.0.1' ? '' : '/website'
  );
  const PER_PAGE = 10;
  const PROJECT_TYPE_MAP = {
    all: null,
    '社招': 1,
    '校招': 2,
    '实习': 3,
    '顶尖人才': 4,
  };

  const urlParams = new URLSearchParams(window.location.search);
  let keyword = urlParams.get('q') || '';
  let activeCity = urlParams.get('city') || 'all';
  let activeProject = urlParams.get('project') || 'all';
  let currentPage = Math.max(0, (parseInt(urlParams.get('page'), 10) || 1) - 1);
  let pageTotal = 1;
  let loading = false;
  let debounceTimer = null;

  if (searchInput && keyword) searchInput.value = keyword;
  if (heroSearch && keyword) heroSearch.value = keyword;

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function previewText(text) {
    const line = String(text || '').split('\n').find((part) => part.trim());
    if (!line) return '';
    return line.trim().slice(0, 120);
  }

  function syncUrl() {
    const params = new URLSearchParams();
    if (activeCity !== 'all') params.set('city', activeCity);
    if (activeProject !== 'all') params.set('project', activeProject);
    if (keyword.trim()) params.set('q', keyword.trim());
    if (currentPage > 0) params.set('page', String(currentPage + 1));
    const qs = params.toString();
    history.replaceState(null, '', 'opportunities.html' + (qs ? '?' + qs : ''));
  }

  function setFilterActive(group, value) {
    document.querySelectorAll(`[data-filter="${group}"] .filter-tab`).forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.value === value);
    });
  }

  if (activeCity !== 'all') setFilterActive('city', activeCity);
  if (activeProject !== 'all') setFilterActive('project', activeProject);

  function renderLoading() {
    list.innerHTML = '<div class="jobs-placeholder reveal"><div class="status"><span class="dot"></span>加载中</div><p>正在搜索职位...</p></div>';
    if (countEl) countEl.textContent = '—';
    if (pageInfo) pageInfo.textContent = '—';
    if (prevBtn) prevBtn.disabled = true;
    if (nextBtn) nextBtn.disabled = true;
  }

  function renderEmpty() {
    list.innerHTML = '<div class="jobs-placeholder reveal"><h3>暂无匹配职位</h3><p>试试调整关键词或更换城市筛选。</p></div>';
  }

  function renderError(message) {
    list.innerHTML = `<div class="jobs-placeholder reveal"><h3>职位加载失败</h3><p>${escapeHtml(message || '请稍后重试')}</p></div>`;
  }

  function renderJobs(items) {
    if (!items.length) {
      renderEmpty();
      return;
    }

    list.innerHTML = items.map((item) => {
      const cities = (item.cityZhNames || []).join(' / ');
      const desc = previewText(item.description);
      const applyUrl = item.url || '#';
      return `
        <article class="job-card">
          <div class="job-info">
            <div class="job-title-row">
              <a class="job-title" href="${escapeHtml(applyUrl)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>
              <div class="job-tags">
                ${cities ? `<span>${escapeHtml(cities)}</span>` : ''}
              </div>
            </div>
            ${desc ? `<p class="job-desc">${escapeHtml(desc)}</p>` : ''}
          </div>
          <div class="job-action">
            <a href="${escapeHtml(applyUrl)}" class="job-apply" target="_blank" rel="noopener">投递</a>
          </div>
        </article>
      `;
    }).join('');
  }

  function updatePagination(total) {
    pageTotal = Math.max(1, Math.ceil(total / PER_PAGE));
    if (currentPage >= pageTotal) currentPage = pageTotal - 1;
    if (pageInfo) pageInfo.textContent = `${currentPage + 1}/${pageTotal}`;
    if (prevBtn) prevBtn.disabled = currentPage <= 0;
    if (nextBtn) nextBtn.disabled = currentPage >= pageTotal - 1;
    if (countEl) countEl.textContent = total;
  }

  async function fetchJobs() {
    if (loading) return;
    loading = true;
    renderLoading();

    const params = new URLSearchParams();
    params.set('keyword', keyword.trim());
    params.set('cityZhNames', activeCity === 'all' ? '' : activeCity);
    params.set('pageSize', String(PER_PAGE));
    params.set('pageNum', String(currentPage + 1));

    const type = PROJECT_TYPE_MAP[activeProject];
    if (type) params.set('type', String(type));

    try {
      const res = await fetch(`${JOB_API_BASE}/api/agent/searchJobPage?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (json.code !== 0 || !json.data) throw new Error(json.message || '接口返回异常');

      updatePagination(json.data.total || 0);
      renderJobs(json.data.list || []);
      syncUrl();
    } catch (err) {
      renderError(err.message);
      if (countEl) countEl.textContent = '0';
      if (pageInfo) pageInfo.textContent = '—';
      if (prevBtn) prevBtn.disabled = true;
      if (nextBtn) nextBtn.disabled = true;
    } finally {
      loading = false;
    }
  }

  function scheduleSearch(resetPage) {
    if (resetPage) currentPage = 0;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(fetchJobs, 350);
  }

  document.querySelectorAll('[data-filter="city"] .filter-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      trackClickEvent('加入我们-城市筛选-' + btn.dataset.value);
      activeCity = btn.dataset.value;
      setFilterActive('city', activeCity);
      scheduleSearch(true);
    });
  });

  document.querySelectorAll('[data-filter="project"] .filter-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      activeProject = btn.dataset.value;
      setFilterActive('project', activeProject);
      scheduleSearch(true);
    });
  });

  if (searchInput) {
    searchInput.addEventListener('input', () => {
      keyword = searchInput.value;
      if (heroSearch) heroSearch.value = keyword;
      scheduleSearch(true);
    });
  }

  if (heroForm && heroSearch) {
    heroForm.addEventListener('submit', (e) => {
      e.preventDefault();
      trackClickEvent('加入我们-搜索按钮');
      keyword = heroSearch.value.trim();
      if (searchInput) searchInput.value = keyword;
      scheduleSearch(true);
      document.querySelector('.jobs')?.scrollIntoView({ behavior: 'smooth' });
    });
  }

  document.querySelectorAll('.loc-pcard[data-filter-city]').forEach((card) => {
    card.addEventListener('click', () => {
      trackClickEvent('加入我们-工作地点-' + card.dataset.filterCity);
      activeCity = card.dataset.filterCity;
      currentPage = 0;
      setFilterActive('city', activeCity);
      fetchJobs();
      document.querySelector('.jobs')?.scrollIntoView({ behavior: 'smooth' });
    });
  });

  if (prevBtn) {
    prevBtn.addEventListener('click', () => {
      if (currentPage > 0) {
        currentPage -= 1;
        fetchJobs();
      }
    });
  }

  if (nextBtn) {
    nextBtn.addEventListener('click', () => {
      if (currentPage < pageTotal - 1) {
        currentPage += 1;
        fetchJobs();
      }
    });
  }

  fetchJobs();
})();
