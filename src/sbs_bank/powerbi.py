"""Export the Power BI star schema (powerbi/data/*.csv).

SQL (sql/06_powerbi_export.sql) aggregates the facts; Python adds French
labels, the RFM segment and the calendar, then writes CSV files that the
Power BI project (powerbi/SBS_Bank.pbip) imports.

Why CSV files rather than a live MySQL connection? The report can be opened
by anyone who clones the repository, without MySQL or an ODBC/.NET driver.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .analysis import SEGMENT_ORDER, run_query, segment_rfm
from .config import PROJECT_ROOT

POWERBI_DIR = PROJECT_ROOT / "powerbi"
DATA_DIR = POWERBI_DIR / "data"
PARAMETER_FILE = POWERBI_DIR / "SBS_Bank.SemanticModel" / "definition" / "expressions.tmdl"

CHANNELS = [
    ("MOBILE", "Mobile"),
    ("WEB", "Site web"),
    ("PARTNER", "Partenaires"),
    ("UNKNOWN", "Non identifié"),
]
STATUSES = {"ACTIVE": "Actif", "DORMANT": "Dormant", "NEVER_FUNDED": "Jamais alimenté", "CLOSED": "Clôturé"}
EVENTS = {
    "CREATE_ACCOUNT": "Ouverture de compte", "LOGIN": "Connexion", "BALANCE_INQUIRY": "Consultation du solde",
    "DEPOSIT": "Dépôt", "WITHDRAWAL": "Retrait", "TRANSFER": "Virement", "CARD_PAYMENT": "Paiement carte",
    "CLOSE_ACCOUNT": "Clôture de compte",
}
REASONS = {
    "NONE": "Aucun", "INSUFFICIENT_FUNDS": "solde insuffisant", "WRONG_PIN": "code PIN erroné",
    "INVALID_CARD_NUMBER": "numéro de carte invalide", "ACCOUNT_CLOSED": "bénéficiaire clôturé",
    "SAME_ACCOUNT": "virement vers soi-même", "UNKNOWN_CARD": "carte inconnue", "INVALID_AMOUNT": "montant invalide",
}
MONTHS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
NOT_SEGMENTED = "Hors segmentation"


def _write(frame: pd.DataFrame, name: str) -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(DATA_DIR / f"{name}.csv", index=False, encoding="utf-8", lineterminator="\n")
    return len(frame)


def build_calendar(months: pd.Series) -> pd.DataFrame:
    dates = pd.date_range(months.min(), months.max(), freq="MS")
    return pd.DataFrame({
        "Mois": dates.date,
        "Libellé mois": [f"{MONTHS_FR[d.month - 1]} {d.year}" for d in dates],
        "Année": dates.year,
        "Numéro mois": dates.month,
        "Trimestre": [f"T{(d.month - 1) // 3 + 1} {d.year}" for d in dates],
        "Ordre mois": dates.year * 100 + dates.month,
    })


def build_accounts() -> pd.DataFrame:
    accounts = run_query("pbi_dim_account")
    segments = segment_rfm(run_query("q12_rfm_base"))[["account_id", "segment"]]
    accounts = accounts.merge(segments, on="account_id", how="left")
    accounts["segment"] = accounts["segment"].fillna(NOT_SEGMENTED)
    segment_rank = {name: rank for rank, name in enumerate([*SEGMENT_ORDER, NOT_SEGMENTED], start=1)}
    status_rank = {label: rank for rank, label in enumerate(STATUSES.values(), start=1)}
    status = accounts["lifecycle_status"].map(STATUSES)
    return pd.DataFrame({
        "Id compte": accounts["account_id"],
        "Id client": accounts["customer_id"],
        "Code canal": accounts["signup_channel"],
        "Tranche âge": accounts["age_band"],
        "Ville": accounts["city"],
        "Mois ouverture": accounts["cohort_month"],
        "Date ouverture": accounts["opened_date"],
        "Statut": status,
        "Ordre statut": status.map(status_rank),
        "Segment RFM": accounts["segment"],
        "Ordre segment": accounts["segment"].map(segment_rank),
        "Jours avant premier dépôt": accounts["days_to_first_deposit"].astype("Int64"),
        "Alimenté sous 7 jours": accounts["funded_within_7_days"].astype(int),
        "Alimenté sous 30 jours": accounts["funded_within_30_days"].astype(int),
        "Éligible activation": accounts["activation_eligible"].astype(int),
        "Jours depuis dernière activité": accounts["days_since_last_activity"].astype("Int64"),
        "Solde fin de période": accounts["balance_at_period_end"],
        "Dépenses carte": accounts["card_spend"],
        "Paiements carte": accounts["card_payments"].astype(int),
        "Paiements refusés": accounts["declined_card_payments"].astype(int),
    })


def build_operations() -> pd.DataFrame:
    ops = run_query("pbi_fact_operations")
    event = ops["event_type"].map(EVENTS)
    reason = ops["failure_reason"].map(REASONS)
    failed = ops["status"] == "FAILED"
    return pd.DataFrame({
        "Mois": ops["month_start"],
        "Code canal": ops["signup_channel"],
        "Type opération": event,
        "Résultat": failed.map({True: "Échec", False: "Réussite"}),
        "Motif échec": reason,
        "Type et motif": (event + " : " + reason).where(failed, event),
        "Tentatives": ops["attempts"].astype(int),
        "Montant demandé": ops["amount_requested"],
    })


def export(update_parameter: bool = True) -> dict[str, int]:
    counts = {}
    accounts = build_accounts()
    activity = run_query("pbi_fact_account_month")
    counts["dim_compte"] = _write(accounts, "dim_compte")
    counts["dim_mois"] = _write(build_calendar(pd.to_datetime(activity["month_start"])), "dim_mois")
    counts["dim_canal"] = _write(
        pd.DataFrame({"Code canal": [c for c, _ in CHANNELS], "Canal": [label for _, label in CHANNELS],
                      "Ordre canal": range(1, len(CHANNELS) + 1)}),
        "dim_canal",
    )
    counts["fait_activite_mensuelle"] = _write(pd.DataFrame({
        "Id compte": activity["account_id"],
        "Mois": activity["month_start"],
        "Client actif": activity["is_customer_active"].astype(int),
        "Opérations client": activity["customer_operations"].astype(int),
        "Paiements carte": activity["card_payments"].astype(int),
        "Paiements refusés": activity["declined_card_payments"].astype(int),
        "Dépenses carte": activity["card_spend"],
        "Dépôts": activity["deposits"],
    }), "fait_activite_mensuelle")
    counts["fait_operations"] = _write(build_operations(), "fait_operations")

    spend = run_query("pbi_fact_card_spend")
    counts["fait_depenses_carte"] = _write(pd.DataFrame({
        "Mois": spend["month_start"],
        "Code canal": spend["signup_channel"],
        "Catégorie": spend["category"],
        "Type de dépense": spend["is_essential"].astype(bool).map({True: "Essentielle", False: "Non essentielle"}),
        "Paiements": spend["payments"].astype(int),
        "Montant": spend["amount"],
    }), "fait_depenses_carte")

    retention = run_query("pbi_fact_retention")
    counts["fait_retention_cohortes"] = _write(pd.DataFrame({
        "Mois ouverture": retention["cohort_month"],
        "Cohorte": pd.to_datetime(retention["cohort_month"]).dt.strftime("%Y-%m"),
        "Code canal": retention["signup_channel"],
        "Mois depuis ouverture": retention["months_since_opening"].astype(int),
        "Comptes actifs": retention["active_accounts"].astype(int),
        "Taille cohorte": retention["cohort_size"].astype(int),
    }), "fait_retention_cohortes")

    if update_parameter and PARAMETER_FILE.exists():
        set_data_folder_parameter(DATA_DIR)
    return counts


def set_data_folder_parameter(folder: Path) -> None:
    """Point the Power BI `DossierDonnees` parameter to this clone's data folder.

    Power Query needs an absolute path to read local files.
    """
    lines = PARAMETER_FILE.read_text(encoding="utf-8").splitlines()
    value = str(folder.resolve()) + "\\"
    lines = [
        f'expression DossierDonnees = "{value}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'
        if line.startswith("expression DossierDonnees") else line
        for line in lines
    ]
    PARAMETER_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
