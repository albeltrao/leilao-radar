"""Conteudo educativo do onboarding (secao 10).

Escrito para quem nunca participou de leilao. Cada passo cita o dispositivo
legal de referencia para que o leitor possa conferir -- informar o que a norma
diz e diferente de dizer o que vai acontecer no caso dele, e so a primeira coisa
cabe a este produto (secao 11).
"""

from __future__ import annotations

PASSOS = [
    {
        "chave": "o-que-e",
        "titulo": "O que é um leilão judicial",
        "resumo": "É a venda de um bem determinada por um juiz dentro de um processo.",
        "detalhe": (
            "Quando alguém é condenado a pagar uma dívida e não paga, o juiz pode "
            "determinar a penhora e a venda de um bem para quitar o débito. Essa "
            "venda é o leilão judicial. Quem conduz é um leiloeiro credenciado, e "
            "as regras de cada leilão estão no edital — que é o documento que vale."
        ),
        "atencao": (
            "Leilão judicial é diferente de leilão de banco ou de financeira. "
            "Aqui existe um processo, um juiz e um edital público por trás."
        ),
    },
    {
        "chave": "pracas",
        "titulo": "1ª e 2ª praça",
        "resumo": "Duas oportunidades de venda, com valores mínimos diferentes.",
        "detalhe": (
            "Na 1ª praça o bem costuma sair pelo valor da avaliação judicial. Se "
            "ninguém der lance, abre-se a 2ª praça, com um valor mínimo menor, que "
            "o próprio edital fixa. É na 2ª praça que costuma aparecer o desconto — "
            "e também onde a concorrência aumenta."
        ),
        "atencao": (
            "O percentual da 2ª praça NÃO é sempre 50%. Cada edital fixa o seu. "
            "O Radar lê esse percentual do edital em vez de presumir."
        ),
    },
    {
        "chave": "preco-vil",
        "titulo": "Preço vil",
        "resumo": "Existe um piso: lance baixo demais não é aceito.",
        "detalhe": (
            "O art. 891 do Código de Processo Civil proíbe lance por preço vil. O "
            "edital deve indicar o valor mínimo; quando não indica, a lei considera "
            "vil o preço inferior a 50% do valor da avaliação."
        ),
        "atencao": "Arrematação por preço vil pode ser anulada depois. Confira o mínimo no edital.",
    },
    {
        "chave": "habilitacao",
        "titulo": "Habilitação",
        "resumo": "Você precisa se cadastrar antes, e isso tem prazo.",
        "detalhe": (
            "Para dar lance é preciso se habilitar no portal do leiloeiro, com "
            "documentos e aceite das condições. O prazo costuma encerrar horas ou "
            "dias antes da praça. Quem deixa para o dia perde o leilão por burocracia."
        ),
        "atencao": (
            "Quando o edital não declara o prazo, o Radar estima e marca o evento "
            "como “estimado”. Confirme sempre com o leiloeiro."
        ),
    },
    {
        "chave": "caucao",
        "titulo": "Caução e garantia",
        "resumo": "Alguns leilões exigem depósito prévio para você poder dar lance.",
        "detalhe": (
            "Parte dos editais exige caução — um depósito que garante que o "
            "interessado é sério. Quem não arremata recebe de volta; quem arremata "
            "e desiste pode perder o valor e ainda responder por perdas e danos."
        ),
        "atencao": "Desistir depois de arrematar tem custo. Só dê lance no que pretende pagar.",
    },
    {
        "chave": "pagamento",
        "titulo": "Como se paga",
        "resumo": "À vista é a regra; parcelamento depende do edital e da lei.",
        "detalhe": (
            "O pagamento costuma ser à vista, em prazo curto. O art. 895 do CPC "
            "permite proposta de parcelamento com entrada de pelo menos 25% e o "
            "restante em até 30 meses, se o edital admitir. Alguns editais aceitam "
            "FGTS e financiamento para imóvel — mas isso precisa estar escrito."
        ),
        "atencao": "Financiamento leva tempo. Confirme se o prazo do edital comporta.",
    },
    {
        "chave": "comissao",
        "titulo": "Comissão do leiloeiro",
        "resumo": "Some ao lance: normalmente 5%, por conta do arrematante.",
        "detalhe": (
            "A comissão do leiloeiro é paga por quem arremata e normalmente NÃO "
            "está incluída no valor do lance. Um lance de R$ 160.000 com 5% de "
            "comissão custa R$ 168.000 antes de qualquer outra despesa."
        ),
        "atencao": "O simulador do Radar soma a comissão ao lance para você ver o caixa real.",
    },
    {
        "chave": "onus",
        "titulo": "Ônus, dívidas e quem paga",
        "resumo": "O ponto que mais gera surpresa — e o que mais exige advogado.",
        "detalhe": (
            "Um imóvel pode ter hipoteca, penhora, IPTU e condomínio atrasados. O "
            "art. 130, parágrafo único, do Código Tributário Nacional prevê que os "
            "débitos tributários se sub-roguem no preço da arrematação, e o art. 908 "
            "do CPC trata da ordem de pagamento com o produto da venda. Débito de "
            "condomínio segue lógica própria e muitos editais o atribuem a quem "
            "arremata."
        ),
        "atencao": (
            "O Radar mostra o que o edital DIZ sobre isso, com o trecho citado. "
            "Ele não diz o que você vai pagar — essa leitura é do seu advogado."
        ),
    },
    {
        "chave": "ocupacao",
        "titulo": "Imóvel ocupado",
        "resumo": "Arrematar não é o mesmo que receber a chave.",
        "detalhe": (
            "Se o imóvel está ocupado — pelo executado, por inquilino ou por "
            "terceiro — a desocupação pode exigir um pedido de imissão na posse e "
            "levar meses. Isso é custo e é tempo, e precisa entrar na conta."
        ),
        "atencao": "Imóvel ocupado é o principal fator de risco no score do Radar.",
    },
    {
        "chave": "custos",
        "titulo": "O custo que não está no lance",
        "resumo": "ITBI, registro, dívidas assumidas, desocupação e reforma.",
        "detalhe": (
            "Além do lance e da comissão, entram ITBI, custas de registro da carta "
            "de arrematação, eventuais débitos que o edital atribua ao arrematante, "
            "despesas de desocupação e reforma. O desconto só é real depois disso."
        ),
        "atencao": "O simulador cobre lance, comissão e débitos citados. O resto é com você.",
    },
    {
        "chave": "diario",
        "titulo": "Onde o Radar descobre o leilão",
        "resumo": "No Diário da Justiça, antes de o leilão aparecer em qualquer site.",
        "detalhe": (
            "Todo leilão judicial é anunciado por edital publicado no Diário da "
            "Justiça. Desde a Resolução CNJ nº 455/2022 os tribunais publicam no "
            "Diário de Justiça Eletrônico Nacional, que reúne a Justiça Estadual e "
            "a Justiça Federal. O Radar lê esse diário todos os dias, identifica "
            "quais publicações anunciam leilão e separa os bens em móveis e "
            "imóveis, e os imóveis em rurais e urbanos."
        ),
        "atencao": (
            "A identificação é automática e vem sempre com o trecho da publicação "
            "que a motivou. Se o trecho não convencer você, ele é justamente o que "
            "há para conferir: clique em \"por que está nesta categoria?\" e leia. "
            "O documento que vale continua sendo o edital completo."
        ),
    },
]

REFERENCIAS = [
    {
        "titulo": "Resolução CNJ nº 236/2016",
        "descricao": "Disciplina a alienação judicial por meio eletrônico.",
        "url": "https://atos.cnj.jus.br/atos/detalhar/2333",
    },
    {
        "titulo": "CPC, arts. 879 a 903",
        "descricao": "Regras da alienação em leilão judicial, preço vil e parcelamento.",
        "url": "https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2015/lei/l13105.htm",
    },
    {
        "titulo": "Resolução CNJ nº 455/2022",
        "descricao": (
            "Institui o Diário de Justiça Eletrônico Nacional, onde os tribunais "
            "estaduais e federais publicam os editais de leilão."
        ),
        "url": "https://atos.cnj.jus.br/atos/detalhar/4563",
    },
    {
        "titulo": "CTN, art. 130",
        "descricao": "Sub-rogação de tributos sobre o imóvel no preço da arrematação.",
        "url": "https://www.planalto.gov.br/ccivil_03/leis/l5172compilado.htm",
    },
]
