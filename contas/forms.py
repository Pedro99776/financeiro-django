from django import forms
from .models import Transacao, Conta, Categoria


class TransacaoForm(forms.ModelForm):
    class Meta:
        model = Transacao
        fields = ['data', 'descricao', 'valor', 'conta', 'categoria', 'tipo']
        widgets = {
            'data': forms.DateInput(attrs={'type': 'date'}),
            'descricao': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        # ✅ CORREÇÃO: Recebe o usuário para filtrar
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # ✅ SEGURANÇA: Filtra apenas contas e categorias do usuário logado
        if user:
            self.fields['conta'].queryset = Conta.objects.filter(usuario=user)
            self.fields['categoria'].queryset = Categoria.objects.filter(usuario=user)

        # Aplica classe CSS
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nome']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'})
        }


class ContaForm(forms.ModelForm):
    class Meta:
        model = Conta
        fields = ['nome', 'saldo_inicial', 'instituicao']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'saldo_inicial': forms.NumberInput(attrs={'class': 'form-control'}),
            'instituicao': forms.TextInput(attrs={'class': 'form-control'}),
        }


class UploadFileForm(forms.Form):
    arquivo = forms.FileField(label="Selecione o Extrato (PDF)")
    conta = forms.ModelChoiceField(
        queryset=Conta.objects.none(),  # ✅ IMPORTANTE: Começa vazio
        label="Para qual conta?"
    )

    def __init__(self, *args, **kwargs):
        # ✅ CORREÇÃO: Recebe o usuário para filtrar
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # ✅ SEGURANÇA: Filtra apenas contas do usuário logado
        if user:
            self.fields['conta'].queryset = Conta.objects.filter(usuario=user)

        # Aplica classe CSS
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'