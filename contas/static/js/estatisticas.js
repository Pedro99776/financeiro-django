
document.addEventListener('DOMContentLoaded', function() {
    carregarResumo();
    carregarHistorico();
    carregarCategoriasChart();
    carregarMaioresGastos();
});

const ctxHistorico = document.getElementById('chartHistorico').getContext('2d');
const ctxCategorias = document.getElementById('chartCategorias').getContext('2d');

let chartHistoricoInstance = null;
let chartCategoriasInstance = null;

// --- Data Fetching ---

function carregarResumo() {
    fetch('/api/analytics/resumo/')
        .then(res => res.json())
        .then(data => {
            document.getElementById('kpiReceitas').textContent = `R$ ${parseFloat(data.total_receitas).toLocaleString('pt-BR', {minimumFractionDigits: 2})}`;
            document.getElementById('kpiDespesas').textContent = `R$ ${parseFloat(data.total_despesas).toLocaleString('pt-BR', {minimumFractionDigits: 2})}`;
            document.getElementById('kpiSaldo').textContent = `R$ ${parseFloat(data.saldo).toLocaleString('pt-BR', {minimumFractionDigits: 2})}`;
            
            // Saving Rate
            let rate = 0;
            if(data.total_receitas > 0) {
               rate = ((data.total_receitas - data.total_despesas) / data.total_receitas) * 100;
            }
            document.getElementById('kpiPoupanca').textContent = `${rate.toFixed(1)}%`;
            document.getElementById('kpiPoupanca').className = rate >= 0 ? 'h2 fw-bold text-success' : 'h2 fw-bold text-danger';
        });
}

function carregarHistorico() {
    fetch('/api/analytics/historico_anual/')
        .then(res => res.json())
        .then(data => {
            const labels = data.map(d => d.mes_ano);
            const receitas = data.map(d => d.receitas);
            const despesas = data.map(d => d.despesas);

            if(chartHistoricoInstance) chartHistoricoInstance.destroy();

            chartHistoricoInstance = new Chart(ctxHistorico, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [
                        { label: 'Receitas', data: receitas, backgroundColor: '#198754', borderRadius: 4 },
                        { label: 'Despesas', data: despesas, backgroundColor: '#dc3545', borderRadius: 4 }
                    ]
                },
                options: {
                    responsive: true,
                    plugins: { legend: { position: 'top' } },
                    scales: { 
                        y: { beginAtZero: true } 
                    }
                }
            });
        });
}

function carregarCategoriasChart() {
    fetch('/api/analytics/gastos_por_categoria/')
        .then(res => res.json())
        .then(data => {
            const labels = data.map(d => d.categoria);
            const values = data.map(d => d.total);
            // Simple Palette
            const colors = ['#0d6efd', '#6610f2', '#6f42c1', '#d63384', '#dc3545', '#fd7e14', '#ffc107', '#198754', '#20c997', '#0dcaf0'];

            if(chartCategoriasInstance) chartCategoriasInstance.destroy();

            chartCategoriasInstance = new Chart(ctxCategorias, {
                type: 'doughnut',
                data: {
                    labels: labels,
                    datasets: [{
                        data: values,
                        backgroundColor: colors.slice(0, labels.length),
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    plugins: { legend: { position: 'right' } }
                }
            });
        });
}

function carregarMaioresGastos() {
    fetch('/api/analytics/maiores_gastos/')
        .then(res => res.json())
        .then(data => {
            const tbody = document.getElementById('tableMaioresGastos');
            tbody.innerHTML = '';
            
            if(data.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Sem gastos relevantes.</td></tr>';
                return;
            }

            data.forEach(item => {
                const row = `
                    <tr>
                        <td>${item.descricao}</td>
                        <td><span class="badge bg-secondary">${item.categoria}</span></td>
                        <td>${new Date(item.data).toLocaleDateString('pt-BR')}</td>
                        <td class="fw-bold text-danger">R$ ${parseFloat(item.valor).toLocaleString('pt-BR', {minimumFractionDigits: 2})}</td>
                    </tr>
                `;
                tbody.innerHTML += row;
            });
        });
}
