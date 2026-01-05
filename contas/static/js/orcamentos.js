
document.addEventListener('DOMContentLoaded', function() {
    carregarOrcamentos();
    carregarCategorias();
});

// --- API Functions ---

function carregarOrcamentos() {
    fetch('/api/orcamentos/')
        .then(response => response.json())
        .then(data => {
            renderizarOrcamentos(data);
        })
        .catch(error => console.error('Erro ao carregar orçamentos:', error))
        .finally(() => {
            document.getElementById('loadingBudgets').style.display = 'none';
            document.getElementById('budgetsGrid').style.display = 'flex';
        });
}

function carregarCategorias() {
    fetch('/api/categorias/')
        .then(response => response.json())
        .then(data => {
            const select = document.getElementById('orcCategoria');
            select.innerHTML = '<option value="">Selecione...</option>';
            data.forEach(cat => {
                const option = document.createElement('option');
                option.value = cat.id;
                option.textContent = cat.nome;
                select.appendChild(option);
            });
        });
}

function salvarOrcamento() {
    const categoriaId = document.getElementById('orcCategoria').value;
    const valorLimite = document.getElementById('orcValorLimite').value;
    const id = document.getElementById('orcamentoId').value;

    if (!categoriaId || !valorLimite) {
        alert("Preencha todos os campos.");
        return;
    }

    const payload = {
        categoria: parseInt(categoriaId),
        valor_limite: parseFloat(valorLimite)
    };

    const method = id ? 'PUT' : 'POST';
    const url = id ? `/api/orcamentos/${id}/` : '/api/orcamentos/';

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
            bootstrap.Modal.getInstance(document.getElementById('modalNovoOrcamento')).hide();
            carregarOrcamentos();
            limparFormOrcamento();
        } else {
            response.json().then(data => {
                if(data.non_field_errors) alert(data.non_field_errors[0]); // Unique constraint
                else alert("Erro ao salvar orçamento.");
            });
        }
    });
}

function editarOrcamento(id, catId, valor) {
    document.getElementById('orcamentoId').value = id;
    document.getElementById('orcCategoria').value = catId;
    document.getElementById('orcValorLimite').value = valor;
    
    // Bloqueia categoria na edição (opcional, simplifica lógica)
    // document.getElementById('orcCategoria').disabled = true;

    const modal = new bootstrap.Modal(document.getElementById('modalNovoOrcamento'));
    modal.show();
}

function excluirOrcamento(id) {
    if(!confirm("Deseja excluir este orçamento?")) return;

    fetch(`/api/orcamentos/${id}/`, {
        method: 'DELETE',
        headers: {
            'X-CSRFToken': getCsrfToken()
        }
    }).then(response => {
        if(response.ok) carregarOrcamentos();
        else alert("Erro ao excluir.");
    });
}

// --- UI Functions ---

function renderizarOrcamentos(lista) {
    const grid = document.getElementById('budgetsGrid');
    grid.innerHTML = '';

    if (lista.length === 0) {
        grid.innerHTML = '<div class="col-12 text-center text-muted"><p>Nenhum orçamento definido.</p></div>';
        return;
    }

    lista.sort((a, b) => b.percentual - a.percentual); // Ordena pelos mais críticos

    lista.forEach(orc => {
        const percent = Math.min(100, orc.percentual);
        const valorGasto = parseFloat(orc.valor_gasto);
        const valorLimite = parseFloat(orc.valor_limite);
        
        // Dynamic Color Logic: 
        // 0-50%: Green to Yellow
        // 50-100%: Yellow to Red
        let barColorClass = 'bg-success';
        if (percent > 50 && percent < 90) barColorClass = 'bg-warning';
        if (percent >= 90) barColorClass = 'bg-danger';

        const cardHtml = `
            <div class="col-md-6 col-lg-4 mb-4">
                <div class="card h-100 shadow-sm border-0">
                    <div class="card-body">
                         <div class="d-flex justify-content-between align-items-center mb-2">
                            <h5 class="card-title fw-bold text-dark mb-0">${orc.categoria_nome}</h5>
                            <div class="dropdown">
                                <button class="btn btn-link text-muted p-0" data-bs-toggle="dropdown">
                                    <i class="bi bi-three-dots-vertical"></i>
                                </button>
                                <ul class="dropdown-menu dropdown-menu-end">
                                    <li><a class="dropdown-item" href="#" onclick="editarOrcamento(${orc.id}, ${orc.categoria}, ${orc.valor_limite})">Editar</a></li>
                                    <li><a class="dropdown-item text-danger" href="#" onclick="excluirOrcamento(${orc.id})">Excluir</a></li>
                                </ul>
                            </div>
                        </div>

                        <div class="d-flex justify-content-between align-items-end mb-1">
                             <span class="text-muted small">Gasto Mês Atual</span>
                             <span class="fw-bold ${percent >= 100 ? 'text-danger' : 'text-dark'}">
                                R$ ${valorGasto.toLocaleString('pt-BR', {minimumFractionDigits: 2})} 
                                <span class="text-secondary fw-normal">/ ${valorLimite.toLocaleString('pt-BR', {minimumFractionDigits: 0})}</span>
                             </span>
                        </div>

                        <div class="progress" style="height: 12px; border-radius: 6px;">
                            <div class="progress-bar ${barColorClass}" role="progressbar" 
                                 style="width: ${percent}%; transition: width 0.6s ease;" 
                                 aria-valuenow="${percent}" aria-valuemin="0" aria-valuemax="100">
                            </div>
                        </div>
                        <div class="text-end mt-1">
                            <small class="text-muted fw-bold">${Math.round(percent)}%</small>
                        </div>
                    </div>
                </div>
            </div>
        `;
        grid.innerHTML += cardHtml;
    });
}

function limparFormOrcamento() {
    document.getElementById('formOrcamento').reset();
    document.getElementById('orcamentoId').value = '';
    // document.getElementById('orcCategoria').disabled = false;
}

// Helpers (Reused logic, keep DRY if possible, but duplicating for simplicity in this file)
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
    const inputFn = document.querySelector('[name=csrfmiddlewaretoken]');
    return inputFn ? inputFn.value : '';
}
