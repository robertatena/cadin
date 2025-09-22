# app_cadin.py — CADIN (Federal/Gateway/SERPRO + PMSP PF & PJ via gateway)
import os
import re
from typing import Dict, Any, List, Optional, Tuple

import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="CADIN • Consulta PF e PJ", layout="wide")

APP_TITLE = "📌 Consulta CADIN (PF e PJ)"
APP_CAPTION = (
    "Consulta CADIN com consentimento e credenciais válidas. "
    "Fluxo padrão: Gateway (recomendado) → SERPRO (opcional) → modo demonstração. "
    "Para CADIN Municipal da **Prefeitura de São Paulo (PMSP)**, use o gateway PMSP (PF e PJ)."
)

# =========================================================
# Secrets / Env (configure em Settings → Secrets do Streamlit)
# =========================================================
# Fluxo geral (Federal / outros provedores internos)
GATEWAY_URL = os.getenv("GATEWAY_URL")          # ex.: https://seu-backend.exemplo.app
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")# header X-API-Key para o gateway

# SERPRO direto (opcional; se não tiver, deixe vazio e use gateway)
SERPRO_BASE  = os.getenv("SERPRO_CADIN_BASE")   # ex.: https://apicadin.serpro.gov.br
SERPRO_TOKEN = os.getenv("SERPRO_TOKEN")        # token/bearer

# PMSP municipal (via gateway próprio que resolve captcha/autenticação)
PMSP_GATEWAY_URL = os.getenv("PMSP_GATEWAY_URL")  # ex.: https://seu-gateway-pmsp.exemplo.app
PMSP_API_KEY     = os.getenv("PMSP_API_KEY")

# =========================================================
# Utils
# =========================================================
def only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")

def is_cpf(d: str) -> bool:
    d = only_digits(d); return len(d) == 11

def is_cnpj(d: str) -> bool:
    d = only_digits(d); return len(d) == 14

def label_doc(d: str) -> str:
    return "CPF" if is_cpf(d) else "CNPJ" if is_cnpj(d) else "Documento"

def fmt_doc(d: str) -> str:
    d = only_digits(d)
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return d

# =========================================================
# Providers (clientes HTTP) — TODOS retornam dicionário
# =========================================================
@st.cache_data(ttl=600, show_spinner=False)
def fetch_cadin_via_gateway(document: str) -> Dict[str, Any]:
    """
    Gateway padrão (Federal/geral). Esperado JSON:
    { "documento":"...", "nome":"...", "situacao":"REGULAR|IRREGULAR", "pendencias":[...] }
    """
    if not (GATEWAY_URL and INTERNAL_API_KEY):
        raise RuntimeError("Gateway padrão não configurado")
    url = f"{GATEWAY_URL.rstrip('/')}/cadin/{only_digits(document)}"
    r = requests.get(url, headers={"X-API-Key": INTERNAL_API_KEY}, timeout=40)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=600, show_spinner=False)
def fetch_cadin_via_serpro_direct(document: str) -> Dict[str, Any]:
    """Exemplo de chamada direta ao SERPRO (ajuste ao seu contrato)."""
    if not (SERPRO_BASE and SERPRO_TOKEN):
        raise RuntimeError("SERPRO não configurado")
    url = f"{SERPRO_BASE.rstrip('/')}/cadin/v1/consulta/{only_digits(document)}"
    headers = {"Authorization": f"Bearer {SERPRO_TOKEN}"}
    r = requests.get(url, headers=headers, timeout=40)
    r.raise_for_status()
    return r.json()

# PMSP — PF (CPF + data nasc)
@st.cache_data(ttl=600, show_spinner=False)
def fetch_cadin_pmsp_pf(cpf: str, dtnasc_ddmmaaaa: str) -> Dict[str, Any]:
    """
    Gateway PMSP (PF). Esperado JSON compatível:
    { "cpf":"...", "nome":"...", "situacao":"REGULAR|IRREGULAR", "pendencias":[...] }
    """
    if not (PMSP_GATEWAY_URL and PMSP_API_KEY):
        raise RuntimeError("Gateway PMSP não configurado")
    url = f"{PMSP_GATEWAY_URL.rstrip('/')}/cadin/pmspspf/{only_digits(cpf)}"
    r = requests.get(url, params={"dtnasc": dtnasc_ddmmaaaa}, headers={"X-API-Key": PMSP_API_KEY}, timeout=45)
    r.raise_for_status()
    return r.json()

# PMSP — PJ (CNPJ)
@st.cache_data(ttl=600, show_spinner=False)
def fetch_cadin_pmsp_pj(cnpj: str) -> Dict[str, Any]:
    """
    Gateway PMSP (PJ). Esperado JSON compatível:
    { "cnpj":"...", "razao_social":"...", "situacao":"REGULAR|IRREGULAR", "pendencias":[...] }
    """
    if not (PMSP_GATEWAY_URL and PMSP_API_KEY):
        raise RuntimeError("Gateway PMSP não configurado")
    url = f"{PMSP_GATEWAY_URL.rstrip('/')}/cadin/pmspspj/{only_digits(cnpj)}"
    r = requests.get(url, headers={"X-API-Key": PMSP_API_KEY}, timeout=45)
    r.raise_for_status()
    return r.json()

