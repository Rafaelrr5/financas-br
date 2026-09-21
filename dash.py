"""Dashboard local: importar, sincronizar, categorizar e ver. python dash.py -> :8000"""
import datetime
import email.parser
import html
import io
import itertools
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import b3_pdf
import inter_pdf
import mp_sync
import store
from fmt import brl, mil, dia_br, mes_br, MES

# Identidade: papel pautado de contabilidade, impresso em duas tintas.
#   preto     = dado impresso pela máquina (inclusive entrada)
#   vermelho  = saída de dinheiro, e nada mais
#   azul      = tudo que humano escreveu (regras, filtro ativo, links, carimbo)
# Entrada não é verde: é barra vazada. A distinção é de forma, não de cor — sobrevive a
# daltonismo e libera o vermelho pra ter um sentido só.
ICONE = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>"
         "<rect width='16' height='16' fill='%23FBFBF7'/>"
         "<rect y='3' width='16' height='3' fill='%231C1F1B'/>"
         "<rect y='7' width='16' height='3' fill='%23E8EFE6'/>"
         "<rect y='11' width='16' height='3' fill='%231C1F1B'/></svg>")

PAGE = """<!doctype html><meta charset=utf-8><title>Finanças</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<link rel=icon href="{icone}">
<style>
:root{{color-scheme:light dark;
--papel:#FBFBF7;--barra:#E8EFE6;--tinta:#1C1F1B;--tinta2:#6B7268;
--vermelho:#B4231C;--esfero:#1F4E8C;--linha:#C9CCC4}}
/* o negativo do razão */
@media (prefers-color-scheme:dark){{:root{{
--papel:#12140F;--barra:#1A1F18;--tinta:#E4E7DE;--tinta2:#8D948A;
--vermelho:#F0574C;--esfero:#7FA8E8;--linha:#333831}}}}
*{{box-sizing:border-box}}
body{{margin:0;padding:1.5rem 1.75rem 4rem;background:var(--papel);color:var(--tinta);
font:13.5px/1.5 ui-monospace,"Cascadia Mono","SF Mono","Segoe UI Mono","Roboto Mono",Menlo,monospace;
font-variant-numeric:tabular-nums}}
.folha{{max-width:1180px;margin:0 auto}}
/* registro rótulo: nome de campo impresso em formulário */
h1,h2,h3,.rot,th,summary,legend{{font-size:11px;font-weight:600;letter-spacing:.18em;
text-transform:uppercase;margin:0;color:var(--tinta2)}}
/* .rot (0,1,0) vence h1,h2,h3 (0,0,1): rótulo da calha fica na tinta apagada */
h1,h2,h3{{color:var(--tinta)}}
.cab{{display:flex;justify-content:space-between;align-items:baseline;
gap:1rem;flex-wrap:wrap;padding-bottom:1.2rem}}
.cab time{{font-size:11px;letter-spacing:.1em;color:var(--tinta2)}}
/* a dobra do formulário contínuo separa as seções — sem caixa, sem sombra */
.folha>section{{display:grid;grid-template-columns:7.5rem 1fr;gap:1.5rem;
border-top:1px dashed var(--linha);padding:1.2rem 0}}
.folha>section>.rot{{padding-top:.2rem}}
@media (max-width:720px){{.folha>section{{grid-template-columns:1fr;gap:.6rem}}}}
a{{color:var(--esfero)}}
td a{{text-decoration:none}}td a:hover{{text-decoration:underline}}
:focus-visible{{outline:2px solid var(--esfero);outline-offset:2px}}
.sr{{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}}
/* carimbo: registro de uma ação sua, então tinta de caneta. Erro é vermelho. */
.msg{{display:inline-block;margin:0 0 1.1rem;padding:.35rem .7rem;border:2px solid var(--esfero);
color:var(--esfero);font-size:11px;font-weight:600;letter-spacing:.14em;
text-transform:uppercase;transform:rotate(-1.2deg)}}
.msg.erro{{border-color:var(--vermelho);color:var(--vermelho)}}
table{{border-collapse:collapse;width:100%}}
th,td{{padding:.32rem .55rem;text-align:left}}
thead th{{border-bottom:1.5px solid var(--tinta);white-space:nowrap}}
td.v,th.v{{text-align:right}}
.neg{{color:var(--vermelho)}}
.pautada tbody tr:nth-child(even){{background:var(--barra)}}
.bar{{display:block;height:6px;background:var(--vermelho)}}
input,select,button{{font:inherit;background:var(--papel);border:1px solid var(--linha);
padding:.25rem .4rem}}
input,select{{color:var(--esfero)}}
button{{cursor:pointer;font-size:11px;letter-spacing:.14em;text-transform:uppercase;
border-color:var(--esfero);color:var(--esfero)}}
button:hover{{background:var(--barra)}}
label{{display:flex;flex-direction:column;gap:.15rem;font-size:10px;letter-spacing:.14em;
text-transform:uppercase;color:var(--tinta2)}}
.filtros{{display:flex;gap:.7rem;flex-wrap:wrap;align-items:end}}
.rapido{{display:flex;gap:.35rem;flex-wrap:wrap;margin-bottom:.8rem}}
.rapido a{{padding:.2rem .65rem;border:1px solid var(--linha);text-decoration:none;
color:var(--tinta2);font-size:11px;letter-spacing:.08em}}
.rapido a.on{{color:var(--esfero);border-color:var(--esfero);box-shadow:inset 0 0 0 1px var(--esfero)}}
/* somatório de fechamento: rótulo à esquerda, cifra alinhada na vírgula, régua no total */
.soma{{max-width:36rem}}
.soma th{{padding-left:0;white-space:nowrap}}
.soma .cifra{{text-align:right;font-size:1.75rem;line-height:1.15;letter-spacing:-.01em;
white-space:nowrap}}
.soma .medida{{width:38%;padding-right:0}}
.soma .medida i{{display:block;height:9px;background:var(--vermelho)}}
.soma .medida i.vazada{{background:none;box-shadow:inset 0 0 0 1.5px var(--tinta)}}
.soma .medida i.apl{{background:var(--esfero)}}
.soma tr.total th,.soma tr.total td{{border-top:1.5px solid var(--tinta);padding-top:.45rem}}
.meses-wrap{{display:flex;align-items:stretch;margin-top:1.3rem}}
.meses-esc{{display:flex;flex-direction:column;justify-content:space-between;
align-items:flex-end;padding:0 .5rem 0 0;font-size:9.5px;letter-spacing:.04em;
color:var(--tinta2);height:96px;min-width:3.2rem}}
.meses-esc span{{line-height:1}}
.meses{{display:flex;gap:.3rem;align-items:flex-end;height:96px;flex:1;
border-bottom:1px solid var(--linha);border-left:1px solid var(--linha)}}
.meses>a{{flex:1;min-width:0;height:100%;display:flex;flex-direction:column;
justify-content:flex-end;align-items:center;text-decoration:none;border:0}}
.meses>a:hover i{{background:var(--tinta)}}
.meses span{{flex:1;display:flex;gap:2px;align-items:flex-end}}
.meses i,.meses b,.meses u{{width:9px;background:var(--vermelho)}}
.meses b{{background:none;box-shadow:inset 0 0 0 1.5px var(--tinta)}}
.meses u{{background:var(--esfero)}}
.meses em{{font-style:normal;font-size:9.5px;letter-spacing:.05em;color:var(--tinta2);
margin-top:.35rem;white-space:nowrap}}
.meta{{margin:.9rem 0 0;font-size:11px;letter-spacing:.06em;color:var(--tinta2)}}
.hint{{font-size:11px;line-height:1.45;color:var(--tinta2);margin:.55rem 0 0;max-width:62ch}}
.duas{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));
gap:1.5rem;align-items:start}}
.duas>section{{min-width:0}}
.duas h3{{margin-bottom:.5rem}}
/* triagem: uma categoria por linha, um form por linha, zero JS */
#triar td form{{display:flex;gap:.25rem;margin:0}}
#triar td input{{width:9rem}}
#triar td button{{padding:.2rem .45rem}}
.rolagem{{overflow-x:auto}}
.razao{{min-width:680px}}
.razao tbody.par{{background:var(--barra)}}
.razao tbody .dia th{{padding-top:.6rem;color:var(--tinta);letter-spacing:.14em}}
.razao td{{white-space:nowrap}}
.razao td.desc{{white-space:normal}}
.nota-ed{{display:flex;gap:.25rem;margin:0}}
.nota-ed input{{width:11rem}}
.nota-ed button{{padding:.2rem .45rem}}
.cod{{color:var(--tinta2);font-size:10.5px;letter-spacing:.1em}}
/* o fio: removido — coluna mostra valor numérico do acumulado */
.fontes{{display:flex;gap:1.2rem;flex-wrap:wrap;margin-top:.7rem}}
.fontes fieldset{{flex:1;min-width:270px;border:1px solid var(--linha);padding:.5rem .8rem .7rem;
margin:0}}
.fontes form{{display:flex;gap:.5rem;align-items:end;flex-wrap:wrap;margin:.4rem 0 0}}
summary{{cursor:pointer;color:var(--esfero)}}
.cobertura{{display:flex;gap:.3rem;flex-wrap:wrap}}
.cob-mes{{display:flex;flex-direction:column;align-items:center;gap:.15rem;
padding:.3rem .5rem;border:1px solid var(--linha);min-width:56px;text-decoration:none;color:inherit}}
.cob-mes:hover{{border-color:var(--esfero)}}
.cob-mes em{{font-style:normal;font-size:9.5px;letter-spacing:.05em;color:var(--tinta2)}}
.cob-tag{{font-size:9px;letter-spacing:.08em;font-weight:600;padding:.1rem .25rem;
border-radius:2px}}
.cob-tag.inter{{background:#C8E6C9;color:#2E7D32}}
.cob-tag.mp{{background:#BBDEFB;color:#1565C0}}
@media(prefers-color-scheme:dark){{
.cob-tag.inter{{background:#1B5E20;color:#A5D6A7}}
.cob-tag.mp{{background:#0D47A1;color:#90CAF9}}
}}
.cob-miss{{color:var(--vermelho);font-size:9px;letter-spacing:.08em;font-weight:600}}
/* dropdown pesquisável: caixa fina com seta, painel de opções flutuante */
.dd{{position:relative;display:inline-block;min-width:9rem}}
.dd input.dd-in{{width:100%;padding-right:1.4rem;color:var(--esfero);cursor:text}}
.dd .dd-arrow{{position:absolute;right:.4rem;top:50%;transform:translateY(-50%);
pointer-events:none;font-size:9px;color:var(--tinta2);line-height:1}}
.dd-list{{display:none;position:absolute;top:100%;left:0;right:0;z-index:90;
background:var(--papel);border:1px solid var(--esfero);
border-top:none;margin:0;padding:0;list-style:none}}
.dd.open .dd-list{{display:block}}
.dd-list li{{padding:.25rem .5rem;cursor:pointer;font-size:12px;color:var(--tinta)}}
.dd-list li:hover,.dd-list li.act{{background:var(--barra);color:var(--esfero)}}
.dd-list li.dd-novo{{font-style:italic;color:var(--esfero)}}
.dd-list li.dd-hide{{display:none}}
/* parcelado: cartões de resumo iguais aos de investimentos + barra de progresso da compra */
.parc-prog{{display:block;height:6px;background:var(--linha)}}
.parc-prog i{{display:block;height:100%;background:var(--vermelho)}}
.parc-quit{{color:var(--tinta2)}}
.parc-mes{{display:flex;justify-content:space-between;gap:.8rem;max-width:26rem;
padding:.2rem 0;border-bottom:1px dotted var(--linha)}}
.parc-mes b{{font-weight:400}}
/* investimentos: seção dedicada com resumo e extrato */
.regras-toggle{{margin-top:1rem}}
.regras-tbl td:last-child{{width:2.5rem;text-align:center;padding:0}}
.regra-rm{{margin:0;display:inline}}
.regra-ed{{margin:0;display:flex;gap:.3rem;align-items:center}}
.regra-ed button{{padding:.2rem .5rem}}
.regra-rm button{{border:none;background:none;color:var(--vermelho);font-size:14px;
cursor:pointer;padding:.2rem .4rem;line-height:1}}
.regra-rm button:hover{{background:var(--barra)}}
.inv-resumo{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
gap:1rem;margin-bottom:1.2rem}}
.inv-card{{padding:.6rem .8rem;border:1px solid var(--linha)}}
.inv-card .rot{{margin-bottom:.15rem}}
.inv-card .cifra{{font-size:1.25rem;letter-spacing:-.01em}}
.inv-card .cifra.pos{{color:var(--tinta)}}
.inv-verde{{color:#2E7D32}}
@media(prefers-color-scheme:dark){{.inv-verde{{color:#81C784}}}}
/* aplicação sai da conta, mas não é gasto: azul da caneta, não o vermelho do consumo */
.inv-apl{{color:var(--esfero)}}
</style>
<div class=folha>
<div class=cab><h1>Extrato unificado</h1><time>{janela}</time></div>
{msg}
<section><h2 class=rot>Fontes</h2><div>
<details><summary>Importar PDF / sincronizar Mercado Pago</summary>
<div class=fontes>
<fieldset><legend>PDF do Inter (extrato ou fatura)</legend>
<form method=post action=/import enctype=multipart/form-data>
<label for=pdf>Arquivos<input type=file id=pdf name=pdf accept=.pdf multiple required></label>
<button>Importar</button></form></fieldset>
<fieldset><legend>Extrato de movimentação B3 (relatórios)</legend>
<form method=post action=/import_b3 enctype=multipart/form-data>
<label for=b3>Arquivos<input type=file id=b3 name=pdf accept=.pdf multiple required></label>
<button>Importar</button></form>
<p class=hint>Só complementa Investimentos com o detalhe por ativo — não entra no razão nem
no gasto (o caixa já vem do extrato do Inter).</p></fieldset>
<fieldset><legend>Mercado Pago</legend>
<form method=post action=/sync>
<label for=dias>Últimos dias<input type=number id=dias name=dias value=30 min=1 max=365></label>
<button>Sincronizar</button></form></fieldset>
</div></details></div></section>

<section><h2 class=rot>Cobertura</h2><div>
<details><summary>Meses com extrato importado</summary>
<div class=cobertura>{cobertura}</div>
</details></div></section>

<section><h2 class=rot>Período</h2><div>
<div class=rapido>{rapido}</div>
<form class=filtros>
<label for=de>De<input type=date id=de name=de value="{de}"></label>
<label for=ate>Até<input type=date id=ate name=ate value="{ate}"></label>
<label for=origem>Origem<select id=origem name=origem>{origens}</select></label>
<label for=tipo>Tipo<input id=tipo name=tipo value="{tipo}" placeholder="pix, debito..."></label>
<label for=desc>Descrição<input id=desc name=desc value="{desc}" placeholder="nome, recebedor..."></label>
<label>Categoria{filtro_cat_dd}<small class=hint>{nao_fluxo}: só entram no total se filtradas aqui</small></label>
<button>Filtrar</button>
</form></div></section>

<section><h2 class=rot>Resumo</h2><div>
<details open><summary>Totais e meses do período</summary>
<table class=soma><caption class=sr>Totais do período</caption>
<tr><th scope=row>Gasto<td class=cifra><span class=neg>R$ {v_gasto}</span>
<td class=medida><i style=width:{w_gasto}%></i>
<tr><th scope=row>Aplicações<td class=cifra><span class=inv-apl>R$ {v_inv_liquido2}</span>
<td class=medida><i class=apl style=width:{w_apl}%></i>
<tr><th scope=row>Entrada<td class=cifra>R$ {v_entrada}
<td class=medida><i class=vazada style=width:{w_entrada}%></i>
<tr class=total><th scope=row>Líquido em caixa<td class=cifra>{v_caixa}<td class=medida>
</table>
<p class=hint>Aplicação sai da conta mesmo sem ser gasto. Aplicações = aplicado − resgatado.
Líquido em caixa = entrada − gasto − aplicações.</p>
<div class=meses-wrap><div class=meses-esc>{escala}</div><div class=meses>{meses}</div></div>
<p class=meta>{meta}</p>
</details></div></section>

<section><h2 class=rot>Conferência</h2><div>
<details><summary>Registrar e conferir saldo</summary>
<form class=filtros method=post action=/saldo>
<label for=sd>Data<input type=date id=sd name=data value="{hoje}" required></label>
<label for=st>Saldo total<input type=number step=0.01 id=st name=total required></label>
<label for=sc>Caixinhas<input type=number step=0.01 id=sc name=caixinhas value=0></label>
<label for=si>Saldo Inter<input type=number step=0.01 id=si name=inter value=0></label>
<label for=sf>Fatura cartão<input type=number step=0.01 id=sf name=fatura value=0></label>
<button>Registrar</button></form>
<p class=hint>Fatura em aberto pelo que já foi importado: <b>R$ {v_fatura_aberta}</b> — compras
no cartão desde o último pagamento de fatura no extrato. Diferença contra a fatura informada =
fatura do ciclo ainda não importada (fecha dia 15).</p>
<table class=pautada><caption class=sr>Conferência de saldo informado</caption>
<thead><tr><th scope=col>Data<th scope=col class=v>Total<th scope=col class=v>Caixinhas
<th scope=col class=v>Inter<th scope=col class=v>Fatura<th scope=col class=v>Δ informado
<th scope=col class=v>Σ lançado<th scope=col class=v>Não rastreado</thead>
<tbody>{conferencia}</tbody></table>
<p class=hint>Δ informado = quanto o saldo total mudou entre duas fotos. Σ lançado = soma das
movimentações que tocam a conta no mesmo intervalo (cartão fora: a compra não muda saldo, o
pagamento da fatura sim). "Não rastreado" ≠ 0 é dinheiro que se moveu sem lançamento
importado.</p>
</details></div></section>

<section><h2 class=rot>Parcelado</h2><div>
<div class=inv-resumo>
<div class=inv-card><p class=rot>Em aberto</p>
<p class="cifra neg">R$ {v_parc_aberto}</p></div>
<div class=inv-card><p class=rot>Compras ativas</p>
<p class=cifra>{n_parc_ativos}</p></div>
<div class=inv-card><p class=rot>Próxima fatura</p>
<p class="cifra neg">R$ {v_parc_proxima}</p></div>
<div class=inv-card><p class=rot>Termina em</p>
<p class=cifra>{parc_fim}</p></div>
</div>
<p class=hint>Compras parceladas no cartão, independentes do período filtrado — compromisso é
para frente, não histórico. "Em aberto" = parcelas que ainda não foram cobradas.</p>
<table class=pautada><caption class=sr>Parcelamentos em aberto</caption>
<thead><tr><th scope=col>Compra<th scope=col>Categoria<th scope=col>Cartão
<th scope=col class=v>Parcela<th scope=col class=v>Valor<th scope=col class=v>Em aberto
<th scope=col>Última<th scope=col><span class=sr>Progresso</span></thead>
<tbody>{parc_linhas}</tbody></table>
<details><summary>Parcelas por mês daqui pra frente</summary>
<div style=margin-top:.6rem>{parc_meses}</div>
<p class=hint>Quanto de fatura já está comprometido em cada mês só pelas parcelas.</p>
</details>
<details><summary>{n_parc_quitados} já quitado{pl_parc}</summary>
<table class=pautada><caption class=sr>Parcelamentos quitados</caption>
<thead><tr><th scope=col>Compra<th scope=col>Categoria<th scope=col class=v>Parcelas
<th scope=col class=v>Valor<th scope=col class=v>Total<th scope=col>Última</thead>
<tbody>{parc_quitados}</tbody></table>
</details>
<p class=hint>O extrato do Inter lança todas as parcelas com a data da compra, sem dizer em
qual fatura cada uma cai. O calendário aqui é deduzido: uma parcela por mês a partir da
primeira fatura depois da compra (fecha dia {fechamento}). Compra com carência ou antecipada
sai fora do lugar. Valor com <b>*</b> é estimado — nem toda parcela da compra foi importada,
então o total é parcelas × valor da parcela.</p>
</div></section>

<section><h2 class=rot>Investimentos</h2><div>
<div class=inv-resumo>
<div class=inv-card><p class=rot>Aplicações</p>
<p class="cifra inv-apl">R$ {v_aplicacao}</p></div>
<div class=inv-card><p class=rot>Resgates</p>
<p class="cifra pos">R$ {v_resgate}</p></div>
<div class=inv-card><p class=rot>Rendimentos</p>
<p class="cifra inv-verde">R$ {v_rendimento}</p></div>
<div class=inv-card><p class=rot>Saldo aplicado</p>
<p class=cifra>{v_inv_liquido}</p></div>
</div>
<details><summary>{n_inv} movimentações de investimento</summary>
<p class=hint>Aplicações, resgates e rendimentos no período. Inter: Tesouro, CDB, B3,
renda fixa. Mercado Pago: rendimientos da conta remunerada.</p>
<table class=pautada><caption class=sr>Movimentações de investimento</caption>
<thead><tr><th scope=col>Data<th scope=col>Org<th scope=col>Tipo
<th scope=col>Descrição<th scope=col>Categoria<th scope=col class=v>Valor</thead>
<tbody>{inv_linhas}</tbody></table>
</details>
<details><summary>{n_b3} eventos da B3 por ativo</summary>
<p class=hint>Do extrato de movimentação da B3 (investidor.b3.com.br → Relatórios). Proventos =
rendimento, dividendo, JCP, amortização e juros; o resto (liquidação, empréstimo, subscrição) é
posição, não renda. Nada disso entra em gasto/entrada: o caixa já vem do extrato do Inter.</p>
<table class=pautada><caption class=sr>Eventos da B3 por ativo</caption>
<thead><tr><th scope=col>Ativo<th scope=col class=v>Eventos<th scope=col class=v>Proventos
<th scope=col>Último evento</thead>
<tbody>{b3_ativos}</tbody></table>
</details>
</div></section>

<section id=triar><h2 class=rot>Triar</h2><div>
<details><summary>{n_outros} em "outros"</summary>
<p class=hint>Top 20 por valor absoluto. A categoria vira regra: vale retroativo para tudo que
casa com o trecho e para as próximas importações. Categoria nova = nome novo.
Sem descrição (comum no Mercado Pago) o trecho é o tipo — então a regra pinta todos os
lançamentos daquele tipo de uma vez.</p>
<table class=pautada><caption class=sr>Lançamentos sem categoria</caption>
<thead><tr><th scope=col>Descrição<th scope=col class=v>Qtd<th scope=col class=v>Total
<th scope=col>Categoria</thead><tbody>{triagem}</tbody></table>
<h3 style=margin-top:1.2rem>Regra livre</h3>
<form class=filtros method=post action=/regra>
<label for=p>Trechos da descrição<input id=p name=padrao required
 placeholder="uber, 99app, taxi"></label>
<label>Categoria{regra_dd}</label>
<button>Aplicar a tudo</button>
</form>
<p class=hint>Para o que não está na lista acima: clique numa descrição do razão para preencher
o trecho. Vários trechos separados por vírgula viram uma regra cada, todas na mesma
categoria.</p>
<details class=regras-toggle><summary>{n_regras} regra{pl_regras}</summary>
<table class="pautada regras-tbl"><caption class=sr>Regras de categorização</caption>
<thead><tr><th scope=col>Padrão<th scope=col>Categoria<th scope=col></thead>
<tbody>{regras_linhas}</tbody></table>
</details>
</details></div></section>

<section><h2 class=rot>Onde</h2><div class=duas>
<section><h3>Por categoria</h3>
<table class=pautada><caption class=sr>Gasto por categoria</caption>
<thead><tr><th scope=col>Categoria<th scope=col class=v>Gasto<th scope=col class=v>Qtd
<th scope=col class=v>%<th scope=col><span class=sr>Proporção</span></thead>
<tbody>{cats}</tbody></table>
{drilldown}</section>
<section><h3>Onde mais gastei</h3>
<table class=pautada><caption class=sr>Maiores gastos por estabelecimento</caption>
<thead><tr><th scope=col>Descrição<th scope=col>Categoria<th scope=col class=v>Qtd<th scope=col class=v>Total
<th scope=col class=v>%<th scope=col><span class=sr>Proporção</span></thead>
<tbody>{top}</tbody></table>
<p class=hint>Top 15 no período. Parcelas da mesma compra somam numa linha.</p>
</section></div></section>

<section><h2 class=rot>Razão</h2><div>
<div class=rolagem><table class=razao><caption class=sr>Movimentações do período</caption>
<thead><tr><th scope=col>Org<th scope=col>Tipo<th scope=col>Descrição<th scope=col>Obs
<th scope=col>Categoria<th scope=col class=v>Valor<th scope=col class=v>Acum</thead>
{linhas}</table></div>
<p class=hint>500 linhas mais recentes, agrupadas por dia. "Acum" é o acumulado do fluxo de
consumo (ignora fatura, interno e investimentos), da mais antiga para a mais nova — não é o
saldo da conta. Investimentos aparecem na seção própria acima.</p>
</div></section>
</div>
"""

