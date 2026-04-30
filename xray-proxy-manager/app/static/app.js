async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json"
    },
    ...options
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Request failed: ${response.status}`);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

function badge(ok) {
  const label = ok ? "OK" : "Fail";
  const cssClass = ok ? "ok" : "bad";
  return `<span class="badge ${cssClass}">${label}</span>`;
}

async function loadStatus() {
  const status = await fetchJson("/api/system/status");
  const root = document.getElementById("status");
  root.innerHTML = `
    <div class="status-item"><span>Xray service</span>${badge(status.xray_active)}</div>
    <div class="status-item"><span>Manager service</span>${badge(status.manager_active)}</div>
    <div class="status-item"><span>Config validation</span>${badge(status.config_ok)}</div>
    <div class="status-item"><span>Users</span><strong>${status.users}</strong></div>
    <div class="status-item"><span>Domains</span><strong>${status.domains}</strong></div>
  `;
}

function userCard(user) {
  return `
    <article class="user-card">
      <div class="user-meta">
        <p><strong>${user.name}</strong></p>
        <p>UUID: <code>${user.uuid}</code></p>
        <p>Created: ${new Date(user.created_at).toLocaleString()}</p>
      </div>
      <div class="user-config">
        <p>VLESS link</p>
        <code>${user.vless_url}</code>
      </div>
      <div class="user-actions">
        <img class="qr" src="/api/users/${user.uuid}/qrcode" alt="QR for ${user.name}">
        <button type="button" data-copy="${user.vless_url}">Copy link</button>
        <button type="button" data-delete="${user.uuid}">Remove</button>
      </div>
    </article>
  `;
}

async function loadUsers() {
  const users = await fetchJson("/api/users");
  const root = document.getElementById("users");
  root.innerHTML = users.map(userCard).join("") || "<p class='hint'>No users yet.</p>";
}

async function loadDomains() {
  const payload = await fetchJson("/api/domains");
  document.getElementById("domains").value = payload.domains.join("\n");
}

async function refresh() {
  await Promise.all([loadStatus(), loadUsers(), loadDomains()]);
}

document.getElementById("user-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.getElementById("user-name");
  await fetchJson("/api/users", {
    method: "POST",
    body: JSON.stringify({ name: input.value.trim() })
  });
  input.value = "";
  await refresh();
});

document.getElementById("save-domains").addEventListener("click", async () => {
  const domains = document.getElementById("domains").value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

  await fetchJson("/api/domains", {
    method: "PUT",
    body: JSON.stringify({ domains })
  });

  await refresh();
});

document.getElementById("users").addEventListener("click", async (event) => {
  const copyValue = event.target.getAttribute("data-copy");
  const deleteUuid = event.target.getAttribute("data-delete");

  if (copyValue) {
    await navigator.clipboard.writeText(copyValue);
    return;
  }

  if (deleteUuid) {
    await fetchJson(`/api/users/${deleteUuid}`, { method: "DELETE" });
    await refresh();
  }
});

refresh().catch((error) => {
  alert(error.message);
});
