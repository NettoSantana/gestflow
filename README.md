# GESTFLOW

## VISÃO GERAL

O GESTFLOW é um ERP modular desenvolvido para atender diferentes segmentos de mercado utilizando uma única base de código.

O objetivo é permitir que novos segmentos sejam adicionados através de módulos específicos, sem necessidade de recriar todo o sistema.

Segmentos previstos:

* Oficina Automotiva
* Loja de Roupas
* Engenharia
* Manutenção Industrial
* Distribuidora
* Autopeças
* Prestadores de Serviço

---

# FILOSOFIA DO PROJETO

O GESTFLOW será composto por:

1. CORE (Base Principal)
2. Módulos Específicos

Toda empresa utilizará o CORE.

Cada segmento poderá habilitar módulos adicionais conforme necessidade.

---

# CORE GESTFLOW

## Dashboard

Responsável por apresentar os principais indicadores da empresa.

Funcionalidades previstas:

* Contas a receber
* Contas a pagar
* Fluxo de caixa
* Vendas do período
* Gráficos
* Calendário
* Indicadores operacionais

---

## Cadastros

Cadastro das informações básicas do sistema.

Entidades previstas:

* Clientes
* Fornecedores
* Funcionários
* Transportadoras
* Categorias

---

## Produtos

Gestão de produtos comercializados.

Funcionalidades previstas:

* Cadastro
* Preço de venda
* Controle de estoque
* Código interno
* Categorias
* Etiquetas

---

## Serviços

Gestão dos serviços prestados.

Funcionalidades previstas:

* Cadastro
* Categorias
* Valor padrão
* Tempo estimado

---

## Orçamentos

Controle comercial.

Funcionalidades previstas:

* Criação
* Edição
* Aprovação
* Conversão para venda
* Geração de PDF

---

## Vendas

Controle das vendas realizadas.

Funcionalidades previstas:

* Venda de produtos
* Venda de serviços
* Histórico
* Cancelamentos
* Devoluções

---

## Ordens de Serviço

Controle operacional.

Funcionalidades previstas:

* Abertura
* Execução
* Finalização
* Histórico
* Anexos

---

## Estoque

Controle de movimentações.

Funcionalidades previstas:

* Entrada
* Saída
* Ajustes
* Transferências
* Inventário

---

## Financeiro

Controle financeiro da empresa.

Funcionalidades previstas:

* Contas a pagar
* Contas a receber
* Fluxo de caixa
* Bancos
* Pagamentos

---

# FLUXO PRINCIPAL

Cliente

↓

Orçamento

↓

Venda

↓

Ordem de Serviço

↓

Estoque

↓

Financeiro

---

# MÓDULOS FUTUROS

## Oficina

* Veículos
* Placas
* Quilometragem
* Diagnóstico
* Histórico do veículo

## Engenharia

* Obras
* Projetos
* Medições
* Contratos
* ART

## Loja de Roupas

* Grade
* Cor
* Tamanho
* Coleções

---

# TECNOLOGIA

Backend:

* Python
* Flask

Banco:

* SQLite (MVP)
* PostgreSQL (Futuro)

Frontend:

* HTML
* CSS
* JavaScript

Hospedagem:

* Railway

---

# OBJETIVO V1

Disponibilizar um ERP funcional contendo:

* Dashboard
* Cadastros
* Produtos
* Serviços
* Orçamentos
* Vendas
* Ordens de Serviço
* Estoque
* Financeiro

Sem módulos específicos.

---

# OBJETIVO V2

Adicionar módulos específicos para segmentos.

---

# OBJETIVO V3

Transformar o GESTFLOW em uma plataforma SaaS multiempresa.
