document.addEventListener('DOMContentLoaded', async () => {
    // 1. Pega a aba atual do navegador
    let [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    if (!tab) return;

    // Extrai apenas o domínio
    let url = new URL(tab.url);
    let domain = url.hostname.replace("www.", "");

    document.getElementById('current-domain').innerText = domain;

    const btnScan = document.getElementById('btn-scan');
    const list = document.getElementById('results');
    const loading = document.getElementById('loading');
    const statusArea = document.getElementById('status-area');

    // Carrega ícones do FontAwesome dinamicamente se não estiverem carregados
    if (!document.getElementById('fa-styles')) {
        let link = document.createElement('link');
        link.id = 'fa-styles';
        link.rel = 'stylesheet';
        link.href = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css';
        document.head.appendChild(link);
    }

    // Função para buscar e desenhar os leads
    async function loadLeads() {
        try {
            const response = await fetch(`http://127.0.0.1:8000/api/results/${domain}`);
            const data = await response.json();

            list.innerHTML = '';

            if (data.leads && data.leads.length > 0) {
                statusArea.style.display = 'none';

                data.leads.forEach(lead => {
                    const li = document.createElement('li');
                    li.className = 'lead-item';

                    // Define cor e ícone do status
                    let iconColor = lead.status === 'valid' ? '#16a34a' : '#ca8a04';
                    let bgBadge = lead.status === 'valid' ? '#dcfce7' : '#fef9c3';
                    let iconHtml = lead.status === 'valid' ? '<i class="fas fa-check-circle"></i>' : '<i class="fas fa-exclamation-circle"></i>';

                    // Botão do LinkedIn (só aparece se tiver link no banco)
                    let linkedinBtn = lead.linkedin_url
                        ? `<a href="${lead.linkedin_url}" target="_blank" title="Abrir LinkedIn" style="color:#0077b5; margin-left:8px; font-size:14px; text-decoration:none;"><i class="fab fa-linkedin"></i></a>`
                        : '';

                    // Formata o nome completo
                    let fullName = `${lead.first_name} ${lead.last_name || ''}`.trim();

                    li.innerHTML = `
                        <div style="display:flex; flex-direction:column; max-width: 65%;">
                            <div style="display:flex; align-items:center;">
                                <span class="lead-email" style="font-weight:600; color:#334155;">${lead.email}</span>
                                ${linkedinBtn}
                            </div>
                            <span style="font-size:11px; color:#64748b; margin-top:2px;">
                                <i class="fas fa-user-tie" style="font-size:10px; margin-right:3px;"></i> ${fullName}
                                <span style="color:#94a3b8;"> • ${lead.job_title || 'Contato'}</span>
                            </span>
                        </div>
                        <span class="lead-status" style="background:${bgBadge}; color:${iconColor}; font-size:10px; padding:2px 8px; border-radius:12px; display:flex; align-items:center; gap:4px; height:fit-content;">
                            ${iconHtml} ${lead.status}
                        </span>
                    `;
                    list.appendChild(li);
                });
            } else {
                statusArea.style.display = 'block';
                statusArea.innerHTML = `<p style="text-align:center; color:#64748b; font-size:12px;">Nenhum lead encontrado ainda.</p>`;
            }
        } catch (error) {
            console.error("Erro:", error);
            statusArea.innerHTML = `<p style="text-align:center; color:#ef4444; font-size:12px;">Erro ao conectar API.</p>`;
        }
    }

    // Carrega ao abrir
    loadLeads();

    // Lógica do Botão de Busca
    btnScan.addEventListener('click', async () => {
        btnScan.disabled = true;
        btnScan.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Buscando...`;
        loading.style.display = 'block';

        try {
            await fetch('http://127.0.0.1:8000/api/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ domain: domain })
            });

            // Polling: Verifica resultados a cada 2s
            let attempts = 0;
            const maxAttempts = 30; // 60 segundos limite

            const interval = setInterval(async () => {
                attempts++;
                await loadLeads();

                // Se já achou mais que os genéricos (8) ou estourou tempo
                if (list.children.length > 8 || attempts >= maxAttempts) {
                    clearInterval(interval);
                    btnScan.disabled = false;
                    btnScan.innerHTML = `<i class="fas fa-search"></i> Buscar Novamente`;
                    loading.style.display = 'none';
                }
            }, 2000);

        } catch (error) {
            alert("Erro: O servidor Python está rodando?");
            btnScan.disabled = false;
            btnScan.innerText = "Buscar E-mails";
            loading.style.display = 'none';
        }
    });
});