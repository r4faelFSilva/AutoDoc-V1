"""
Exemplo fictício: leitura de "base" (simulada com pandas), tratamento,
exportação para planilha, envio por e-mail e notificação no Teams em caso de falha.

Nenhum dado ou URL aqui é real — configure variáveis de ambiente só no seu .env local para testes reais.
"""

from __future__ import annotations

import io
import logging
import os
import smtplib
import sys
from email.message import EmailMessage

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# --- Constantes fictícias (projeto / grupo "X" apenas para narrativa do exemplo) ---
NOME_GRUPO_TEAMS_FICTICIO = "Grupo_X_Relatorios_Financeiros"
REMETENTE_FICTICIO = "relatorios@empresa-exemplo-ficticia.local"
DESTINATARIO_FICTICIO = "gestor@empresa-exemplo-ficticia.local"
ASSUNTO_EMAIL = "[TESTE] Planilha tratada — base fictícia"


def ler_base_simulada() -> pd.DataFrame:
    """Simula leitura de uma base (como se viesse de um banco ou arquivo)."""
    dados_ficticios = {
        "id_pedido": [1001, 1002, 1003, 1004, 1005],
        "cliente": [
            "Comércio Aurora Ltda",
            "Indústrias Beta S.A.",
            "Serviços Gama ME",
            "Comércio Aurora Ltda",
            "Tech Delta EIRELI",
        ],
        "categoria": ["varejo", "industria", "servicos", "varejo", "servicos"],
        "valor_bruto": [1500.00, 8900.50, 320.75, 2100.00, 12500.00],
        "data_ref": ["2026-01-05", "2026-01-06", "2026-01-06", "2026-01-07", "2026-01-08"],
    }
    return pd.DataFrame(dados_ficticios)


def tratar_dados(df: pd.DataFrame) -> pd.DataFrame:
    """Regras de negócio fictícias sobre o DataFrame."""
    out = df.copy()
    out["data_ref"] = pd.to_datetime(out["data_ref"])
    out["valor_liquido"] = (out["valor_bruto"] * 0.97).round(2)
    out["categoria"] = out["categoria"].str.upper()
    out = out.sort_values(["data_ref", "id_pedido"]).reset_index(drop=True)
    return out


def dataframe_para_planilha_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="Tratado")
    return buf.getvalue()


def enviar_email_com_anexo(
    corpo_texto: str,
    anexo_nome: str,
    anexo_bytes: bytes,
) -> None:
    """
    Integração típica com SMTP.
    Use variáveis de ambiente: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
    SMTP_FROM, SMTP_TO (todos fictícios no seu teste).
    """
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    mail_from = os.getenv("SMTP_FROM", REMETENTE_FICTICIO).strip()
    mail_to = os.getenv("SMTP_TO", DESTINATARIO_FICTICIO).strip()

    if not host:
        raise RuntimeError(
            "SMTP_HOST não configurado — exemplo intencional para simular falha de envio "
            "e acionar o fluxo de notificação no Teams."
        )

    msg = EmailMessage()
    msg["Subject"] = ASSUNTO_EMAIL
    msg["From"] = mail_from
    msg["To"] = mail_to
    msg.set_content(corpo_texto)
    msg.add_attachment(
        anexo_bytes,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=anexo_nome,
    )

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)

    logger.info("E-mail enviado com sucesso (ambiente configurado).")


def enviar_alerta_teams(mensagem: str) -> None:
    """
    Mensagem para um canal/grupo via Incoming Webhook do Teams (Office 365).
    Defina TEAMS_WEBHOOK_URL no ambiente; se ausente, apenas simula no log.
    """
    url = os.getenv("TEAMS_WEBHOOK_URL", "").strip()
    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"Falha no pipeline — {NOME_GRUPO_TEAMS_FICTICIO}",
        "themeColor": "FF0000",
        "title": "Alerta: falha no envio do relatório",
        "text": mensagem,
    }

    if not url or "00000000-0000-0000-0000-000000000000" in url:
        logger.warning(
            "[SIMULAÇÃO Teams → %s] Webhook não configurado ou URL placeholder. "
            "Mensagem que seria enviada:\n%s",
            NOME_GRUPO_TEAMS_FICTICIO,
            mensagem,
        )
        return

    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()
    logger.info("Alerta enviado ao Teams com sucesso.")


def executar_pipeline() -> int:
    try:
        df_raw = ler_base_simulada()
        logger.info("Base lida (simulada): %s linhas.", len(df_raw))

        df_tratado = tratar_dados(df_raw)
        logger.info("Tratamento concluído.")

        xlsx_bytes = dataframe_para_planilha_bytes(df_tratado)
        corpo = (
            "Segue em anexo a planilha tratada (dados 100%% fictícios para teste de caso).\n\n"
            f"Linhas exportadas: {len(df_tratado)}."
        )

        enviar_email_com_anexo(
            corpo_texto=corpo,
            anexo_nome="relatorio_ficticio_tratado.xlsx",
            anexo_bytes=xlsx_bytes,
        )
        return 0

    except Exception as exc:  # noqa: BLE001 — exemplo didático: qualquer falha dispara Teams
        logger.exception("Falha no pipeline de e-mail.")
        texto_teams = (
            f"**Grupo:** {NOME_GRUPO_TEAMS_FICTICIO}\n\n"
            f"**Erro:** `{type(exc).__name__}`\n\n"
            f"**Detalhe:** {exc}\n\n"
            "_Dados utilizados eram apenas fictícios._"
        )
        try:
            enviar_alerta_teams(texto_teams)
        except Exception as teams_exc:  # noqa: BLE001
            logger.error("Falha também ao notificar Teams: %s", teams_exc)
        return 1


if __name__ == "__main__":
    sys.exit(executar_pipeline())