# ponytail: uma troca de innerHTML, sem framework nem endpoint JSON. O servidor já devolve a
# página inteira (o POST redireciona pro GET com o recado) — então o fetch segue o 303 e a
# resposta é o HTML novo: basta trocar a folha. Sem JS o form nativo continua funcionando.
JS = """<script>
const folha=()=>document.querySelector('.folha')
async function troca(u,opt){
  const velha=folha(); velha.style.opacity=.55
  const r=await fetch(u,opt), d=new DOMParser().parseFromString(await r.text(),'text/html')
  const abertos=[...document.querySelectorAll('details')].map(x=>x.open)
  velha.replaceWith(d.querySelector('.folha'))
  document.querySelectorAll('details').forEach((x,i)=>x.open=abertos[i]??false)
  history.replaceState(null,'',r.url)
  initDD()
}
addEventListener('submit',ev=>{
  const f=ev.target, fd=new FormData(f)
  ev.preventDefault()
  if(f.method.toUpperCase()=='POST')
    troca(f.action,{method:'POST',
      body:f.enctype.includes('multipart')?fd:new URLSearchParams(fd)})
  else troca('?'+new URLSearchParams([...fd].filter(([,v])=>v)))
})
// atalhos de período e filtros são links de query: mesma troca
addEventListener('click',ev=>{
  const a=ev.target.closest('a[href^="?"]')
  if(a){ev.preventDefault(); troca(a.getAttribute('href'))}
})
// --- dropdown pesquisável ---
function initDD(){
  document.querySelectorAll('.dd').forEach(dd=>{
    if(dd._dd) return
    dd._dd=true
    const inp=dd.querySelector('.dd-in'), ul=dd.querySelector('.dd-list')
    const items=()=>[...ul.querySelectorAll('li:not(.dd-novo)')]
    const novo=ul.querySelector('.dd-novo')
    let cur=-1
    function open(){dd.classList.add('open'); filtra()}
    function close(){dd.classList.remove('open'); cur=-1; act()}
    function filtra(){
      const v=inp.value.toLowerCase().trim()
      let vis=0
      items().forEach(li=>{
        const show=!v||li.textContent.toLowerCase().includes(v)
        li.classList.toggle('dd-hide',!show)
        if(show) vis++
      })
      if(novo){
        // mostrar "criar X" se digitou algo que não é match exato
        const exact=items().some(li=>li.textContent.toLowerCase()===v)
        if(v&&!exact){novo.textContent='+ criar "'+inp.value.trim()+'"'; novo.classList.remove('dd-hide')}
        else novo.classList.add('dd-hide')
      }
    }
    function act(){items().concat(novo?[novo]:[]).forEach((li,i)=>li.classList.toggle('act',i===cur))}
    function pick(val){inp.value=val; close(); inp.dispatchEvent(new Event('change',{bubbles:true}))}
    inp.addEventListener('focus',open)
    inp.addEventListener('input',()=>{open(); cur=-1; act()})
    inp.addEventListener('keydown',ev=>{
      const vis=items().concat(novo?[novo]:[]).filter(l=>!l.classList.contains('dd-hide'))
      if(ev.key==='ArrowDown'){ev.preventDefault(); cur=Math.min(cur+1,vis.length-1); markVis(vis)}
      else if(ev.key==='ArrowUp'){ev.preventDefault(); cur=Math.max(cur-1,0); markVis(vis)}
      else if(ev.key==='Enter'&&dd.classList.contains('open')&&cur>=0){
        ev.preventDefault(); pick(vis[cur].dataset.val||vis[cur].textContent.replace(/^\+ criar "/,'').replace(/"$/,''))}
      else if(ev.key==='Escape') close()
    })
    function markVis(vis){vis.forEach((li,i)=>li.classList.toggle('act',i===cur))}
    ul.addEventListener('mousedown',ev=>{
      ev.preventDefault() // keep focus on input
      const li=ev.target.closest('li')
      if(!li) return
      pick(li.dataset.val||li.textContent.replace(/^\+ criar "/,'').replace(/"$/,''))
    })
    document.addEventListener('click',ev=>{if(!dd.contains(ev.target)) close()})
  })
}
initDD()
</script>"""

