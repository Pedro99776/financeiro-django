from django import forms
from .models import Transacao, Conta, Categoria, CartaoCredito


class TransacaoForm(forms.ModelForm):
    class Meta:
        model = Transacao
        fields = ['data', 'descricao', 'valor', 'conta', 'cartao', 'categoria', 'tipo']
        widgets = {
            'data': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
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
            self.fields['cartao'].queryset = CartaoCredito.objects.filter(usuario=user)
        
        # Torna cartao e conta opcionais no form (validação será no clean)
        self.fields['conta'].required = False
        self.fields['cartao'].required = False

        # Aplica classe CSS
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

    def clean(self):
        cleaned_data = super().clean()
        conta = cleaned_data.get('conta')
        cartao = cleaned_data.get('cartao')

        if not conta and not cartao:
            raise forms.ValidationError("Você deve selecionar uma Conta ou um Cartão de Crédito.")
        
        if conta and cartao:
            raise forms.ValidationError("Selecione apenas uma opção: Conta ou Cartão, não ambos.")
            
        return cleaned_data


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


class CartaoCreditoForm(forms.ModelForm):
    class Meta:
        model = CartaoCredito
        fields = ['nome', 'limite', 'dia_fechamento', 'dia_vencimento', 'conta_pagamento', 'bandeira']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Nubank, XP'}),
            'limite': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'dia_fechamento': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 31}),
            'dia_vencimento': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 31}),
            'conta_pagamento': forms.Select(attrs={'class': 'form-control'}),
            'bandeira': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields['conta_pagamento'].queryset = Conta.objects.filter(usuario=user)


class UploadFileForm(forms.Form):
    arquivo = forms.FileField(
        label="Selecione o Extrato (PDF, Imagem ou CSV)",
        widget=forms.ClearableFileInput(attrs={'accept': 'application/pdf, image/*, .csv, text/csv'})
    )
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