# =========================================================
# Normalização de payload (deixa tudo com mesma cara)
# =========================================================
def normalize_payload(data: Dict[str, Any], doc: str) -> Dict[str, Any]:
    """
    Devolve: {"documento":..., "nome":..., "situacao":..., "pendencias":[...]}
    Aceita cópias "nome", "razao_social", "cpf", "cnpj", etc.
    """
    out = {}
    out["documento"] = only_digits(data.get("documento") or data.get("cpf") or data.get("cnpj") or doc)
    out["nome"] = data.get("nome") or data.get("razao_social") or data.get("razaoSocial") or "—"
    out["situacao"] = (data.get("situacao") or data.get("status") or "—").upper()
    pend = data.get("pendencias") or data.get("itens") or data.get("debts") or []
    # garante lista de dicts
    if isinstance(pend, dict):
        pend = [pend]
    out["pendencias"] = pend
    # mantém original p/ expander
    out["_raw"] = data
    return out

def demo_payload(document: str) -> Dict[str, Any]:
    """Modo demonstração — NÃO consulta base real."""
    d = only_digits(document)
    is_pf = is_cpf(d); is_irreg = (int(d[-1]) % 2 == 1) if d else False
    nome = "Pessoa Física (demo)" if is_pf else "Empresa Ltda (demo)" if is_cnpj(d) else "Documento (demo)"
    return normalize_payload({
        "documento": d,
        "nome": nome,
        "situacao": "IRREGULAR" if is_irreg else "REGULAR",
        "pendencias": ([] if not is_irreg else [
            {"orgao":"PMSP" if is_pf else "União", "origem":"Tributo", "numero":"000123/2024", "data":"2024-08-12", "valor": 199.9}
        ])
    }, d)

# =========================================================
# Orquestração
# =========================================================
def resolve_general(document: str) -> Tuple[Dict[str, Any], str]:
    """
    Fluxo geral: Gateway → SERPRO → Demo.
    Retorna (payload_normalizado, fonte).
    """
    # 1) Gateway padrão (federal/geral)
    if GATEWAY_URL and INTERNAL_API_KEY:
        try:
            data = fetch_cadin_via_gateway(document)
            return normalize_payload(data, document), "gateway"
        except Exception as e:
            st.warning(f"Gateway falhou: {e}")

    # 2) SERPRO direto (opcional)
    if SERPRO_BASE and SERPRO_TOKEN:
        try:
            data = fetch_cadin_via_serpro_direct(document)
            return normalize_payload(data, document), "serpro"
        except Exception as e:
            st.warning(f"SERPRO falhou: {e}")

    # 3) Demo (sem base real)
    return demo_payload(document), "demo"

