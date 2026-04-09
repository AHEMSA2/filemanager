(() => {
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const statusEl = document.getElementById('status');
  const authStateEl = document.getElementById('auth-state');
  let token = "";

  const backendBase = new URLSearchParams(window.location.search).get('backend') || window.location.origin;

  function setStatus(msg) {
    statusEl.textContent = msg;
  }

  async function api(path, method = 'GET', body = null, expectBlob = false) {
    const headers = {
      Authorization: `Bearer ${token}`,
    };
    if (body) headers['Content-Type'] = 'application/json';
    const res = await fetch(`${backendBase}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`${res.status} ${txt}`);
    }
    if (expectBlob) return res.blob();
    return res.json();
  }

  async function auth() {
    if (!tg) throw new Error('Telegram WebApp objesi bulunamadi.');
    tg.ready();
    token = tg.initData || '';
    if (!token) throw new Error('initData bos.');
    const data = await fetch(`${backendBase}/api/auth`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ initData: token }),
    });
    if (!data.ok) throw new Error('Mini App auth basarisiz');
    const out = await data.json();
    authStateEl.textContent = `Auth: ${out.user.first_name || out.user.id}`;
  }

  function bindTabs() {
    const tabButtons = [...document.querySelectorAll('.tabs button')];
    tabButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        tabButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
        document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
      });
    });
  }

  async function loadFiles() {
    try {
      const path = document.getElementById('files-path').value.trim() || '/';
      const out = await api('/api/files/list', 'POST', { path });
      const root = document.getElementById('files-list');
      root.innerHTML = '';
      [...out.folders.map(x => ({name: x, type: 'folder'})), ...out.files.map(x => ({name: x, type: 'file'}))].forEach(item => {
        const row = document.createElement('div');
        row.className = 'item';
        const left = document.createElement('span');
        left.textContent = `${item.type === 'folder' ? 'DIR' : 'FILE'} ${item.name}`;
        row.appendChild(left);

        const actions = document.createElement('div');
        actions.className = 'row';

        if (item.type === 'folder') {
          const openBtn = document.createElement('button');
          openBtn.textContent = 'Ac';
          openBtn.onclick = () => {
            document.getElementById('files-path').value = `${out.path.replace(/\/$/, '')}/${item.name}`;
            loadFiles();
          };
          actions.appendChild(openBtn);
        } else {
          const fullPath = `${out.path.replace(/\/$/, '')}/${item.name}`;

          const runBtn = document.createElement('button');
          runBtn.textContent = 'Run';
          runBtn.onclick = async () => {
            try {
              const r = await api('/api/files/run', 'POST', { file: fullPath });
              setStatus(`PID: ${r.pid}`);
            } catch (e) { setStatus(String(e)); }
          };

          const downBtn = document.createElement('button');
          downBtn.textContent = 'Download';
          downBtn.onclick = async () => {
            try {
              const d = await api('/api/files/download_link', 'POST', { file: fullPath });
              window.open(`${backendBase}${d.url}`, '_blank');
            } catch (e) { setStatus(String(e)); }
          };
          actions.appendChild(runBtn);
          actions.appendChild(downBtn);
        }

        row.appendChild(actions);
        root.appendChild(row);
      });
      setStatus(`Files: ${out.path}`);
    } catch (e) { setStatus(String(e)); }
  }

  async function loadProcesses(full) {
    try {
      const f = document.getElementById('proc-filter').value.trim();
      const out = await api(`/api/processes/list?filter=${encodeURIComponent(f)}&full=${full ? '1' : '0'}`);
      const root = document.getElementById('proc-list');
      root.innerHTML = '';
      out.processes.forEach(p => {
        const row = document.createElement('div');
        row.className = 'item';
        const left = document.createElement('span');
        left.textContent = `${p.pid} ${p.name} ${p.cmdline || ''}`;
        const killBtn = document.createElement('button');
        killBtn.textContent = 'Kill';
        killBtn.onclick = async () => {
          try {
            const r = await api('/api/processes/kill', 'POST', { pid: p.pid, sig: 'SIGTERM' });
            setStatus(r.message || 'Kill gonderildi');
            await loadProcesses(full);
          } catch (e) { setStatus(String(e)); }
        };
        row.appendChild(left);
        row.appendChild(killBtn);
        root.appendChild(row);
      });
      setStatus(`Process count: ${out.processes.length}`);
    } catch (e) { setStatus(String(e)); }
  }

  async function loadUSB() {
    try {
      const out = await api('/api/usb/list');
      const root = document.getElementById('usb-list');
      root.innerHTML = '';
      out.devices.forEach(d => {
        const row = document.createElement('div');
        row.className = 'item';
        const label = document.createElement('span');
        label.textContent = `${d.mountpoint} (${d.device})`;
        const btn = document.createElement('button');
        btn.textContent = 'Kopyala';
        btn.onclick = async () => {
          const r = await api('/api/usb/copy', 'POST', { mountpoint: d.mountpoint });
          setStatus(r.message);
        };
        row.appendChild(label);
        row.appendChild(btn);
        root.appendChild(row);
      });
      setStatus(`USB auto: ${out.status.auto_enabled}`);
    } catch (e) { setStatus(String(e)); }
  }

  async function schedulePower(action) {
    try {
      const seconds = Number(document.getElementById('power-seconds').value || 0);
      const out = await api('/api/power/schedule', 'POST', { action, seconds });
      setStatus(out.message);
      await loadPower();
    } catch (e) { setStatus(String(e)); }
  }

  async function cancelPower() {
    try {
      const out = await api('/api/power/cancel', 'POST', {});
      setStatus(out.message);
      await loadPower();
    } catch (e) { setStatus(String(e)); }
  }

  async function loadPower() {
    try {
      const out = await api('/api/power/status');
      const root = document.getElementById('power-status');
      root.innerHTML = '';
      (out.status.scheduled || []).forEach(s => {
        const row = document.createElement('div');
        row.className = 'item';
        row.textContent = `${s.unit} (${s.active ? 'active' : 'inactive'})`;
        root.appendChild(row);
      });
      if (!out.status.scheduled || out.status.scheduled.length === 0) {
        root.textContent = 'Planli islem yok';
      }
    } catch (e) { setStatus(String(e)); }
  }

  async function loadAP() {
    try {
      const out = await api('/api/ap/status');
      const root = document.getElementById('ap-status');
      root.innerHTML = '';
      const hd = document.createElement('div');
      hd.textContent = `nmcli: ${out.status.nmcli_exists} | enabled: ${out.status.enabled}`;
      root.appendChild(hd);
      (out.clients || []).forEach(c => {
        const row = document.createElement('div');
        row.className = 'item';
        row.textContent = c;
        root.appendChild(row);
      });
    } catch (e) { setStatus(String(e)); }
  }

  async function startAP() {
    try {
      const ssid = document.getElementById('ap-ssid').value.trim();
      const password = document.getElementById('ap-password').value.trim();
      const out = await api('/api/ap/start', 'POST', { ssid, password });
      setStatus(out.message);
      await loadAP();
    } catch (e) { setStatus(String(e)); }
  }

  async function stopAP() {
    try {
      const out = await api('/api/ap/stop', 'POST', {});
      setStatus(out.message);
      await loadAP();
    } catch (e) { setStatus(String(e)); }
  }

  async function boot() {
    try {
      bindTabs();
      await auth();
      document.getElementById('files-refresh').onclick = loadFiles;
      document.getElementById('proc-refresh').onclick = () => loadProcesses(false);
      document.getElementById('proc-full').onclick = () => loadProcesses(true);
      document.getElementById('usb-refresh').onclick = loadUSB;
      document.getElementById('power-shutdown').onclick = () => schedulePower('shutdown');
      document.getElementById('power-reboot').onclick = () => schedulePower('reboot');
      document.getElementById('power-cancel').onclick = cancelPower;
      document.getElementById('ap-start').onclick = startAP;
      document.getElementById('ap-stop').onclick = stopAP;

      await Promise.all([loadFiles(), loadProcesses(false), loadUSB(), loadPower(), loadAP()]);
    } catch (e) {
      authStateEl.textContent = 'Auth hata';
      setStatus(String(e));
    }
  }

  boot();
})();