# atalhos de período: viram de/até no servidor, sem JS
RAPIDO = ((7, "7d"), (30, "30d"), (60, "60d"), (90, "90d"), (180, "6m"), (365, "1a"), (0, "tudo"))

# Agrupador de estabelecimento: tira o sufixo de parcela que a fatura do Inter cola na
# descrição ("JIM.COM* X (Parcela 01 de 04)"), senão cada parcela vira uma linha própria
# e o ranking de "onde mais gastei" mente. Também deixa o trecho pronto pra virar regra.
LOJA = ("CASE WHEN instr(descricao,' (Parcela ')>0 "
        "THEN substr(descricao,1,instr(descricao,' (Parcela ')-1) ELSE descricao END")

# Alvo da triagem. 79% do que está em 'outros' vem do Mercado Pago sem descrição nenhuma —
# aí o tipo é o único sinal, e serve de padrão porque a regra casa contra "tipo + descrição".
# Sem esse fallback a fila de triagem mostraria uma linha vazia em vez de 376 lançamentos.
ALVO = f"CASE WHEN descricao<>'' THEN {LOJA} ELSE tipo END"

ORG = {"inter": "INT", "mercado_pago": "MP"}
# status do caminho felizial: não informa nada em 98% das linhas, então a coluna só mostra exceção
OK = ("concluido", "approved")

