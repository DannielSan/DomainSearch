document.addEventListener('DOMContentLoaded', async () => {
    // 1. Pega a aba atual do navegador
    let [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    if (!tab) return;

    // Extrai apenas o domínio
    let url = new URL(tab.url);
    let domain = url.hostname.replace("www.", "");

    document.getElementById('current-domain').innerText = domain;

    const btnScan = document.getElementById('btn-scan');
    const btnSeeMore = document.getElementById('btn-see-more');
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
            const response = await fetch(`http://127.0.0.1:8000/api/results/${domain}`, { credentials: "include" });

            // Se retornar erro de autenticação, pedimos pro cara logar
            if (response.status === 401 || response.status === 403 || response.url.includes('/login')) {
                statusArea.style.display = 'block';
                document.getElementById('empty-state-box').style.display = 'none';
                statusArea.innerHTML = `<p style="text-align:center; color:#ef4444; font-size:12px;"><i class="fas fa-lock" style="margin-right:4px;"></i> Por favor, faça login no dashboard primeiro.</p>
                                        <button onclick="window.open('http://127.0.0.1:8000/login', '_blank')" style="background:#4f46e5; color:white; border:none; padding:6px 12px; border-radius:4px; font-size:11px; cursor:pointer; margin-top:8px;">Fazer Login</button>`;
                return;
            }

            const data = await response.json();

            list.innerHTML = '';
            const emptyBox = document.getElementById('empty-state-box');

            if (data.status === "Não iniciado") {
                statusArea.style.display = 'block';
                emptyBox.style.display = 'none';
                btnSeeMore.style.display = 'none';
                return; // Para a execução aqui
            }

            if (data.leads && data.leads.length > 0) {
                statusArea.style.display = 'none';
                emptyBox.style.display = 'none'; // Esconde caixa azul

                // Mostra "Ver mais" se tiver leads
                btnSeeMore.style.display = 'block';

                // Renderiza APENAS os 5 primeiros no popup para não poluir
                data.leads.slice(0, 5).forEach(lead => {
                    const li = document.createElement('li');
                    li.className = 'lead-item';

                    // Define cor e ícone do status
                    let iconColor = lead.status === 'valid' ? '#16a34a' : '#ca8a04';
                    let bgBadge = lead.status === 'valid' ? '#dcfce7' : '#fef9c3';
                    let iconHtml = lead.status === 'valid' ? '<i class="fas fa-check-circle"></i>' : '<i class="fas fa-exclamation-circle"></i>';

                    // Botão do LinkedIn
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
                // Se 0 leads MAS já terminou de escanear (is_scanning === false), mostra erro real
                if (data.is_scanning === false) {
                    statusArea.style.display = 'none';
                    emptyBox.style.display = 'block';
                    btnSeeMore.style.display = 'none';
                } else {
                    // Está escaneando e ainda não achou (polling): 
                    // Garante que a caixa de vazio fique escondida enquanto busca
                    statusArea.style.display = 'none';
                    emptyBox.style.display = 'none';
                }
            }
        } catch (error) {
            console.error("Erro:", error);
            statusArea.style.display = 'block'; // Mostra de volta se der erro
            document.getElementById('empty-state-box').style.display = 'none';
            statusArea.innerHTML = `<p style="text-align:center; color:#ef4444; font-size:12px;">Erro ao conectar API.</p>`;
        }
    }

    // Carrega ao abrir
    loadLeads();

    // Botão Ver Mais
    btnSeeMore.addEventListener('click', () => {
        chrome.tabs.create({ url: `http://127.0.0.1:8000/view/${domain}` });
    });

    // Lógica do Botão de Busca
    btnScan.addEventListener('click', async () => {
        btnScan.disabled = true;
        btnScan.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Buscando...`;
        loading.style.display = 'block';
        list.innerHTML = ''; // Limpa lista visualmente enquanto busca
        btnSeeMore.style.display = 'none';

        try {
            await fetch('http://127.0.0.1:8000/api/scan', {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ domain: domain })
            });

            // Polling: Verifica resultados a cada 2s
            let attempts = 0;
            const maxAttempts = 30; // 60 segundos limite

            const interval = setInterval(async () => {
                attempts++;
                await loadLeads();

                // Se já achou leads reais (que não sejam só os genéricos) ou estourou tempo
                // Assumindo que genéricos são ~5, se tiver > 5 provavelmente achou algo
                if (list.children.length > 0 || attempts >= maxAttempts) {
                    if (attempts >= maxAttempts || list.children.length > 5) {
                        clearInterval(interval);
                        btnScan.disabled = false;
                        btnScan.innerHTML = `<i class="fas fa-search"></i> Buscar Novamente`;
                        loading.style.display = 'none';
                    }
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