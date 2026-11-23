"""Campanhas de anúncio: cria no Meta (pelo Zernio), pausa/ativa, muda orçamento, puxa gasto e
cruza com a comissão da Shopee por Sub ID.

Regras (automacao/campanhas.md):
- O relatório da Shopee de um dia só sai no dia seguinte: lucro compara o gasto de ONTEM (D-1)
  com as comissões de D-1.
- Teste = 3 dias fechados. 2º dia com comissão acumulada < gasto: só alerta.
  3º dia em diante com comissão acumulada < gasto: o robô pausa sozinho às 23:59 (pedido do Felipe, 23/11).
  Se o cliente reativar depois, o robô não pausa de novo.
"""
import logging
import shutil
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import subid, supa, zernio

log = logging.getLogger("robo.campanhas")
TZ = ZoneInfo("America/Sao_Paulo")
AUTO = "pausada automaticamente pelo robô"
MANTIDA = "Mantida pelo dono"  # o dono decidiu manter: o robô não mexe na recomendação nem pausa


def _today():
    return datetime.now(TZ).date()


def _set(cid, **values):
    supa.update("campanhas", {"id": f"eq.{cid}"}, values)


def _contas(uid):
    p = supa.one("profiles", {"id": f"eq.{uid}"}) or {}
    return (p.get("zernio_ads_account_id") or "").strip(), (p.get("meta_ad_account_id") or "").strip()


# ------------------------------------------------------------------ criar
def criar_pedidas():
    agora = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    pedidas = supa.select("campanhas", {"status": "eq.pedido", "order": "created_at.asc", "limit": 200})
    # "inicio" (AAAA-MM-DD HH:MM, horário de Brasília) agenda a subida; vazio = sobe já
    prontas = [c for c in pedidas if (c.get("inicio") or "").replace("T", " ")[:16] <= agora]
    for c in prontas[:5]:
        conta, ad_account = _contas(c["user_id"])
        if not conta or not ad_account:
            _set(c["id"], status="erro", error_message="Conecte o Meta Ads em Conectar contas e escolha a conta de anúncios.")
            continue
        p = supa.one("produtos", {"id": f"eq.{c['produto_id']}"}) or {}
        if not p.get("final_path"):
            _set(c["id"], status="erro", error_message="O produto ainda não tem vídeo final.")
            continue
        got = supa.update("campanhas", {"id": f"eq.{c['id']}", "status": "eq.pedido"}, {"status": "criando"})
        if not got:
            continue
        work = tempfile.mkdtemp(prefix="ad-")
        try:
            video = supa.download(p["final_path"], f"{work}/final.mp4")
            url = zernio.upload_video(video, "anuncio.mp4")
            ad = zernio.create_video_ad(
                conta, ad_account, c.get("nome") or f"CA | {p.get('nome', '')} | {c.get('sub_id', '')}",
                url, c.get("texto") or "", c.get("titulo") or (p.get("nome") or "Achadinho da Shopee"),
                c["link_url"], float(c.get("orcamento_diario") or 25),
                int(c.get("idade_min") or 18), int(c.get("idade_max") or 45), c.get("genero") or "female",
                status="ACTIVE", idem=f"campanha-{c['id']}",
            )
            _set(c["id"], status="em_revisao", error_message="", zernio_ad_id=ad.get("_id") or "",
                 platform_campaign_id=ad.get("platformCampaignId") or "",
                 platform_adset_id=ad.get("platformAdSetId") or "",
                 ativada_em=_today().isoformat())
            log.info("campanha %s criada", c["id"])
        except Exception as e:  # noqa: BLE001
            log.exception("falha ao criar campanha")
            _set(c["id"], status="erro", error_message=f"Não consegui criar a campanha: {str(e)[:300]}")
        finally:
            shutil.rmtree(work, ignore_errors=True)


# ------------------------------------------------------------------ ações do cliente
def aplicar_acoes():
    for acao in ("pausar", "ativar", "orcamento", "excluir"):
        for c in supa.select("campanhas", {"acao": f"eq.{acao}"}):
            camp = c.get("platform_campaign_id") or ""
            try:
                if not camp:
                    raise RuntimeError("A campanha ainda não foi criada no Meta.")
                if acao == "pausar":
                    zernio.set_campaign_status(camp, "paused")
                    _set(c["id"], acao="", status="pausada", error_message="")
                elif acao == "ativar":
                    zernio.set_campaign_status(camp, "active")
                    _set(c["id"], acao="", status="ativa", error_message="")
                elif acao == "orcamento":
                    zernio.set_budget(camp, c.get("platform_adset_id"), float(c["orcamento_diario"]))
                    _set(c["id"], acao="", error_message="")
                else:
                    zernio.set_campaign_status(camp, "paused")  # excluir = parar (regra do Felipe)
                    _set(c["id"], acao="", status="encerrada", error_message="")
            except Exception as e:  # noqa: BLE001
                log.exception("falha na ação %s", acao)
                _set(c["id"], acao="", error_message=f"Não consegui {acao}: {str(e)[:300]}")


