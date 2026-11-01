"""Policy-retrieval evaluation set (offline, data only).

Each supported case: English question, PT-BR keyword query (what the LLM is asked
to send), acceptable gold section ids, and a verbatim snippet that must appear in
the retrieved gold evidence. `HELD_OUT` was written after `retrieval.GLOSSARY`
was frozen and must not be used to tune it.
"""

from __future__ import annotations

from typing import NamedTuple


class Case(NamedTuple):
    question_en: str
    query_pt: str
    gold: frozenset[str]
    snippet: str


class Unsupported(NamedTuple):
    question_en: str
    query_pt: str
    forbidden: tuple[str, ...]  # folded substrings that must not appear in any passage


class Trap(NamedTuple):
    question_en: str
    query_pt: str
    expected_section: str
    must_contain: str  # caveat the agent needs to see in that passage
    must_not_contain: str  # claim the policy never makes


def _c(en: str, pt: str, gold: str, snippet: str) -> Case:
    return Case(en, pt, frozenset(gold.split()), snippet)


DEV: tuple[Case, ...] = (
    _c("What time do you open on Saturday?", "horário sábado", "2", "Sábado 09:00 às 13:00"),
    _c("Are you open on Sundays?", "abre domingo", "2", "Domingo e Feriados Fechado"),
    _c("What is the store address?", "endereço da loja", "1.2", "Rua 14 de Maio, 3200"),
    _c("Which payment methods do you accept?", "formas de pagamento", "3", "Boleto Bancário"),
    _c("Do I get a discount paying with PIX?", "desconto PIX", "3 6.2", "5% de desconto"),
    _c(
        "What is the minimum installment for 6x on credit card?",
        "parcela mínima 6x cartão",
        "3.1",
        "4x a 6x: sem juros, parcela mínima de R$ 80,00",
    ),
    _c("Can I combine PIX and credit card?", "combinar PIX e cartão", "3.1",
       "acima de R$ 2.000,00"),
    _c("How long does a boleto take to clear?", "compensação boleto", "3", "até 3 dias úteis"),
    _c(
        "I changed my mind about an online purchase, can I return it?",
        "devolução arrependimento compra online",
        "4.1",
        "7 (sete) dias corridos após o recebimento",
    ),
    _c("Who pays the return shipping?", "frete de devolução", "4.1",
       "frete de devolução é por conta da loja"),
    _c("How long does the refund take?", "prazo reembolso", "4.1", "em até 10 dias úteis"),
    _c(
        "My guitar arrived defective, can I exchange it?",
        "troca produto com defeito",
        "4.2",
        "30 (trinta) dias corridos após a compra",
    ),
    _c("Can I exchange for a different color?", "troca por cor diferente", "4.3",
       "(cor, modelo, tamanho)"),
    _c("Can I return a saxophone mouthpiece?", "devolver boquilha", "4.4", "Boquilhas"),
    _c("Is shipping free in Campo Grande?", "frete grátis Campo Grande", "5.1",
       "acima de R$ 500,00"),
    _c("How long does SEDEX take?", "prazo SEDEX", "5.2", "2 a 5 dias úteis"),
    _c("The package arrived damaged, what should I do?", "pacote chegou com avaria", "5.2",
       "recusar o recebimento"),
    _c("What does the tracking code look like?", "formato código de rastreamento", "5.3",
       "BR4K7M2X9P1BR"),
    _c("Do promotions stack with the PIX discount?", "promoção cumulativa desconto PIX", "6.2",
       "não são cumulativas"),
    _c("How big are the Black Friday discounts?", "desconto Black Friday", "6.1", "15% a 30%"),
    _c("How long is the warranty?", "prazo de garantia", "8.1", "90 (noventa) dias"),
    _c("Does the warranty cover worn strings?", "garantia cobre desgaste cordas", "8.3",
       "Desgaste natural"),
    _c("Do you sell amplifiers or strings?", "vende amplificadores cordas acessórios", "1",
       "não comercializamos acessórios"),
    _c("How can I delete my personal data?", "excluir meus dados pessoais", "9",
       "exclusão de seus dados"),
    _c("How long until you answer my complaint?", "prazo retorno reclamação", "7.3",
       "24 horas úteis"),
)

HELD_OUT: tuple[Case, ...] = (
    _c("Can I pay in 10 instalments?", "parcelar em 10 vezes", "3 3.1", "12x"),
    _c("Is there a rain check if a promo item sells out?",
       "reserva de preço produto esgotado promoção", "6.2", "rain check"),
    _c("How long is the manufacturer warranty?", "garantia do fabricante prazo", "8.2",
       "6 meses a 2 anos"),
    _c("What time do you close on weekdays?", "horário de fechamento segunda a sexta", "2",
       "09:00 às 18:00"),
    _c("What is your WhatsApp number?", "número WhatsApp", "1.2 7", "(67)"),
    _c("Which carriers do you use for other states?", "transportadora envio outras cidades",
       "5.2", "Jadlog"),
    _c("Do I need the original box to return something?", "embalagem original devolução",
       "4.1 4.3", "embalagem original"),
    _c("Can I return an instrument that had a custom setup?",
       "devolver instrumento com setup personalizado", "4.4", "setup, regulagem especial"),
    _c("Does the warranty cover a guitar I dropped?", "garantia cobre queda", "8.3 4.2",
       "queda"),
    _c("What's the delivery fee for orders under R$500 in Campo Grande?",
       "taxa de entrega pedido abaixo de 500 Campo Grande", "5.1", "R$ 35,00"),
    _c("Do you share my data with other companies?", "compartilhar dados com terceiros", "9",
       "não são compartilhados com terceiros"),
    _c("When is the store anniversary sale?", "promoção aniversário da loja", "6.1",
       "Aniversário da Loja (Agosto)"),
)

UNSUPPORTED: tuple[Unsupported, ...] = (
    Unsupported("Do you rent instruments?", "aluguel de instrumentos", ("alug", "locacao")),
    Unsupported("Do you ship internationally?", "envio internacional exterior",
                ("internacional", "exterior")),
    Unsupported("Do you match competitor prices?", "cobrir preço concorrente",
                ("concorr", "cobrimos")),
    Unsupported("Do you offer music lessons?", "aulas de música",
                ("aula de", "aulas de", "curso")),
    Unsupported("Do you sell gift cards?", "vale-presente cartão presente",
                ("vale-presente", "vale presente", "cartao presente", "gift")),
)

TRAPS: tuple[Trap, ...] = (
    Trap("Do you accept PayPal?", "aceita PayPal forma de pagamento", "3",
         "Aceitamos as seguintes formas de pagamento", "paypal"),
    Trap("What is the return window for an in-store purchase?",
         "prazo devolução compra na loja física", "4.1", "(Compras Online)", "loja fisica"),
)
