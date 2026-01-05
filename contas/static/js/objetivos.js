
document.addEventListener('DOMContentLoaded', function() {
    carregarObjetivos();
    carregarContas();
});

// --- API Functions ---

function carregarObjetivos() {
    fetch('/api/objetivos/')
        .then(response => response.json())
        .then(data => {
            renderizarObjetivos(data);
            atualizarTotal(data);
        })
        .catch(error => console.error('Erro ao carregar objetivos:', error))
        .finally(() => {
            document.getElementById('loadingGoals').style.display = 'none';
            document.getElementById('goalsGrid').style.display = 'flex';
        });
}

function carregarContas() {
    fetch('/api/contas/')
        .then(response => response.json())
        .then(data => {
            const select = document.getElementById('movConta');
            select.innerHTML = '';
            data.forEach(conta => {
                const option = document.createElement('option');
                option.value = conta.id;
                option.textContent = `${conta.nome} (R$ ${conta.saldo_atual.toLocaleString('pt-BR', {minimumFractionDigits: 2})})`;
                select.appendChild(option);
            });
        });
}

function salvarObjetivo() {
    const nome = document.getElementById('objNome').value;
    const valorAlvo = document.getElementById('objValorAlvo').value;
    const dataLimite = document.getElementById('objDataLimite').value;
    const cor = document.getElementById('objCor').value;
    const icone = document.getElementById('objIcone').value;
    const id = document.getElementById('objetivoId').value;

    if (!nome || !valorAlvo) {
        alert("Preencha os campos obrigatórios.");
        return;
    }

    const payload = {
        nome: nome,
        valor_alvo: parseFloat(valorAlvo),
        data_limite: dataLimite || null,
        cor: cor,
        icone: icone
    };

    const method = id ? 'PUT' : 'POST';
    const url = id ? `/api/objetivos/${id}/` : '/api/objetivos/';

    fetch(url, {
        method: method,
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify(payload)
    })
    .then(response => {
        if (response.ok) {
            bootstrap.Modal.getInstance(document.getElementById('modalNovoObjetivo')).hide();
            carregarObjetivos();
            limparFormObjetivo();
        } else {
            alert("Erro ao salvar objetivo.");
        }
    });
}

function abrirModalMovimentar(id, tipo, nome) {
    document.getElementById('movObjetivoId').value = id;
    document.getElementById('movTipo').value = tipo;
    
    const titulo = tipo === 'depositar' ? 'Depositar' : 'Resgatar';
    const btnClass = tipo === 'depositar' ? 'btn-success' : 'btn-warning';
    const labelConta = tipo === 'depositar' ? 'Conta de Origem' : 'Conta de Destino';
    
    document.getElementById('modalMovTitle').textContent = `${titulo} - ${nome}`;
    document.getElementById('labelContaMov').textContent = labelConta;
    document.getElementById('btnConfirmMov').textContent = titulo;
    document.getElementById('btnConfirmMov').className = `btn ${btnClass}`;
    document.getElementById('movValor').value = '';

    const modal = new bootstrap.Modal(document.getElementById('modalMovimentar'));
    modal.show();
}

function confirmarMovimentacao() {
    const id = document.getElementById('movObjetivoId').value;
    const tipo = document.getElementById('movTipo').value;
    const valor = document.getElementById('movValor').value;
    const contaId = document.getElementById('movConta').value;

    if (!valor || !contaId) {
        alert("Preencha todos os campos.");
        return;
    }

    const url = `/api/objetivos/${id}/${tipo}/`; // /api/objetivos/1/depositar/

    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({
            valor: parseFloat(valor),
            conta_id: parseInt(contaId)
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            alert(data.error);
        } else {
            bootstrap.Modal.getInstance(document.getElementById('modalMovimentar')).hide();
            carregarObjetivos();
            // Opcional: Recarregar contas se estiver mostrando saldo em outro lugar
            carregarContas(); 
        }
    })
    .catch(err => alert("Erro na comunicação com o servidor."));
}