# ------------------------------------------------------------------ métricas
def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _walk(node):
    yield node
    for key in ("campaigns", "adSets", "adsets", "ads", "children"):
        for child in node.get(key) or []:
            yield from _walk(child)


def _salvar_metrica(c, dia, **vals):
    supa.upsert("campanha_metricas", {"campanha_id": c["id"], "user_id": c["user_id"], "data": dia, **vals},
                "campanha_id,data")


def ligar_sub_ids():
    """Liga cada campanha do Meta ao Sub ID lendo o link de destino dos anúncios, mesmo com nomes
    diferentes. Sub ID corrigido à mão (sub_id_origem='manual') nunca é trocado."""
    camps = supa.select("campanhas", {"status": "neq.erro", "limit": 1000})
    por_user = {}
    for c in camps:
        por_user.setdefault(c["user_id"], []).append(c)
    for p in supa.select("profiles", {"zernio_ads_account_id": "neq.", "meta_ad_account_id": "neq."}):
        uid = p.get("id") or p.get("user_id")
        por_user.setdefault(uid, [])
    for uid, lista in por_user.items():
        conta, ad_account = _contas(uid)
        if not conta or not ad_account:
            continue
        try:
            ads = zernio.list_ads_summary(conta, ad_account)
        except Exception:  # noqa: BLE001
            log.exception("lista de anúncios indisponível")
            continue
        meta = {}
        for ad in ads:
            pid = str(ad.get("platformCampaignId") or "").strip()
            if not pid:
                continue
            m = meta.setdefault(pid, {"nome": ad.get("campaignName") or ad.get("name") or "", "link": "",
                                      "ativa": False, "adset": ad.get("platformAdSetId") or ""})
            link = ((ad.get("creative") or {}).get("linkUrl") or "").strip()
            if link and not m["link"]:
                m["link"] = link
            st = str(ad.get("platformCampaignStatus") or ad.get("status") or "").lower()
            if st in ("active", "ativo"):
                m["ativa"] = True
        por_pid = {c["platform_campaign_id"]: c for c in lista if c.get("platform_campaign_id")}
        livres = [c for c in lista if not c.get("platform_campaign_id")]
        for pid, m in meta.items():
            sub = subid.de_link(m["link"])
            c = por_pid.get(pid)
            if not c and sub:
                c = next((x for x in livres if (x.get("sub_id") or "").strip().lower() == sub.lower()), None)
            if not c and m["nome"]:
                c = next((x for x in livres if (x.get("nome") or "").strip().lower() == m["nome"].strip().lower()
                          or (x.get("nome") or "").lower().removeprefix("ca | ").strip() == m["nome"].strip().lower()),
                         None)
            if c is None:
                if not subid.e_shopee(m["link"]):
                    continue  # campanha que não leva para a Shopee (ex.: ClickBank): não entra no app
                try:
                    supa.insert("campanhas", {
                        "user_id": uid, "nome": m["nome"], "platform_campaign_id": pid, "link_url": m["link"],
                        "sub_id": sub, "sub_id_origem": "auto" if sub else "",
                        "status": "ativa" if m["ativa"] else "pausada",
                        "ativada_em": _today().isoformat() if m["ativa"] else ""})
                except Exception:  # noqa: BLE001
                    log.exception("não consegui criar a campanha %s", pid)
                continue
            if c in livres:
                livres.remove(c)
            mud = {}
            if not c.get("platform_campaign_id"):
                mud["platform_campaign_id"] = pid
            if m["link"] and not c.get("link_url"):
                mud["link_url"] = m["link"]
            if c.get("sub_id_origem") != "manual" and sub and sub != c.get("sub_id"):
                mud["sub_id"], mud["sub_id_origem"] = sub, "auto"
            if mud:
                _set(c["id"], **mud)


def puxar_gasto():
    """Gasto, cliques e impressões dos últimos 4 dias de cada campanha, por dia."""
    ativas = supa.select("campanhas", {"platform_campaign_id": "neq.", "status": "neq.encerrada"})
    por_user = {}
    for c in ativas:
        por_user.setdefault(c["user_id"], []).append(c)
    hoje = _today()
    for uid, camps in por_user.items():
        conta, ad_account = _contas(uid)
        if not conta or not ad_account:
            continue
        try:
            tree = zernio.ads_tree(conta, ad_account, (hoje - timedelta(days=4)).isoformat(), hoje.isoformat())
        except Exception:  # noqa: BLE001
            log.exception("métricas indisponíveis")
            continue
        by_id = {c["platform_campaign_id"]: c for c in camps}
        for node in _walk(tree):
            cid = node.get("platformCampaignId") or node.get("platformId") or node.get("id")
            if cid not in by_id or node.get("level", "campaign") not in ("campaign", None):
                continue
            c = by_id.pop(cid)
            status = (node.get("status") or node.get("effectiveStatus") or "").lower()
            if c["status"] == "em_revisao" and status in ("active", "ativo"):
                _set(c["id"], status="ativa")
            for d in node.get("daily") or []:
                dia = (d.get("date") or d.get("dateStart") or d.get("day") or "")[:10]
                if not dia:
                    continue
                actions = d.get("actions") or {}
                _salvar_metrica(c, dia, gasto=_num(d.get("spend")), impressoes=int(_num(d.get("impressions"))),
                                cliques=int(_num(d.get("clicks"))),
                                cliques_link=int(_num(actions.get("link_click") if isinstance(actions, dict) else 0)))