e = lambda s: html.escape(str(s or ""))
# clicar na descrição preenche o campo de regra livre (sem recarregar, mantém os filtros).
# Sem descrição não há o que copiar: mostra o travessão em vez de um link vazio e clicável.
link = lambda d: (f"<a href='#p' onclick=\"p.value=this.textContent\">{e(d)}</a>" if d
                  else "<span class=cod>—</span>")


def desc_cel(r):
    """Descrição do razão. Sem descrição (pix/bank_transfer do MP) ou com nota já escrita,
    a célula é um campo editável — nota é coluna própria, sobrevive ao resync."""
    if r[3] and not r[8]:
        return link(r[3])
    return (f"<form method=post action=/nota class=nota-ed>"
            f"<input type=hidden name=id value=\"{e(r[7])}\">"
            f"<input name=nota value=\"{e(r[8])}\" placeholder=\"{e(r[3]) or 'descrever...'}\">"
            f"<button>ok</button></form>")


def dd_html(name, cats, placeholder="categoria", value="", required=True):
    """Gera o HTML do dropdown pesquisável (.dd) para uma lista de categorias."""
    lis = "".join(f"<li data-val='{e(c)}'>{e(c)}</li>" for c in cats)
    req = " required" if required else ""
    return (f"<div class=dd><input class=dd-in name='{e(name)}' value='{e(value)}'"
            f" autocomplete=off placeholder='{e(placeholder)}'{req}>"
            f"<span class=dd-arrow>▾</span>"
            f"<ul class=dd-list>{lis}<li class='dd-novo dd-hide'></li></ul></div>")