// --- UI Functions ---

function renderizarObjetivos(lista) {
    const grid = document.getElementById('goalsGrid');
    grid.innerHTML = '';

    if (lista.length === 0) {
        grid.innerHTML = '<div class="col-12 text-center text-muted"><p>Nenhum objetivo criado ainda.</p></div>';
        return;
    }

    lista.forEach(obj => {
        const percent = Math.min(100, (obj.valor_atual / obj.valor_alvo) * 100);
        const cardHtml = `
            <div class="col-md-4 mb-4">
                <div class="card h-100 shadow-sm border-0">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-start mb-3">
                            <div class="icon-sq d-flex align-items-center justify-content-center text-white rounded-3 shadow-sm" 
                                 style="width: 48px; height: 48px; background-color: ${obj.cor};">
                                <i class="${obj.icone || 'fas fa-piggy-bank'} fa-lg"></i>
                            </div>
                            <div class="dropdown">
                                <button class="btn btn-link text-muted p-0" data-bs-toggle="dropdown">
                                    <i class="bi bi-three-dots-vertical"></i>
                                </button>
                                <ul class="dropdown-menu dropdown-menu-end">
                                    <li><a class="dropdown-item" href="#" onclick="editarObjetivo(${obj.id})">Editar</a></li>
                                    <li><a class="dropdown-item text-danger" href="#" onclick="excluirObjetivo(${obj.id})">Excluir</a></li>
                                </ul>
                            </div>
                        </div>
                        
                        <h5 class="card-title fw-bold text-dark">${obj.nome}</h5>
                        <div class="d-flex justify-content-between mb-1">
                            <small class="text-muted">Guardado</small>
                            <span class="fw-bold" style="color: ${obj.cor}">R$ ${parseFloat(obj.valor_atual).toLocaleString('pt-BR', {minimumFractionDigits: 2})}</span>
                        </div>
                        
                        <div class="progress mb-2" style="height: 8px;">
                            <div class="progress-bar" role="progressbar" 
                                 style="width: ${percent}%; background-color: ${obj.cor};" 
                                 aria-valuenow="${percent}" aria-valuemin="0" aria-valuemax="100">
                            </div>
                        </div>
                        
                        <div class="d-flex justify-content-between text-muted small mb-4">
                            <span>Meta: R$ ${parseFloat(obj.valor_alvo).toLocaleString('pt-BR', {minimumFractionDigits: 2})}</span>
                            <span>${Math.round(percent)}%</span>
                        </div>

                        <div class="d-grid gap-2 d-flex">
                            <button class="btn btn-outline-success flex-grow-1 btn-sm" onclick="abrirModalMovimentar(${obj.id}, 'depositar', '${obj.nome}')">
                                <i class="bi bi-plus-lg"></i> Guardar
                            </button>
                            <button class="btn btn-outline-secondary flex-grow-1 btn-sm" onclick="abrirModalMovimentar(${obj.id}, 'resgatar', '${obj.nome}')">
                                <i class="bi bi-dash-lg"></i> Resgatar
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        grid.innerHTML += cardHtml;
    });
}

function atualizarTotal(lista) {
    const total = lista.reduce((acc, curr) => acc + parseFloat(curr.valor_atual), 0);
    document.getElementById('totalAcumulado').textContent = 
        `R$ ${total.toLocaleString('pt-BR', {minimumFractionDigits: 2})}`;
}

function limparFormObjetivo() {
    document.getElementById('formObjetivo').reset();
    document.getElementById('objetivoId').value = '';
}

// Helpers
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function getCsrfToken() {
    const validToken = getCookie('csrftoken');
    if (validToken) return validToken;
    
    // Fallback: Tenta pegar do input hidden se existir
    const inputFn = document.querySelector('[name=csrfmiddlewaretoken]');
    return inputFn ? inputFn.value : '';
}