def puxar_comissoes():
    """Comissão por Sub ID de ontem e anteontem (o relatório da Shopee sai no dia seguinte)."""
    camps = supa.select("campanhas", {"sub_id": "neq.", "status": "neq.erro"})
    por_user = {}
    for c in camps:
        por_user.setdefault(c["user_id"], []).append(c)
    hoje = _today()
    for uid, lista in por_user.items():
        for back in (1, 2):
            dia = (hoje - timedelta(days=back)).isoformat()
            try:
                linhas = supa.shopee_conversions(uid, dia)
            except Exception:  # noqa: BLE001 - sem credenciais da Shopee ou API fora
                log.exception("comissões indisponíveis")
                break
            soma = {}
            for row in linhas or []:
                sub = (row.get("sub_id") or "").strip().lower()
                s = soma.setdefault(sub, {"comissao": 0.0, "pedidos": 0})
                s["comissao"] += _num(row.get("comissao"))
                s["pedidos"] += int(_num(row.get("pedidos")))
            for c in lista:
                if dia < (c.get("ativada_em") or "9999"):
                    continue
                s = soma.get(c["sub_id"].strip().lower(), {"comissao": 0.0, "pedidos": 0})
                _salvar_metrica(c, dia, comissao=round(s["comissao"], 2), pedidos=s["pedidos"])


# ------------------------------------------------------------------ avaliação
def avaliar():
    hoje = _today()
    ontem = (hoje - timedelta(days=1)).isoformat()
    for c in supa.select("campanhas", {"ativada_em": "neq.", "status": "neq.encerrada"}):
        if MANTIDA in (c.get("recomendacao") or ""):
            continue
        inicio = c["ativada_em"][:10]
        dias = (hoje - datetime.strptime(inicio, "%Y-%m-%d").date()).days  # dias fechados
        if dias < 1:
            rec = "Primeiro dia rodando. O resultado aparece amanhã, quando a Shopee fecha o relatório de hoje."
        else:
            ms = [m for m in supa.select("campanha_metricas", {"campanha_id": f"eq.{c['id']}"})
                  if inicio <= m["data"] <= ontem]
            gasto = sum(_num(m.get("gasto")) for m in ms)
            comissao = sum(_num(m.get("comissao")) for m in ms)
            saldo = comissao - gasto
            base = f"{dias} dia(s) fechado(s): gasto R$ {gasto:.2f}, comissão R$ {comissao:.2f}, " \
                   f"{'lucro' if saldo >= 0 else 'prejuízo'} R$ {abs(saldo):.2f}."
            if saldo >= 0:
                rec = base + " Está se pagando: manter."
            elif dias < 3:
                rec = base + " Atenção: ainda em teste (3 dias). Só alerta por enquanto."
            else:
                ja_pausou = AUTO in (c.get("recomendacao") or "")
                if c.get("status") == "ativa" and not c.get("acao") and not ja_pausou:
                    _set(c["id"], acao="pausar_auto")  # só vale às 23:59 (pausar_no_fim_do_dia)
                    log.info("campanha %s marcada para pausar às 23:59", c["id"])
                rec = base + f" Teste de 3 dias concluído sem se pagar: {AUTO}."
        if rec != (c.get("recomendacao") or ""):
            _set(c["id"], recomendacao=rec, dia_teste=max(0, dias))


def pausar_no_fim_do_dia():
    """Pausas automáticas só acontecem às 23:59 (horário de Brasília), regra do Felipe."""
    agora = datetime.now(TZ)
    # janela 23:59–00:05: cobre o caso de o robô estar ocupado editando um vídeo às 23:59
    if not ((agora.hour, agora.minute) >= (23, 59) or (agora.hour == 0 and agora.minute < 5)):
        return
    for c in supa.select("campanhas", {"acao": "eq.pausar_auto"}):
        camp = c.get("platform_campaign_id") or ""
        try:
            if MANTIDA in (c.get("recomendacao") or "") or c.get("status") != "ativa":
                _set(c["id"], acao="")
                continue
            if not camp:
                raise RuntimeError("A campanha ainda não foi criada no Meta.")
            zernio.set_campaign_status(camp, "paused")
            _set(c["id"], acao="", status="pausada", error_message="")
            log.info("campanha %s pausada às 23:59", c["id"])
        except Exception as e:  # noqa: BLE001
            log.exception("falha na pausa automática")
            _set(c["id"], acao="", error_message=f"Não consegui pausar: {str(e)[:300]}")


def ciclo():
    criar_pedidas()
    aplicar_acoes()
    ligar_sub_ids()
    puxar_gasto()
    puxar_comissoes()
    avaliar()