def render(q):
    de, ate, origem, tipo, cat, desc, dias = (q.get(k, [""])[0] for k in
                                              ("de", "ate", "origem", "tipo", "cat", "desc", "dias"))
    atual = dias if dias.isdigit() and int(dias) > 0 else ("0" if not (de or ate) else "")
    if atual not in ("", "0"):  # atalho 30d/60d/... vence de/até digitados
        hoje = datetime.date.today()
        de = (hoje - datetime.timedelta(days=int(dias))).isoformat()
        ate = hoje.isoformat()
    where, args = ["1=1"], []
    if de:
        where.append("data >= ?"); args.append(de)
    if ate:
        where.append("data <= ?"); args.append(ate + "T23:59:59")
    if origem:
        where.append("origem = ?"); args.append(origem)
    if tipo:
        where.append("lower(tipo) LIKE ?"); args.append(f"%{tipo.lower()}%")
    if cat:
        where.append("categoria = ?"); args.append(cat)
    if desc:
        where.append("lower(descricao) LIKE ?"); args.append(f"%{desc.lower()}%")
    w = " AND ".join(where)
    # agregados ignoram investimento/fatura; o razão mostra tudo.
    # Filtrar explicitamente uma dessas categorias = querer consultá-la: aí ela entra na conta.
    fora = [x for x in store.NAO_FLUXO if x != cat]
    wf = f"{w} AND categoria NOT IN ({','.join('?' * len(fora))})"
    argsf = args + fora

    with store.conn() as c:
        # investimentos: seção própria
        wi = f"{w} AND categoria IN ({','.join('?' * len(store.INVESTIMENTO_CATS))})"
        argsi = args + list(store.INVESTIMENTO_CATS)
        inv_rows = c.execute(
            f"SELECT data,origem,tipo,descricao,categoria,valor FROM movimentacoes "
            f"WHERE {wi} ORDER BY data DESC LIMIT 200", argsi).fetchall()
        aplicacao = c.execute(
            f"SELECT COALESCE(SUM(-valor),0) FROM movimentacoes "
            f"WHERE {wi} AND categoria='aplicacao' AND valor<0",
            argsi).fetchone()[0]
        resgate = c.execute(
            f"SELECT COALESCE(SUM(valor),0) FROM movimentacoes "
            f"WHERE {wi} AND categoria='resgate' AND valor>0",
            argsi).fetchone()[0]
        rendimento_total = c.execute(
            f"SELECT COALESCE(SUM(valor),0) FROM movimentacoes "
            f"WHERE {wi} AND categoria='rendimento' AND valor>0",
            argsi).fetchone()[0]
        n_inv = c.execute(f"SELECT COUNT(*) FROM movimentacoes WHERE {wi}", argsi).fetchone()[0]

        # B3: só o filtro de data serve (b3_mov não tem origem/tipo/categoria)
        wb, argsb = ["1=1"], []
        if de:
            wb.append("data >= ?"); argsb.append(de)
        if ate:
            wb.append("data <= ?"); argsb.append(ate)
        wb = " AND ".join(wb)
        prov = ",".join("?" * len(b3_pdf.PROVENTOS))
        b3_ativos = c.execute(
            f"SELECT COALESCE(NULLIF(ticker,''),produto),COUNT(*),"
            f"COALESCE(SUM(CASE WHEN mov IN ({prov}) THEN valor END),0),MAX(data),mov "
            f"FROM b3_mov WHERE {wb} "
            f"GROUP BY 1 ORDER BY 3 DESC,2 DESC LIMIT 60",
            list(b3_pdf.PROVENTOS) + argsb).fetchall()
        n_b3 = c.execute(f"SELECT COUNT(*) FROM b3_mov WHERE {wb}", argsb).fetchone()[0]

        # razão: exclui investimentos (têm seção própria), salvo quando é a categoria filtrada
        fora_inv = [x for x in store.INVESTIMENTO_CATS if x != cat]
        wr = f"{w} AND categoria NOT IN ({','.join('?' * len(fora_inv))})"
        argsr = args + fora_inv
        rows = c.execute(f"SELECT data,origem,tipo,descricao,status,categoria,valor,id,nota "
                         f"FROM movimentacoes WHERE {wr} ORDER BY data DESC LIMIT 500",
                         argsr).fetchall()
        cats = c.execute(f"SELECT categoria,SUM(-valor),COUNT(*) FROM movimentacoes WHERE {wf} AND valor<0 "
                         f"GROUP BY categoria ORDER BY 2 DESC", argsf).fetchall()
        gasto, entrada, dmin, dmax = c.execute(
            f"SELECT COALESCE(SUM(CASE WHEN valor<0 THEN -valor END),0),"
            f"COALESCE(SUM(CASE WHEN valor>0 THEN valor END),0),MIN(data),MAX(data) "
            f"FROM movimentacoes WHERE {wf}", argsf).fetchone()
        n, sem_cat = c.execute(f"SELECT COUNT(*),COALESCE(SUM(categoria='outros'),0) "
                               f"FROM movimentacoes WHERE {w}", args).fetchone()
        meses = c.execute(
            f"SELECT substr(data,1,7),SUM(CASE WHEN valor<0 THEN -valor ELSE 0 END),"
            f"SUM(CASE WHEN valor>0 THEN valor ELSE 0 END) FROM movimentacoes WHERE {wf} "
            f"GROUP BY 1 ORDER BY 1 DESC LIMIT 12", argsf).fetchall()[::-1]
        # aplicado líquido por mês (aplicação − resgate): -valor cobre os dois sinais
        apl_mes = dict(c.execute(
            f"SELECT substr(data,1,7),SUM(-valor) FROM movimentacoes "
            f"WHERE {w} AND categoria IN ('aplicacao','resgate') GROUP BY 1", args).fetchall())
        top = c.execute(f"SELECT {LOJA},COUNT(*),SUM(-valor),MAX(categoria) FROM movimentacoes WHERE {wf} "
                        f"AND valor<0 GROUP BY 1 ORDER BY 3 DESC LIMIT 15", argsf).fetchall()
        pend = c.execute(f"SELECT {ALVO},COUNT(*),SUM(valor) FROM movimentacoes "
                         f"WHERE {w} AND categoria='outros' GROUP BY 1 "
                         f"ORDER BY ABS(SUM(valor)) DESC LIMIT 20", args).fetchall()
        todas = [r[0] for r in c.execute("SELECT DISTINCT categoria FROM movimentacoes "
                                         "ORDER BY 1").fetchall()]
        cobertura = c.execute(
            "SELECT substr(data,1,7) AS mes, "
            "SUM(origem='inter')>0, SUM(origem='mercado_pago')>0 "
            "FROM movimentacoes GROUP BY 1 ORDER BY 1").fetchall()
        rs = store.regras(c)
        conf = store.conferencia(c)
        fat_aberta = store.fatura_aberta(c)
        # parcelamento é compromisso futuro: não segue o filtro de período (que olha pra trás)
        parcelas, parc_meses = store.parcelamentos(c)
        # drill-down: top gastos da categoria selecionada, mais caro primeiro
        if cat:
            drilldown_rows = c.execute(
                f"SELECT data,origem,tipo,descricao,valor FROM movimentacoes "
                f"WHERE {w} AND valor<0 ORDER BY valor ASC LIMIT 30", args).fetchall()
        else:
            drilldown_rows = []

    # ponytail: barras em CSS puro, sem lib de gráfico. Altura relativa ao maior mês.
    # ponytail: apl negativo (mês de resgate líquido) não vira barra, só sai do gráfico
    meses = [(m, g, en, max(apl_mes.get(m, 0), 0)) for m, g, en in meses]
    topo = max((max(g, en, ap) for _, g, en, ap in meses), default=0) or 1
    px = lambda v: round(84 * v / topo)
    # escala no eixo Y: topo, metade, zero — valores abreviados (k = mil)
    def abrev(v):
        if v >= 1000:
            r = v / 1000
            return f"{r:.0f}k" if r == int(r) else f"{r:.1f}k"
        return f"{v:.0f}"
    meio = topo / 2
    escala_html = (f"<span>{abrev(topo)}</span><span>{abrev(meio)}</span><span>0</span>"
                   if topo > 1 else "<span></span><span></span><span>0</span>")
    max_cat = max((b for _, b, _ in cats), default=0) or 1
    max_top = max((b for _, _, b, _ in top), default=0) or 1
    fluxo = max(gasto, entrada) or 1
    pct = lambda v: 100 * v / (gasto or 1)
    dd = ((datetime.date.fromisoformat(dmax[:10]) - datetime.date.fromisoformat(dmin[:10])).days
          + 1) if dmin else 1
    liquido = entrada - gasto
    # atalhos preservam os outros filtros; 'tudo' só acende quando não há data nenhuma
    manter = [(k, v) for k in ("origem", "tipo", "cat", "desc") for v in q.get(k, []) if v]
    manter_sem_cat = [(k, v) for k, v in manter if k != "cat"]
    url = lambda d: "?" + urllib.parse.urlencode(manter + ([("dias", d)] if d else []))

    # clicar num mês (gráfico ou cobertura) filtra o período pra aquele mês, mantendo os outros filtros
    def mes_url(m):
        y, mo = int(m[:4]), int(m[5:7])
        fim = datetime.date(y + mo // 12, mo % 12 + 1, 1) - datetime.timedelta(days=1)
        return "?" + urllib.parse.urlencode(manter + [("de", f"{m}-01"), ("ate", fim.isoformat())])

    recado = q.get("msg", [""])[0]
    meta = " · ".join(x for x in (
        f"R$ {brl(gasto / dd)}/dia", f"{mil(n)} lançamentos",
        f"<a href=#triar>{mil(sem_cat)} sem categoria</a>" if sem_cat else "") if x)
    opcoes_lista = list(dict.fromkeys(list(store.CATEGORIAS) + todas))
    # investimentos: saldo aplicado = aplicações - resgates (quanto está "lá dentro")
    inv_liquido = aplicacao - resgate
    caixa = liquido - inv_liquido  # aplicação sai da conta: entra no caixa, não no gasto
    fluxo = max(fluxo, inv_liquido)  # aplicações entram na escala das barras do resumo
    # drill-down: tabela de movimentações mais caras na categoria selecionada
    if drilldown_rows:
        dd_linhas = "".join(
            f"<tr><td>{dia_br(r[0][:10])}<td class=cod>{ORG.get(r[1], e(r[1]))}"
            f"<td>{e(r[2])}<td class=desc>{e(r[3])}"
            f"<td class='v neg'>{brl(-r[4])}"
            for r in drilldown_rows)
        drilldown_html = (
            f"<h3 style=margin-top:1.2rem>Movimentações — {e(cat)}</h3>"
            f"<p class=hint>Top 30 gastos na categoria, do mais caro ao mais barato.</p>"
            f"<table class=pautada><caption class=sr>Gastos na categoria {e(cat)}</caption>"
            f"<thead><tr><th scope=col>Data<th scope=col>Org<th scope=col>Tipo"
            f"<th scope=col>Descrição<th scope=col class=v>Valor</thead>"
            f"<tbody>{dd_linhas}</tbody></table>")
    else:
        drilldown_html = ""
    # parcelado: abertos e quitados em tabelas separadas — o que importa é o que ainda vai cair
    parc_abertos = [p for p in parcelas if p.restantes]
    parc_quitados = [p for p in parcelas if not p.restantes]
    parc_aberto_total = sum(p.aberto for p in parc_abertos)
    parc_max = max((p.aberto for p in parc_abertos), default=0) or 1
    return PAGE.format(
        icone=ICONE, nao_fluxo=" e ".join(store.NAO_FLUXO), de=e(de), ate=e(ate), tipo=e(tipo), desc=e(desc),
        janela=f"{dia_br(dmin[:10])} — {dia_br(dmax[:10])}" if dmin else "sem lançamentos",
        msg=f"<p class='msg{' erro' if recado.startswith('erro') else ''}'>{e(recado)}</p>"
            if recado else "",
        v_gasto=brl(gasto), v_entrada=brl(entrada),
        v_inv_liquido2=brl(inv_liquido),
        w_apl=round(100 * max(inv_liquido, 0) / fluxo),
        v_caixa=f"{'+' if caixa >= 0 else '-'}R$ {brl(abs(caixa))}",
        w_gasto=round(100 * gasto / fluxo), w_entrada=round(100 * entrada / fluxo),
        meta=meta, n_outros=f"{mil(sem_cat)} lançamento{'' if sem_cat == 1 else 's'}",
        rapido="".join(f"<a class={'on' if str(d) == atual else 'off'} href='{e(url(d))}'>{lbl}</a>"
                       for d, lbl in RAPIDO),
        top="".join(f"<tr><td>{link(d)}<td>{e(cat2)}<td class=v>{k}<td class='v neg'>{brl(v)}"
                    f"<td class=v>{pct(v):.0f}%"
                    f"<td><i class=bar style=width:{round(100 * v / max_top)}%></i>"
                    for d, k, v, cat2 in top) or "<tr><td colspan=6>sem gastos no período",
        filtro_cat_dd=dd_html("cat", todas, placeholder="todas", value=cat, required=False),
        regras_linhas="".join(
            # dropdown na categoria: /regra faz upsert, então salvar por cima troca a categoria
            f"<tr><td>{e(p)}"
            f"<td><form method=post action=/regra class=regra-ed>"
            f"<input type=hidden name=padrao value=\"{e(p)}\">"
            f"{dd_html('categoria', opcoes_lista, value=c2)}"
            f"<button>ok</button></form>"
            f"<td><form method=post action=/rm_regra class=regra-rm>"
            f"<input type=hidden name=padrao value=\"{e(p)}\">"
            f"<button title='Remover regra'>✕</button></form>"
            for p, c2 in rs) or "<tr><td colspan=3>nenhuma regra",
        n_regras=len(rs),
        pl_regras="" if len(rs) == 1 else "s",
        regra_dd=dd_html("categoria", opcoes_lista, placeholder="lazer"),
        origens="".join(f"<option value='{v}'{' selected' if v == origem else ''}>{l}"
                        for v, l in (("", "todas"), ("inter", "Inter"), ("mercado_pago", "Mercado Pago"))),
        cobertura="".join(
            "<a href='{qs}' class=cob-mes><em>{lbl}</em>{inter}{mp}</a>".format(
                qs=e(mes_url(m)),
                lbl=mes_br(m),
                inter='<span class="cob-tag inter">INT</span>' if has_inter else '<span class=cob-miss>\u2014</span>',
                mp='<span class="cob-tag mp">MP</span>' if has_mp else ''
            ) for m, has_inter, has_mp in cobertura
        ) or "<em>sem dados</em>",
        meses="".join(f"<a href='{e(mes_url(m))}' "
                      f"title='{mes_br(m)}: gasto {brl(g)} / aplicado {brl(ap)} / entrada {brl(en)}"
                      f" — ver só este mês'>"
                      f"<span><i style=height:{px(g)}px></i><u style=height:{px(ap)}px></u>"
                      f"<b style=height:{px(en)}px></b></span>"
                      f"<em>{mes_br(m)}</em></a>"
                      for m, g, en, ap in meses) or "<a><em>sem dados</em></a>",
        escala=escala_html,
        cats="".join(f"<tr><td><a href='?{urllib.parse.urlencode(manter_sem_cat + [('cat', a)])}'>{e(a)}</a>"
                     f"<td class='v neg'>{brl(b)}<td class=v>{c3}"
                     f"<td class=v>{pct(b):.0f}%"
                     f"<td><i class=bar style=width:{round(100 * b / max_cat)}%></i>"
                     for a, b, c3 in cats) or "<tr><td colspan=5>sem dados",
        drilldown=drilldown_html,
        triagem="".join(
            # SUM(valor) do grupo pode ser positivo (entrada): vermelho é só saída
            f"<tr><td>{e(d)}<td class=v>{k}<td class='v{' neg' if v < 0 else ''}'>{brl(v)}"
            f"<td><form method=post action=/regra>"
            f"<input type=hidden name=padrao value=\"{e(d)}\">"
            f"{dd_html('categoria', opcoes_lista)}"
            f"<button>ok</button></form>" for d, k, v in pend
        ) or "<tr><td colspan=4>nada em 'outros'",
        hoje=datetime.date.today().isoformat(),
        v_fatura_aberta=brl(fat_aberta),
        conferencia="".join(
            # não rastreado: vermelho quando falta dinheiro, tinta normal quando sobra
            f"<tr><td>{dia_br(r[0])}<td class=v>{brl(r[1])}<td class=v>{brl(r[2])}"
            f"<td class=v>{brl(r[3])}<td class='v neg'>{brl(r[4])}"
            + "".join(f"<td class='v{' neg' if v is not None and v < 0 else ''}'>"
                      f"{brl(v) if v is not None else '—'}" for v in r[5:])
            for r in conf) or "<tr><td colspan=8>nenhum saldo registrado",
        fechamento=store.FECHAMENTO,
        v_parc_aberto=brl(parc_aberto_total),
        n_parc_ativos=mil(len(parc_abertos)),
        v_parc_proxima=brl(parc_meses[0][1] if parc_meses else 0),
        parc_fim=mes_br(parc_meses[-1][0]) if parc_meses else "—",
        n_parc_quitados=f"{mil(len(parc_quitados))} parcelamento"
                        f"{'' if len(parc_quitados) == 1 else 's'}",
        pl_parc="" if len(parc_quitados) == 1 else "s",
        parc_linhas="".join(
            # filtrar por descrição mostra as parcelas dessa compra no razão
            f"<tr><td class=desc><a href='?{urllib.parse.urlencode([('desc', p.loja)])}'>"
            f"{e(p.loja)}</a><br><span class=cod>{dia_br(p.compra)}</span>"
            f"<td>{e(p.categoria)}<td class=cod>{e(p.cartao.replace('cartao ', ''))}"
            f"<td class=v>{p.pagas}/{p.parcelas}"
            f"<td class='v neg'>{brl(p.valor_parcela)}"
            f"<td class='v neg'>{brl(p.aberto)}{'' if p.completo else '*'}"
            f"<td>{mes_br(p.ultima)}"
            f"<td><span class=parc-prog title='{p.pagas} de {p.parcelas} pagas'>"
            f"<i style=width:{round(100 * p.pagas / p.parcelas)}%></i></span>"
            for p in parc_abertos) or "<tr><td colspan=8>nenhuma compra parcelada em aberto",
        parc_meses="".join(
            f"<div class=parc-mes><span>{mes_br(m)}</span>"
            f"<b class=neg>R$ {brl(v)}</b></div>" for m, v in parc_meses
        ) or "<p class=hint>nada parcelado pra frente</p>",
        parc_quitados="".join(
            f"<tr><td class=desc><a href='?{urllib.parse.urlencode([('desc', p.loja)])}'>"
            f"{e(p.loja)}</a><br><span class=cod>{dia_br(p.compra)}</span>"
            f"<td>{e(p.categoria)}<td class=v>{p.parcelas}"
            f"<td class='v parc-quit'>{brl(p.valor_parcela)}"
            f"<td class='v parc-quit'>{brl(p.valor_total)}{'' if p.completo else '*'}"
            f"<td class=parc-quit>{mes_br(p.ultima)}"
            for p in parc_quitados) or "<tr><td colspan=6>nenhum parcelamento quitado",
        v_aplicacao=brl(aplicacao), v_resgate=brl(resgate),
        v_rendimento=brl(rendimento_total),
        v_inv_liquido=f"R$ {brl(inv_liquido)}" if inv_liquido >= 0
                      else f"-R$ {brl(abs(inv_liquido))}",
        n_inv=f"{mil(n_inv)} movimentação{'' if n_inv == 1 else 'ões'}",
        inv_linhas="".join(
            f"<tr><td>{dia_br(r[0][:10])}<td class=cod>{ORG.get(r[1], e(r[1]))}"
            f"<td>{e(r[2])}<td class=desc>{e(r[3])}<td>{e(r[4])}"
            f"<td class='v{' inv-apl' if r[5] < 0 else ''}'>{brl(r[5])}"
            for r in inv_rows
        ) or "<tr><td colspan=6>sem investimentos no período",
        n_b3=f"{mil(n_b3)} evento{'' if n_b3 == 1 else 's'}",
        b3_ativos="".join(
            f"<tr><td>{e(a[:48])}<td class=v>{k}<td class='v{' neg' if p < 0 else ''}'>{brl(p)}"
            f"<td class=cod>{dia_br(d)} · {e(m)}"
            for a, k, p, d, m in b3_ativos
        ) or "<tr><td colspan=4>nenhum evento da B3 importado no período",
        linhas=razao(rows)) + JS


def razao(rows):
    """Razão agrupado por dia (faixa do papel pautado) + o fio do acumulado na margem."""
    # o acumulado só faz sentido pra frente: soma na ordem cronológica e volta pra ordem da tabela
    acum, s = [], 0.0
    for r in reversed(rows):
        if r[5] not in store.NAO_FLUXO:
            s += r[6]
        acum.append(s)
    acum.reverse()
    out, faixa = [], 0
    for dia, grupo in itertools.groupby(zip(rows, acum), key=lambda ra: ra[0][0][:10]):
        out.append(f"<tbody class={'par' if faixa % 2 else 'impar'}>"
                   f"<tr class=dia><th colspan=7>{dia_br(dia)}")
        for r, a in grupo:
            acum_cel = (f"<td class='v{' neg' if a < 0 else ''}'>{brl(a)}"
                        if r[5] not in store.NAO_FLUXO else "<td>")
            out.append(f"<tr><td class=cod>{ORG.get(r[1], e(r[1]))}<td>{e(r[2])}"
                       f"<td class=desc>{desc_cel(r)}"
                       f"<td class=cod>{'' if r[4] in OK else e(r[4])}<td>{e(r[5])}"
                       f"<td class='v{' neg' if r[6] < 0 else ''}'>{brl(r[6])}"
                       f"{acum_cel}")
        out.append("</tbody>")
        faixa += 1
    return "".join(out) or "<tbody><tr><td colspan=7>sem dados</tbody>"


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        alvo = urllib.parse.urlparse(self.path)
        if alvo.path != "/":  # ponytail: sem isso, /favicon.ico roda as 8 queries de novo
            return self.send_error(404)
        body = render(urllib.parse.parse_qs(alvo.query)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        acao = {"/regra": self.regra, "/rm_regra": self.rm_regra, "/nota": self.nota,
                "/import": self.importar, "/import_b3": self.importar_b3,
                "/sync": self.sincronizar, "/saldo": self.saldo}
        if self.path not in acao:
            return self.send_error(404)
        try:
            msg = acao[self.path]()
        except (ValueError, RuntimeError) as err:
            msg = f"erro: {err}"
        # volta pro dashboard (mesmos filtros) com o recado. Só path+query do Referer,
        # nunca o host, para não virar redirect aberto.
        ref = urllib.parse.urlsplit(self.headers.get("Referer") or "")
        q = urllib.parse.parse_qs(ref.query)
        q["msg"] = [msg]
        self.send_response(303)
        self.send_header("Location", f"{ref.path or '/'}?{urllib.parse.urlencode(q, doseq=True)}")
        self.end_headers()

    def corpo(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def campos(self):
        return urllib.parse.parse_qs(self.corpo().decode("utf-8"))

    def arquivos(self):
        """multipart -> [(nome, bytes)]. ponytail: email.parser em vez de cgi (removido no 3.13)."""
        raw = b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + self.corpo()
        msg = email.parser.BytesParser().parsebytes(raw)
        return [(p.get_filename(), p.get_payload(decode=True))
                for p in msg.get_payload() if p.get_filename()]

    def regra(self):
        q = self.campos()
        with store.conn() as c:
            n = store.add_regra(c, q.get("padrao", [""])[0], q.get("categoria", [""])[0])
        return f"regra criada; {n} lançamentos recategorizados"

    def rm_regra(self):
        q = self.campos()
        padrao = q.get("padrao", [""])[0].strip()
        if not padrao:
            raise ValueError("padrão não pode ser vazio")
        with store.conn() as c:
            c.execute("DELETE FROM regras WHERE padrao=?", (store.normaliza(padrao),))
            n = store.recategoriza(c)
        return f"regra '{padrao}' removida; {n} recategorizados"

    def nota(self):
        q = self.campos()
        nota = q.get("nota", [""])[0]
        with store.conn() as c:
            store.set_nota(c, q.get("id", [""])[0], nota)
        return "descrição salva" if nota.strip() else "descrição removida"

    def saldo(self):
        q = self.campos()
        def num(k):
            # input type=number manda ponto; aceita "1.234,56" também, colar do app é comum
            v = (q.get(k, [""])[0] or "0").strip()
            return float(v.replace(".", "").replace(",", ".") if "," in v else v)
        data = q.get("data", [""])[0] or datetime.date.today().isoformat()
        with store.conn() as c:
            store.set_saldo(c, data, num("total"), num("caixinhas"), num("inter"),
                            num("fatura"))
        return f"saldo de {dia_br(data)} registrado"

    def importar(self):
        out = []
        with store.conn() as c:
            for nome, blob in self.arquivos():
                # ponytail: erro de um arquivo não aborta o lote
                try:
                    out.append(f"{nome}: {store.upsert(c, inter_pdf.parse(io.BytesIO(blob)))}")
                except ValueError as e:
                    out.append(f"{nome}: ERRO {e}")
        return "importado -> " + ", ".join(out) if out else "nenhum arquivo enviado"

    def importar_b3(self):
        """Extrato de movimentação da B3: entrada própria, tabela própria (b3_mov)."""
        out = []
        with store.conn() as c:
            for nome, blob in self.arquivos():
                try:
                    out.append(f"{nome}: {store.upsert_b3(c, b3_pdf.parse(io.BytesIO(blob)))}")
                except ValueError as e:
                    out.append(f"{nome}: ERRO {e}")
        return "B3 importado -> " + ", ".join(out) if out else "nenhum arquivo enviado"

    def sincronizar(self):
        dias = int(self.campos().get("dias", ["30"])[0])
        return f"Mercado Pago: {mp_sync.sync(dias)} movimentações ({dias}d)"

    def log_message(self, *a):
        pass

    def handle(self):  # ponytail: browser fecha aba = ConnectionError no write, ruído
        try:
            super().handle()
        except ConnectionError:
            pass


if __name__ == "__main__":
    # ponytail: só localhost por padrão, sem auth. Este dashboard mostra o
    # extrato bancário inteiro e não pede senha — expor na rede (FIN_HOST=0.0.0.0)
    # entrega o histórico financeiro a quem alcançar a porta. Só faça isso atrás
    # de uma rede em que você confia, e sabendo o risco.
    host = os.getenv("FIN_HOST", "127.0.0.1")
    port = int(os.getenv("FIN_PORT", "8000"))
    if host != "127.0.0.1":
        print(f"AVISO: escutando em {host} — o dashboard não tem autenticação.")
    print(f"http://{'localhost' if host == '127.0.0.1' else host}:{port}  (Ctrl+C para sair)")
    HTTPServer((host, port), H).serve_forever()
