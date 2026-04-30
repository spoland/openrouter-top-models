(function () {
  const els = {
    modelCount: document.getElementById('model-count'),
    lastUpdated: document.getElementById('last-updated'),
    topTabs: document.querySelectorAll('.top-tab'),
    viewDesc: document.getElementById('view-desc'),
    topViewGrid: document.getElementById('top-view-grid'),
    tabs: document.querySelectorAll('.tab'),
    categoryDesc: document.getElementById('category-desc'),
    topList: document.getElementById('top-list'),
    nonFrontierList: document.getElementById('non-frontier-list'),
  };

  let data = null;

  function fmtDate(iso) {
    if (!iso) return 'N/A';
    const d = new Date(iso);
    return d.toLocaleString();
  }

  function fmtPrice(val) {
    if (val === undefined || val === null) return 'N/A';
    const v = parseFloat(val);
    if (v === 0) return 'Free';
    if (v < 0.001) return `$${v.toFixed(4)}`;
    return `$${v.toFixed(2)}`;
  }

  function rankClass(i) {
    if (i === 0) return 'gold';
    if (i === 1) return 'silver';
    if (i === 2) return 'bronze';
    return '';
  }

  function makeCard(model, index, showBenchmark) {
    const name = model.name || model.id;
    const provider = model._provider || (model.id || '').split('/')[0];
    const frontier = model._frontier;
    const score = model._score;
    const benchmarkScore = model._benchmark_score;

    const arch = model.architecture || {};
    const inputs = arch.input_modalities || [];
    const params = model.supported_parameters || [];

    const chips = [];
    if (showBenchmark && benchmarkScore != null) {
      chips.push(`<span class="chip benchmark">Benchmark: ${benchmarkScore}</span>`);
    }
    if (frontier) chips.push('<span class="chip frontier">Frontier</span>');
    else chips.push('<span class="chip non-frontier">Non-Frontier</span>');

    if (inputs.includes('image')) chips.push('<span class="chip">Vision</span>');
    if (inputs.includes('audio') || inputs.includes('video')) chips.push('<span class="chip">Multimodal</span>');
    if (params.includes('tools')) chips.push('<span class="chip">Tools</span>');
    if (params.includes('reasoning')) chips.push('<span class="chip">Reasoning</span>');
    if (params.includes('structured_outputs')) chips.push('<span class="chip">JSON</span>');

    const ctx = model.context_length ? `${model.context_length.toLocaleString()} ctx` : '';
    if (ctx) chips.push(`<span class="chip">${ctx}</span>`);

    const prompt = fmtPrice(model._prompt_price_1m);
    const completion = fmtPrice(model._completion_price_1m);
    const orUrl = `https://openrouter.ai/models/${encodeURIComponent(model.id || '')}`;

    const html = `
      <div class="model-card">
        <div class="rank-row">
          <div class="rank-badge ${rankClass(index)}">${index + 1}</div>
          <a class="model-name" href="${orUrl}" target="_blank" rel="noopener" title="${name}">${name}</a>
        </div>
        <div class="provider-tag">${provider}</div>
        <div class="chips">${chips.join('')}</div>
        <div class="pricing-line">
          <span>Prompt: ${prompt}/1M</span>
          <span>Completion: ${completion}/1M</span>
        </div>
        <div class="score-line">${showBenchmark && benchmarkScore != null ? `Benchmark Score: ${benchmarkScore}` : `Score: ${score}`}</div>
      </div>
    `;
    return html;
  }

  function renderTopView(view) {
    let models, description;
    switch (view) {
      case 'coding-benchmarks':
        models = data.coding_benchmarks;
        description = data.coding_benchmarks_description;
        break;
      case 'intelligence-benchmarks':
        models = data.intelligence_benchmarks;
        description = data.intelligence_benchmarks_description;
        break;
      default:
        models = data.best_general;
        description = data.best_general_description;
    }

    if (!models || models.length === 0) {
      els.topViewGrid.innerHTML = '<div class="error">No data available</div>';
      return;
    }

    els.topViewGrid.innerHTML = models
      .slice(0, 10)
      .map((m, i) => makeCard(m, i, view !== 'best-general'))
      .join('');

    if (description) {
      els.viewDesc.querySelector('.methodology-text').innerHTML = description;
    }
  }

  function renderCategory(cat) {
    const catData = data.categories[cat];
    if (!catData) {
      els.topList.innerHTML = '<div class="error">No data</div>';
      els.nonFrontierList.innerHTML = '<div class="error">No data</div>';
      els.categoryDesc.classList.remove('visible');
      return;
    }
    els.topList.innerHTML = catData.top.map((m, i) => makeCard(m, i, false)).join('');
    els.nonFrontierList.innerHTML = catData.non_frontier.map((m, i) => makeCard(m, i, false)).join('');

    if (catData.description) {
      els.categoryDesc.querySelector('.methodology-text').innerHTML = catData.description;
      els.categoryDesc.classList.add('visible');
    } else {
      els.categoryDesc.classList.remove('visible');
    }
  }

  function setActiveTopTab(view) {
    els.topTabs.forEach(t => {
      if (t.dataset.view === view) t.classList.add('active');
      else t.classList.remove('active');
    });
  }

  function setActiveTab(cat) {
    els.tabs.forEach(t => {
      if (t.dataset.cat === cat) t.classList.add('active');
      else t.classList.remove('active');
    });
  }

  async function load() {
    try {
      const res = await fetch('/api/data');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();

      els.modelCount.textContent = `${data.model_count || '?'} models indexed`;
      els.lastUpdated.textContent = `Updated: ${fmtDate(data.updated_at)}`;

      const activeTop = document.querySelector('.top-tab.active');
      renderTopView(activeTop ? activeTop.dataset.view : 'best-general');

      const active = document.querySelector('.tab.active');
      renderCategory(active ? active.dataset.cat : 'programming');
    } catch (e) {
      console.error(e);
      els.topViewGrid.innerHTML = `<div class="error">Failed to load data: ${e.message}</div>`;
      els.topList.innerHTML = `<div class="error">Failed to load data</div>`;
      els.nonFrontierList.innerHTML = `<div class="error">Failed to load data</div>`;
    }
  }

  els.topTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      setActiveTopTab(tab.dataset.view);
      renderTopView(tab.dataset.view);
    });
  });

  els.tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      setActiveTab(tab.dataset.cat);
      renderCategory(tab.dataset.cat);
    });
  });

  load();
})();