def resolve_pmsp(document: str, dtnasc: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Tenta PMSP PF/PJ via gateway.
    Para PF exige dtnasc (dd/mm/aaaa).
    Retorna (payload_normalizado | None, fonte | None)
    """
    if not (PMSP_GATEWAY_URL and PMSP_API_KEY):
        return None, None

    if is_cpf(document):
        if not dtnasc or not re.match(r"^\d{2}/\d{2}/\d{4}$", dtnasc.strip()):
            st.error("Para **PMSP – PF**, informe **data de nascimento** no formato dd/mm/aaaa.")
            return None, None
        try:
            data = fetch_cadin_pmsp_pf(document, dtnasc.strip())
            return normalize_payload(data, document), "pmsp_pf"
        except Exception as e:
            st.warning(f"PMSP PF falhou: {e}")
            return None, None

    if is_cnpj(document):
        try:
            data = fetch_cadin_pmsp_pj(document)
            return normalize_payload(data, document), "pmsp_pj"
        except Exception as e:
            st.warning(f"PMSP PJ falhou: {e}")
            return None, None

    st.error("Documento inválido para PMSP.")
    return None, None

# =========================================================
# UI
# =========================================================
st.title(APP_TITLE)
st.caption(APP_CAPTION)

with st.sidebar:
    st.subheader("⚙️ Configurações")
    if GATEWAY_URL and INTERNAL_API_KEY:
        st.success("Gateway padrão configurado"); st.write(f"**Gateway:** {GATEWAY_URL}")
    else:
        st.info("Sem gateway padrão. Configure **GATEWAY_URL** e **INTERNAL_API_KEY**.")

    if SERPRO_BASE and SERPRO_TOKEN:
        st.success("SERPRO direto configurado")
    else:
        st.info("Sem SERPRO direto. (opcional)")

    if PMSP_GATEWAY_URL and PMSP_API_KEY:
        st.success("Gateway **PMSP** configurado (PF & PJ)")
        pmsp_on = st.checkbox("Usar CADIN Municipal PMSP (PF/PJ)", value=True)
    else:
        st.info("Sem gateway PMSP. Configure **PMSP_GATEWAY_URL** e **PMSP_API_KEY**.")
        pmsp_on = False

    st.markdown("---")
    mode = st.radio("Modos de consulta", ["Consulta única", "Lote (CSV)"], index=0)

def show_result_card(payload: Dict[str, Any], fonte: str):
    doc = payload.get("documento","")
    st.subheader(f"Resultado — {label_doc(doc)} {fmt_doc(doc)}")
    st.write("**Fonte:**", fonte.upper())
    st.write("**Nome/Razão social:**", payload.get("nome","—"))
    situ = (payload.get("situacao") or "—").upper()
    st.write("**Situação:**", "🟥 IRREGULAR" if situ=="IRREGULAR" else "🟩 REGULAR")

    st.markdown("---")
    st.subheader("🔎 Pendências")
    pend = payload.get("pendencias") or []
    if not pend:
        st.success("Sem pendências retornadas.")
    else:
        df = pd.DataFrame(pend)
        if "valor" in df.columns:
            with pd.option_context("mode.use_inf_as_na", True):
                df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
        st.dataframe(df, use_container_width=True)

    with st.expander("JSON bruto / depuração"):
        st.json(payload.get("_raw", payload))

def render_single(pmsp_on: bool):
    with st.form("form_single"):
        doc = st.text_input("CPF ou CNPJ", placeholder="000.000.000-00 ou 00.000.000/0001-00")
        dtnasc = st.text_input("Data de nascimento (PMSP – PF)", placeholder="dd/mm/aaaa") if pmsp_on else ""
        consent = st.checkbox("Tenho **consentimento/base legal** para esta consulta (LGPD).", value=False)
        submitted = st.form_submit_button("Consultar")

    if not submitted:
        return
    clean = only_digits(doc)
    if len(clean) not in (11, 14):
        st.error("Informe um CPF (11 dígitos) ou CNPJ (14 dígitos)."); return
    if not consent:
        st.error("Marque o consentimento/base legal (LGPD)."); return

    with st.spinner("Consultando..."):
        payload = None; fonte = None
        # 1) PMSP se habilitado
        if pmsp_on:
            payload, fonte = resolve_pmsp(clean, dtnasc)
        # 2) Se PMSP não usado/fracassou → fluxo geral
        if payload is None:
            payload, fonte = resolve_general(clean)

    show_result_card(payload, fonte)

def render_batch(pmsp_on: bool):
    st.write("Envie um **CSV** com coluna `documento` (CPF/CNPJ). "
             "Se **PMSP** estiver ativo, inclua **`dtnasc`** (dd/mm/aaaa) para **CPFs**.")
    file = st.file_uploader("CSV", type=["csv"])
    consent = st.checkbox("Tenho **consentimento/base legal** para todos os documentos (LGPD).", value=False)
    if not file:
        return
    if not consent:
        st.error("Para processar em lote, marque o consentimento/base legal."); return

    try:
        df = pd.read_csv(file, dtype=str)
    except Exception as e:
        st.error(f"Erro ao ler CSV: {e}"); return
    if "documento" not in df.columns:
        st.error("CSV deve conter a coluna `documento`."); return

    docs = [only_digits(x) for x in df["documento"].fillna("").astype(str).tolist()]
    docs = [d for d in docs if len(d) in (11, 14)]
    if not docs:
        st.error("Nenhum CPF/CNPJ válido encontrado."); return

    out_rows: List[Dict[str, Any]] = []
    prog = st.progress(0.0)
    total = len(docs)

    for i, d in enumerate(docs, start=1):
        payload=None; fonte=None
        # PMSP quando ativo
        if pmsp_on:
            dtnasc = ""
            if is_cpf(d) and "dtnasc" in df.columns:
                try:
                    dtnasc = str(df.loc[df.index[i-1], "dtnasc"] or "").strip()
                except Exception:
                    dtnasc = ""
            p, f = resolve_pmsp(d, dtnasc)
            if p is not None:
                payload, fonte = p, f
        # Se PMSP não usado/fracassou
        if payload is None:
            payload, fonte = resolve_general(d)

        pend = payload.get("pendencias") or []
        out_rows.append({
            "documento": fmt_doc(d),
            "tipo": label_doc(d),
            "nome": payload.get("nome",""),
            "situacao": payload.get("situacao",""),
            "qtd_pendencias": len(pend),
            "fonte": fonte
        })
        prog.progress(i/total)

    out = pd.DataFrame(out_rows)
    st.subheader("📊 Resumo do lote")
    st.dataframe(out, use_container_width=True)
    st.download_button("Baixar CSV", out.to_csv(index=False).encode("utf-8-sig"),
                       file_name="resultado_cadin.csv", mime="text/csv")

# ================= Main =================
st.title(APP_TITLE)
st.caption(APP_CAPTION)

with st.sidebar:
    st.markdown("---")

if mode == "Consulta única":
    render_single(pmsp_on)
else:
    render_batch(pmsp_on)

st.markdown("---")
st.caption(
    "LGPD: Este app pressupõe **consentimento** do titular/base legal e finalidade legítima. "
    "O CADIN (Federal, Estadual e Municipal/PMSP) é base restrita; acesse apenas com **credenciais oficiais** "
    "e dentro do seu contrato. Sem credenciais, o app opera em **modo demonstração** (sem consulta real)."
)
