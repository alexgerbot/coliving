# app_coliving_simulation.py

from dataclasses import dataclass
from typing import Dict, List
import io

import streamlit as st
import pandas as pd


# ----------------------------
# Modèles de données de base
# ----------------------------

@dataclass
class RoomType:
    name: str
    count: int  # nombre de chambres de ce type


@dataclass
class SeasonPricing:
    """
    Prix par type de séjour + mix (quelle proportion des séjours
    sont à la nuit / à la semaine / au mois).
    """
    price_per_night: float
    price_per_week: float
    price_per_month: float
    share_nightly: float   # entre 0 et 1
    share_weekly: float    # entre 0 et 1
    share_monthly: float   # entre 0 et 1

    def equivalent_nightly_rate(self) -> float:
        """
        Calcule un prix moyen par nuit en mélangeant :
        - les séjours à la nuit
        - les séjours à la semaine (prix / 7)
        - les séjours au mois (prix / 30)
        """
        total_share = self.share_nightly + self.share_weekly + self.share_monthly
        if total_share <= 0:
            return 0.0

        sn = self.share_nightly / total_share
        sw = self.share_weekly / total_share
        sm = self.share_monthly / total_share

        nightly_part = sn * self.price_per_night
        weekly_part = sw * (self.price_per_week / 7.0 if self.price_per_week else 0.0)
        monthly_part = sm * (self.price_per_month / 30.0 if self.price_per_month else 0.0)

        return nightly_part + weekly_part + monthly_part


@dataclass
class Season:
    name: str
    days: int
    occupancy: Dict[str, float]              # room_type_name -> taux d’occupation (0–1)
    pricing: Dict[str, SeasonPricing]        # room_type_name -> SeasonPricing


# ----------------------------
# Simulation revenus
# ----------------------------

def simulate_annual_revenue(
    room_types: Dict[str, RoomType],
    seasons: List[Season],
) -> Dict:
    """
    Calcule le revenu annuel total + détail par saison et par type de chambre.
    """
    results = {"per_season": {}, "total_revenue": 0.0}

    for season in seasons:
        season_revenue = 0.0
        room_breakdown = {}

        for rt_name, room_type in room_types.items():
            occ_rate = season.occupancy.get(rt_name, 0.0)
            pricing = season.pricing.get(rt_name)
            if pricing is None:
                continue

            rate = pricing.equivalent_nightly_rate()
            total_room_nights = room_type.count * season.days
            occupied_nights = total_room_nights * occ_rate
            revenue = occupied_nights * rate

            room_breakdown[rt_name] = {
                "equivalent_nightly_rate": rate,
                "occupancy_rate": occ_rate,
                "total_room_nights": total_room_nights,
                "occupied_nights": occupied_nights,
                "revenue": revenue,
            }
            season_revenue += revenue

        results["per_season"][season.name] = {
            "revenue": season_revenue,
            "by_room_type": room_breakdown,
        }
        results["total_revenue"] += season_revenue

    return results


# ----------------------------
# Finance : IRR & dette
# ----------------------------

def compute_irr(cashflows, tol=1e-6, max_iter=1000):
    """
    IRR simple par bissection.
    cashflows[0] = CF année 0 (négatif en général)
    """
    if all(cf >= 0 for cf in cashflows) or all(cf <= 0 for cf in cashflows):
        return None

    low, high = -0.9, 1.0  # -90% à +100%
    for _ in range(max_iter):
        mid = (low + high) / 2
        npv = sum(cf / ((1 + mid) ** t) for t, cf in enumerate(cashflows))
        if abs(npv) < tol:
            return mid
        if npv > 0:
            low = mid
        else:
            high = mid
    return mid


def build_amortization_schedule(debt_amount, annual_rate, years):
    """
    Renvoie une liste de dicts : année, payment, interest, principal, remaining.
    Annuité constante (prêt amortissable).
    """
    if debt_amount <= 0 or annual_rate < 0 or years <= 0:
        return []

    r = annual_rate
    n = int(years)
    if r == 0:
        annual_payment = debt_amount / n
    else:
        annual_payment = debt_amount * (r / (1 - (1 + r) ** -n))

    schedule = []
    remaining = debt_amount

    for year in range(1, n + 1):
        interest = remaining * r
        principal = annual_payment - interest
        remaining = max(0.0, remaining - principal)
        schedule.append({
            "year": year,
            "payment": annual_payment,
            "interest": interest,
            "principal": principal,
            "remaining": remaining,
        })
    return schedule


# ----------------------------
# Config par défaut
# ----------------------------

def get_default_config():
    """
    Renvoie un dict avec TOUTES les hypothèses par défaut.
    """
    config = {
        "room_types": {
            "chambre_premium": 6,
            "chambre_simple": 5,
            "dortoir": 2,
            "studio": 2,
        },
        "charges": {
            "personnel": 200000.0,
            "energie_chauffage": 60000.0,
            "maintenance": 40000.0,
            "marketing_booking": 15000.0,
            "taxes_assurances": 20000.0,
            "autres_fixes": 20000.0,
            "variable_cost_rate": 0.15,
        },
        "fiscalite_comptable": {
            "tax_rate": 0.20,
            "amortizable_share": 0.80,
            "deprec_years": 25,
        },
        "financement": {
            "total_investment": 4_500_000.0,
            "debt_ratio": 0.60,
            "interest_rate": 0.03,
            "loan_years": 15,
            "horizon_years": 15,
            "growth_rate": 0.01,
            "exit_multiple": 8.0,
            "exit_cost_rate": 0.03,
        },
        "scenarios": {
            "Base":      {"occ_factor": 1.00, "price_factor": 1.00, "cost_factor": 1.00},
            "Optimiste": {"occ_factor": 1.10, "price_factor": 1.05, "cost_factor": 0.95},
            "Pessimiste":{"occ_factor": 0.90, "price_factor": 0.97, "cost_factor": 1.05},
        },
        "seasons": {
            "Haute saison hiver": {
                "days": 90,
                "rooms": {
                    "chambre_premium": {
                        "occupancy_base": 0.85,
                        "price_per_night": 150.0,
                        "price_per_week": 950.0,
                        "price_per_month": 3200.0,
                        "share_nightly": 0.6,
                        "share_weekly": 0.3,
                        "share_monthly": 0.1,
                    },
                    "chambre_simple": {
                        "occupancy_base": 0.80,
                        "price_per_night": 110.0,
                        "price_per_week": 700.0,
                        "price_per_month": 2400.0,
                        "share_nightly": 0.7,
                        "share_weekly": 0.2,
                        "share_monthly": 0.1,
                    },
                    "dortoir": {
                        "occupancy_base": 0.90,
                        "price_per_night": 38.0,
                        "price_per_week": 230.0,
                        "price_per_month": 0.0,
                        "share_nightly": 0.9,
                        "share_weekly": 0.1,
                        "share_monthly": 0.0,
                    },
                    "studio": {
                        "occupancy_base": 0.85,
                        "price_per_night": 170.0,
                        "price_per_week": 1100.0,
                        "price_per_month": 3800.0,
                        "share_nightly": 0.4,
                        "share_weekly": 0.4,
                        "share_monthly": 0.2,
                    },
                },
            },
            "Saison été": {
                "days": 90,
                "rooms": {
                    "chambre_premium": {
                        "occupancy_base": 0.75,
                        "price_per_night": 130.0,
                        "price_per_week": 820.0,
                        "price_per_month": 2800.0,
                        "share_nightly": 0.5,
                        "share_weekly": 0.3,
                        "share_monthly": 0.2,
                    },
                    "chambre_simple": {
                        "occupancy_base": 0.65,
                        "price_per_night": 95.0,
                        "price_per_week": 610.0,
                        "price_per_month": 2100.0,
                        "share_nightly": 0.6,
                        "share_weekly": 0.25,
                        "share_monthly": 0.15,
                    },
                    "dortoir": {
                        "occupancy_base": 0.70,
                        "price_per_night": 32.0,
                        "price_per_week": 195.0,
                        "price_per_month": 0.0,
                        "share_nightly": 0.9,
                        "share_weekly": 0.1,
                        "share_monthly": 0.0,
                    },
                    "studio": {
                        "occupancy_base": 0.80,
                        "price_per_night": 150.0,
                        "price_per_week": 950.0,
                        "price_per_month": 3400.0,
                        "share_nightly": 0.3,
                        "share_weekly": 0.4,
                        "share_monthly": 0.3,
                    },
                },
            },
            "Basse saison": {
                "days": 185,
                "rooms": {
                    "chambre_premium": {
                        "occupancy_base": 0.45,
                        "price_per_night": 100.0,
                        "price_per_week": 650.0,
                        "price_per_month": 2300.0,
                        "share_nightly": 0.3,
                        "share_weekly": 0.3,
                        "share_monthly": 0.4,
                    },
                    "chambre_simple": {
                        "occupancy_base": 0.40,
                        "price_per_night": 80.0,
                        "price_per_week": 520.0,
                        "price_per_month": 1900.0,
                        "share_nightly": 0.3,
                        "share_weekly": 0.3,
                        "share_monthly": 0.4,
                    },
                    "dortoir": {
                        "occupancy_base": 0.35,
                        "price_per_night": 26.0,
                        "price_per_week": 160.0,
                        "price_per_month": 0.0,
                        "share_nightly": 0.85,
                        "share_weekly": 0.15,
                        "share_monthly": 0.0,
                    },
                    "studio": {
                        "occupancy_base": 0.60,
                        "price_per_night": 120.0,
                        "price_per_week": 780.0,
                        "price_per_month": 2600.0,
                        "share_nightly": 0.2,
                        "share_weekly": 0.3,
                        "share_monthly": 0.5,
                    },
                },
            },
        },
    }
    return config


# ----------------------------
# Chargement config depuis Excel
# ----------------------------

def load_config_from_excel(file) -> dict:
    """
    Lit un fichier Excel de config et renvoie un dict 'config'
    de la même structure que get_default_config().
    """
    xls = pd.read_excel(file, sheet_name=None)

    cfg = {}

    # room_types
    rt_df = xls.get("room_types")
    if rt_df is not None:
        cfg["room_types"] = {
            str(row["room_type"]): int(row["count"])
            for _, row in rt_df.iterrows()
        }

    # charges
    ch_df = xls.get("charges")
    if ch_df is not None:
        charges = {}
        for _, row in ch_df.iterrows():
            charges[str(row["name"])] = float(row["value"])
        cfg["charges"] = charges

    # fiscalité
    fisc_df = xls.get("fiscalite_comptable")
    if fisc_df is not None:
        fisc = {}
        for _, row in fisc_df.iterrows():
            fisc[str(row["key"])] = float(row["value"])
        cfg["fiscalite_comptable"] = fisc

    # financement
    fin_df = xls.get("financement")
    if fin_df is not None:
        fin = {}
        for _, row in fin_df.iterrows():
            fin[str(row["key"])] = float(row["value"])
        cfg["financement"] = fin

    # scenarios
    scen_df = xls.get("scenarios")
    if scen_df is not None:
        scen = {}
        for _, row in scen_df.iterrows():
            name = str(row["scenario"])
            scen[name] = {
                "occ_factor": float(row["occ_factor"]),
                "price_factor": float(row["price_factor"]),
                "cost_factor": float(row["cost_factor"]),
            }
        cfg["scenarios"] = scen

    # seasons (jours)
    seasons_df = xls.get("seasons")
    season_days = {}
    if seasons_df is not None:
        for _, row in seasons_df.iterrows():
            season_days[str(row["season"])] = int(row["days"])

    # season_room
    sr_df = xls.get("season_room")
    seasons_struct = {}
    if sr_df is not None:
        for _, row in sr_df.iterrows():
            season = str(row["season"])
            room_type = str(row["room_type"])
            if season not in seasons_struct:
                seasons_struct[season] = {
                    "days": season_days.get(season, 90),
                    "rooms": {}
                }
            seasons_struct[season]["rooms"][room_type] = {
                "occupancy_base": float(row["occupancy_base"]),
                "price_per_night": float(row["price_per_night"]),
                "price_per_week": float(row["price_per_week"]),
                "price_per_month": float(row["price_per_month"]),
                "share_nightly": float(row["share_nightly"]),
                "share_weekly": float(row["share_weekly"]),
                "share_monthly": float(row["share_monthly"]),
            }

    if seasons_struct:
        cfg["seasons"] = seasons_struct

    # Merge avec les defaults
    base_cfg = get_default_config()

    def deep_update(d, u):
        for k, v in u.items():
            if isinstance(v, dict) and k in d and isinstance(d[k], dict):
                deep_update(d[k], v)
            else:
                d[k] = v
        return d

    final_cfg = deep_update(base_cfg, cfg)
    return final_cfg


# ----------------------------
# App Streamlit
# ----------------------------

def main():
    st.title("📊 Coliving à la montagne – Modèle financier complet")

    st.markdown(
        """
        Simulation complète d’un projet de **coliving à la montagne** :  
        revenus, charges, dette, impôts, revente, DSCR, TRI, et export Excel “banque”.
        """
    )

    # --- Config en session ---
    if "config" not in st.session_state:
        st.session_state["config"] = get_default_config()
    config = st.session_state["config"]

    # ---------------- SIDEBAR : Config Excel ----------------
    with st.sidebar.expander("📁 Configuration projet (Excel)", expanded=False):
        # Télécharger un template basé sur la config par défaut
        if st.button("⬇️ Télécharger un template de config", key="download_cfg_template"):
            template_cfg = get_default_config()
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                # room_types
                rt_items = []
                for rt_name, count in template_cfg["room_types"].items():
                    rt_items.append({"room_type": rt_name, "count": count})
                pd.DataFrame(rt_items).to_excel(writer, sheet_name="room_types", index=False)

                # charges
                ch_items = []
                for name, value in template_cfg["charges"].items():
                    ch_items.append({"name": name, "value": value})
                pd.DataFrame(ch_items).to_excel(writer, sheet_name="charges", index=False)

                # fiscalité
                fisc_items = []
                for key, value in template_cfg["fiscalite_comptable"].items():
                    fisc_items.append({"key": key, "value": value})
                pd.DataFrame(fisc_items).to_excel(writer, sheet_name="fiscalite_comptable", index=False)

                # financement
                fin_items = []
                for key, value in template_cfg["financement"].items():
                    fin_items.append({"key": key, "value": value})
                pd.DataFrame(fin_items).to_excel(writer, sheet_name="financement", index=False)

                # scenarios
                scen_items = []
                for sname, sp in template_cfg["scenarios"].items():
                    scen_items.append({
                        "scenario": sname,
                        "occ_factor": sp["occ_factor"],
                        "price_factor": sp["price_factor"],
                        "cost_factor": sp["cost_factor"],
                    })
                pd.DataFrame(scen_items).to_excel(writer, sheet_name="scenarios", index=False)

                # seasons
                seasons_items = []
                season_room_items = []
                for sname, scfg in template_cfg["seasons"].items():
                    seasons_items.append({"season": sname, "days": scfg["days"]})
                    for rt_name, rcfg in scfg["rooms"].items():
                        season_room_items.append({
                            "season": sname,
                            "room_type": rt_name,
                            "occupancy_base": rcfg["occupancy_base"],
                            "price_per_night": rcfg["price_per_night"],
                            "price_per_week": rcfg["price_per_week"],
                            "price_per_month": rcfg["price_per_month"],
                            "share_nightly": rcfg["share_nightly"],
                            "share_weekly": rcfg["share_weekly"],
                            "share_monthly": rcfg["share_monthly"],
                        })
                pd.DataFrame(seasons_items).to_excel(writer, sheet_name="seasons", index=False)
                pd.DataFrame(season_room_items).to_excel(writer, sheet_name="season_room", index=False)

            output.seek(0)
            st.download_button(
                label="💾 Télécharger config_coliving_template.xlsx",
                data=output,
                file_name="config_coliving_template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_cfg_file",
            )

        uploaded = st.file_uploader("Charger une config Excel", type=["xlsx"], key="config_uploader")
        if uploaded is not None:
            try:
                new_cfg = load_config_from_excel(uploaded)
                st.session_state["config"] = new_cfg
                config = new_cfg
                st.success("Config Excel chargée ✅")
            except Exception as e:
                st.error(f"Erreur lors du chargement : {e}")

    # ---------------- SIDEBAR : Types de chambres ----------------
    st.sidebar.header("🏨 Types de chambres")
    default_room_types = config["room_types"]
    room_types: Dict[str, RoomType] = {}

    for rt_name, default_count in default_room_types.items():
        count = st.sidebar.number_input(
            f"Nombre de {rt_name}",
            min_value=0,
            value=int(default_count),
            step=1,
        )
        room_types[rt_name] = RoomType(name=rt_name, count=count)

    # ---------------- SIDEBAR : Charges ----------------
    st.sidebar.header("💰 Charges annuelles (BASE)")
    charges_cfg = config["charges"]

    staff_cost = st.sidebar.number_input(
        "Personnel (CHF/an)",
        min_value=0.0,
        value=float(charges_cfg["personnel"]),
        step=10_000.0,
    )
    energy_cost = st.sidebar.number_input(
        "Énergie / chauffage (CHF/an)",
        min_value=0.0,
        value=float(charges_cfg["energie_chauffage"]),
        step=5_000.0,
    )
    maintenance_cost = st.sidebar.number_input(
        "Maintenance (CHF/an)",
        min_value=0.0,
        value=float(charges_cfg["maintenance"]),
        step=5_000.0,
    )
    marketing_cost = st.sidebar.number_input(
        "Marketing / booking (CHF/an)",
        min_value=0.0,
        value=float(charges_cfg["marketing_booking"]),
        step=1_000.0,
    )
    taxes_cost = st.sidebar.number_input(
        "Taxes / assurances (CHF/an)",
        min_value=0.0,
        value=float(charges_cfg["taxes_assurances"]),
        step=1_000.0,
    )
    other_cost = st.sidebar.number_input(
        "Autres charges fixes (CHF/an)",
        min_value=0.0,
        value=float(charges_cfg["autres_fixes"]),
        step=1_000.0,
    )
    variable_cost_rate = st.sidebar.number_input(
        "Charges variables (% du CA)",
        min_value=0.0,
        max_value=1.0,
        value=float(charges_cfg["variable_cost_rate"]),
        step=0.01,
        help="Ex: 0.15 = 15% du chiffre d'affaires",
    )

    base_fixed_costs = (
        staff_cost
        + energy_cost
        + maintenance_cost
        + marketing_cost
        + taxes_cost
        + other_cost
    )

    # ---------------- SIDEBAR : Impôt & amortissement comptable ----------------
    st.sidebar.header("🧾 Impôt & amortissement comptable")
    fisc_cfg = config["fiscalite_comptable"]

    tax_rate = st.sidebar.number_input(
        "Taux d'impôt sur le résultat (ex: 0.20 = 20%)",
        min_value=0.0,
        max_value=0.6,
        value=float(fisc_cfg["tax_rate"]),
        step=0.01,
    )

    amortizable_share = st.sidebar.number_input(
        "Part de l’investissement amortissable (hors terrain)",
        min_value=0.0,
        max_value=1.0,
        value=float(fisc_cfg["amortizable_share"]),
        step=0.05,
    )

    deprec_years = st.sidebar.number_input(
        "Durée d'amortissement comptable (années)",
        min_value=1,
        max_value=50,
        value=int(fisc_cfg["deprec_years"]),
        step=1,
    )

    # ---------------- SIDEBAR : Financement & revente ----------------
    st.sidebar.header("🏦 Financement & revente")
    fin_cfg = config["financement"]

    total_investment = st.sidebar.number_input(
        "Investissement total (achat + travaux, CHF)",
        min_value=0.0,
        value=float(fin_cfg["total_investment"]),
        step=50_000.0,
    )
    debt_ratio = st.sidebar.number_input(
        "Part de dette (LTV, 0–1)",
        min_value=0.0,
        max_value=1.0,
        value=float(fin_cfg["debt_ratio"]),
        step=0.05,
    )
    interest_rate = st.sidebar.number_input(
        "Taux d'intérêt annuel (ex: 0.03 pour 3%)",
        min_value=0.0,
        max_value=0.2,
        value=float(fin_cfg["interest_rate"]),
        step=0.005,
    )
    loan_years = st.sidebar.number_input(
        "Durée du prêt (années)",
        min_value=1,
        max_value=40,
        value=int(fin_cfg["loan_years"]),
        step=1,
    )
    horizon_years = st.sidebar.number_input(
        "Horizon de projection (années)",
        min_value=1,
        max_value=40,
        value=int(fin_cfg["horizon_years"]),
        step=1,
    )
    growth_rate = st.sidebar.number_input(
        "Croissance annuelle de l'EBITDA (ex: 0.02 pour 2%)",
        min_value=-0.5,
        max_value=0.5,
        value=float(fin_cfg["growth_rate"]),
        step=0.005,
    )
    exit_multiple = st.sidebar.number_input(
        "Multiple de revente (valeur = multiple x EBITDA dernière année)",
        min_value=0.0,
        max_value=50.0,
        value=float(fin_cfg["exit_multiple"]),
        step=0.5,
    )
    exit_cost_rate = st.sidebar.number_input(
        "Frais de transaction à la revente (ex: 0.03 = 3%)",
        min_value=0.0,
        max_value=0.2,
        value=float(fin_cfg["exit_cost_rate"]),
        step=0.01,
    )

    # ---------------- SIDEBAR : Scénarios ----------------
    st.sidebar.header("📉 Scénarios (facteurs)")
    scen_cfg = config["scenarios"]

    scenario_params = {
        "Base": {
            "occ_factor": st.sidebar.number_input(
                "Base: facteur occupation",
                min_value=0.0,
                max_value=2.0,
                value=float(scen_cfg["Base"]["occ_factor"]),
                step=0.05,
            ),
            "price_factor": st.sidebar.number_input(
                "Base: facteur prix",
                min_value=0.0,
                max_value=2.0,
                value=float(scen_cfg["Base"]["price_factor"]),
                step=0.05,
            ),
            "cost_factor": st.sidebar.number_input(
                "Base: facteur charges",
                min_value=0.0,
                max_value=2.0,
                value=float(scen_cfg["Base"]["cost_factor"]),
                step=0.05,
            ),
        },
        "Optimiste": {
            "occ_factor": st.sidebar.number_input(
                "Optimiste: facteur occupation",
                min_value=0.0,
                max_value=2.0,
                value=float(scen_cfg["Optimiste"]["occ_factor"]),
                step=0.05,
            ),
            "price_factor": st.sidebar.number_input(
                "Optimiste: facteur prix",
                min_value=0.0,
                max_value=2.0,
                value=float(scen_cfg["Optimiste"]["price_factor"]),
                step=0.05,
            ),
            "cost_factor": st.sidebar.number_input(
                "Optimiste: facteur charges",
                min_value=0.0,
                max_value=2.0,
                value=float(scen_cfg["Optimiste"]["cost_factor"]),
                step=0.05,
            ),
        },
        "Pessimiste": {
            "occ_factor": st.sidebar.number_input(
                "Pessimiste: facteur occupation",
                min_value=0.0,
                max_value=2.0,
                value=float(scen_cfg["Pessimiste"]["occ_factor"]),
                step=0.05,
            ),
            "price_factor": st.sidebar.number_input(
                "Pessimiste: facteur prix",
                min_value=0.0,
                max_value=2.0,
                value=float(scen_cfg["Pessimiste"]["price_factor"]),
                step=0.05,
            ),
            "cost_factor": st.sidebar.number_input(
                "Pessimiste: facteur charges",
                min_value=0.0,
                max_value=2.0,
                value=float(scen_cfg["Pessimiste"]["cost_factor"]),
                step=0.05,
            ),
        },
    }

    # ---------------- Paramètres par saison (BASE) ----------------
    st.header("📅 Paramètres par saison (BASE)")

    default_seasons_cfg = config["seasons"]
    seasons_base_config = {}

    tabs = st.tabs(list(default_seasons_cfg.keys()))

    for tab, (season_name, season_cfg) in zip(tabs, default_seasons_cfg.items()):
        with tab:
            st.subheader(f"Saison : {season_name}")

            days = st.number_input(
                f"Nombre de jours pour {season_name}",
                min_value=1,
                max_value=366,
                value=int(season_cfg["days"]),
                step=1,
                key=f"{season_name}_days",
            )

            occupancy_base = {}
            pricing_base = {}

            st.markdown("### Taux d’occupation (BASE) et prix (BASE) par type")
            rooms_cfg = season_cfg["rooms"]

            for rt_name in default_room_types.keys():
                room_cfg = rooms_cfg.get(rt_name, {
                    "occupancy_base": 0.0,
                    "price_per_night": 0.0,
                    "price_per_week": 0.0,
                    "price_per_month": 0.0,
                    "share_nightly": 1/3,
                    "share_weekly": 1/3,
                    "share_monthly": 1/3,
                })

                col1, col2 = st.columns([1, 3])

                with col1:
                    occ_base = st.slider(
                        f"Taux d’occupation BASE {rt_name}",
                        min_value=0.0,
                        max_value=1.0,
                        value=float(room_cfg["occupancy_base"]),
                        step=0.05,
                        key=f"{season_name}_{rt_name}_occ_base",
                    )
                    occupancy_base[rt_name] = occ_base

                with col2:
                    st.markdown(f"**{rt_name} – Prix BASE & mix des séjours**")

                    c1, c2, c3 = st.columns(3)
                    with c1:
                        base_pn = st.number_input(
                            "Prix/nuit BASE (CHF)",
                            min_value=0.0,
                            value=float(room_cfg["price_per_night"]),
                            step=5.0,
                            key=f"{season_name}_{rt_name}_pn_base",
                        )
                    with c2:
                        base_pw = st.number_input(
                            "Prix/semaine BASE (CHF)",
                            min_value=0.0,
                            value=float(room_cfg["price_per_week"]),
                            step=10.0,
                            key=f"{season_name}_{rt_name}_pw_base",
                        )
                    with c3:
                        base_pm = st.number_input(
                            "Prix/mois BASE (CHF)",
                            min_value=0.0,
                            value=float(room_cfg["price_per_month"]),
                            step=50.0,
                            key=f"{season_name}_{rt_name}_pm_base",
                        )

                    c4, c5, c6 = st.columns(3)
                    with c4:
                        share_nightly = st.number_input(
                            "Part séjours à la nuit",
                            min_value=0.0,
                            max_value=1.0,
                            value=float(room_cfg["share_nightly"]),
                            step=0.05,
                            key=f"{season_name}_{rt_name}_sn",
                        )
                    with c5:
                        share_weekly = st.number_input(
                            "Part séjours à la semaine",
                            min_value=0.0,
                            max_value=1.0,
                            value=float(room_cfg["share_weekly"]),
                            step=0.05,
                            key=f"{season_name}_{rt_name}_sw",
                        )
                    with c6:
                        share_monthly = st.number_input(
                            "Part séjours au mois",
                            min_value=0.0,
                            max_value=1.0,
                            value=float(room_cfg["share_monthly"]),
                            step=0.05,
                            key=f"{season_name}_{rt_name}_sm",
                        )

                    pricing_base[rt_name] = {
                        "price_per_night": base_pn,
                        "price_per_week": base_pw,
                        "price_per_month": base_pm,
                        "share_nightly": share_nightly,
                        "share_weekly": share_weekly,
                        "share_monthly": share_monthly,
                    }

            seasons_base_config[season_name] = {
                "days": days,
                "occupancy_base": occupancy_base,
                "pricing_base": pricing_base,
            }

    # ---------------- Lancer la simulation ----------------
    if st.button("🚀 Lancer la simulation (3 scénarios + revente + impôt + DSCR)"):
        debt_amount = total_investment * debt_ratio
        equity_amount = total_investment * (1 - debt_ratio)
        amort_schedule = build_amortization_schedule(debt_amount, interest_rate, loan_years)

        amortizable_base = total_investment * amortizable_share
        annual_depreciation = amortizable_base / deprec_years

        scenario_results = {}
        scenario_cashflows = {}
        scenario_dscr = {}

        for scenario_name, params in scenario_params.items():
            occ_factor = params["occ_factor"]
            price_factor = params["price_factor"]
            cost_factor = params["cost_factor"]

            # Construire les saisons pour ce scénario
            seasons: List[Season] = []
            for season_name, cfg in seasons_base_config.items():
                days = cfg["days"]
                occupancy_base = cfg["occupancy_base"]
                pricing_base = cfg["pricing_base"]

                occupancy = {}
                pricing = {}

                for rt_name, occ_base in occupancy_base.items():
                    occ_scen = min(1.0, occ_base * occ_factor)
                    occupancy[rt_name] = occ_scen

                for rt_name, pb in pricing_base.items():
                    price_per_night = pb["price_per_night"] * price_factor
                    price_per_week = pb["price_per_week"] * price_factor
                    price_per_month = pb["price_per_month"] * price_factor
                    pricing[rt_name] = SeasonPricing(
                        price_per_night=price_per_night,
                        price_per_week=price_per_week,
                        price_per_month=price_per_month,
                        share_nightly=pb["share_nightly"],
                        share_weekly=pb["share_weekly"],
                        share_monthly=pb["share_monthly"],
                    )

                seasons.append(
                    Season(
                        name=season_name,
                        days=days,
                        occupancy=occupancy,
                        pricing=pricing,
                    )
                )

            # Revenus année 1
            results = simulate_annual_revenue(room_types, seasons)
            revenue = results["total_revenue"]

            # Charges année 1
            variable_costs_base = revenue * variable_cost_rate
            fixed_costs_effective = base_fixed_costs * cost_factor
            variable_costs_effective = variable_costs_base * cost_factor
            total_costs = fixed_costs_effective + variable_costs_effective
            ebitda_year1 = revenue - total_costs

            # Projection sur horizon_years avec croissance de l'EBITDA
            cashflows = []
            years = list(range(horizon_years + 1))
            dscr_rows = []

            # Année 0 : apport equity
            cashflows.append(-equity_amount)

            for year in range(1, horizon_years + 1):
                # EBITDA année t
                ebitda_t = ebitda_year1 * ((1 + growth_rate) ** (year - 1))

                # Intérêt & principal
                if 1 <= year <= len(amort_schedule):
                    sched = amort_schedule[year - 1]
                    interest_t = sched["interest"]
                    principal_t = sched["principal"]
                    remaining_debt_t = sched["remaining"]
                    debt_service_t = sched["payment"]
                else:
                    interest_t = 0.0
                    principal_t = 0.0
                    remaining_debt_t = amort_schedule[-1]["remaining"] if amort_schedule else 0.0
                    debt_service_t = 0.0

                # Amortissement comptable
                depreciation_t = annual_depreciation

                # EBIT
                ebit_t = ebitda_t - depreciation_t

                # Résultat imposable = max(0, EBIT - intérêts)
                taxable_t = max(0.0, ebit_t - interest_t)
                tax_t = taxable_t * tax_rate

                # Résultat net
                net_income_t = ebit_t - interest_t - tax_t

                # CFADS (approx) = EBITDA - impôt
                cfads_t = ebitda_t - tax_t

                # FCFE = résultat net + amortissement comptable - remboursement de principal
                fcfe_t = net_income_t + depreciation_t - principal_t

                # Revente à l'horizon
                if year == horizon_years:
                    exit_value = ebitda_t * exit_multiple
                    exit_costs = exit_value * exit_cost_rate
                    remaining_debt_for_exit = remaining_debt_t
                    net_sale = exit_value - exit_costs - remaining_debt_for_exit
                    fcfe_t += net_sale

                cashflows.append(fcfe_t)

                # DSCR
                if debt_service_t > 0:
                    dscr_t = cfads_t / debt_service_t
                else:
                    dscr_t = None

                dscr_rows.append({
                    "Année": year,
                    "EBITDA": ebitda_t,
                    "CFADS (approx)": cfads_t,
                    "Debt service": debt_service_t,
                    "DSCR": dscr_t,
                    "Intérêts": interest_t,
                    "Principal": principal_t,
                    "Dette restante": remaining_debt_t,
                })

            irr = compute_irr(cashflows)

            scenario_results[scenario_name] = {
                "results": results,
                "revenue": revenue,
                "fixed_costs_effective": fixed_costs_effective,
                "variable_costs_effective": variable_costs_effective,
                "total_costs": total_costs,
                "ebitda_year1": ebitda_year1,
                "cashflows": cashflows,
                "irr": irr,
                "params": params,
            }

            cf_rows = []
            for t, cf in zip(years, cashflows):
                cf_rows.append({"Année": t, "CF (CHF)": cf})
            scenario_cashflows[scenario_name] = pd.DataFrame(cf_rows)
            scenario_dscr[scenario_name] = pd.DataFrame(dscr_rows)

        # ---------------- Affichage synthèse ----------------
        st.header("📈 Synthèse des scénarios")

        synth_rows = []
        for name, data in scenario_results.items():
            synth_rows.append({
                "Scénario": name,
                "Revenu année 1 (CHF)": data["revenue"],
                "EBITDA année 1 (CHF)": data["ebitda_year1"],
                "Charges totales année 1 (CHF)": data["total_costs"],
                "IRR (TRI) avec revente": data["irr"],
                "Facteur occ": data["params"]["occ_factor"],
                "Facteur prix": data["params"]["price_factor"],
                "Facteur charges": data["params"]["cost_factor"],
            })

        df_synth = pd.DataFrame(synth_rows)

        # conversions safe pour éviter les erreurs de format
        for col in ["Revenu année 1 (CHF)", "EBITDA année 1 (CHF)", "Charges totales année 1 (CHF)"]:
            if col in df_synth.columns:
                df_synth[col] = pd.to_numeric(df_synth[col], errors="coerce")
        if "IRR (TRI) avec revente" in df_synth.columns:
            df_synth["IRR (TRI) avec revente"] = pd.to_numeric(
                df_synth["IRR (TRI) avec revente"], errors="coerce"
            )

        st.dataframe(
            df_synth.style.format({
                "Revenu année 1 (CHF)": "{:,.0f}",
                "EBITDA année 1 (CHF)": "{:,.0f}",
                "Charges totales année 1 (CHF)": "{:,.0f}",
                "IRR (TRI) avec revente": "{:.2%}",
            })
        )

        # ---------------- DSCR ----------------
        st.subheader("🛡️ DSCR par scénario")

        dscr_all = None
        for name, df_d in scenario_dscr.items():
            df_tmp = df_d.copy()
            df_tmp = df_tmp[["Année", "DSCR"]]
            df_tmp = df_tmp.rename(columns={"DSCR": f"DSCR {name}"})
            if dscr_all is None:
                dscr_all = df_tmp
            else:
                dscr_all = dscr_all.merge(df_tmp, on="Année", how="outer")

        if dscr_all is not None:
            numeric_cols = [c for c in dscr_all.columns if c != "Année"]
            for c in numeric_cols:
                dscr_all[c] = pd.to_numeric(dscr_all[c], errors="coerce")
            st.dataframe(
                dscr_all.style.format({c: "{:.2f}" for c in numeric_cols})
            )
            dscr_all_chart = dscr_all.set_index("Année")
            st.line_chart(dscr_all_chart)

        # ---------------- CF ----------------
        st.subheader("💸 Cash-flows annuels par scénario")

        cf_merge = None
        for name, df_cf in scenario_cashflows.items():
            df_tmp = df_cf.copy()
            df_tmp = df_tmp.rename(columns={"CF (CHF)": f"CF {name}"})
            if cf_merge is None:
                cf_merge = df_tmp
            else:
                cf_merge = cf_merge.merge(df_tmp, on="Année", how="outer")

        if cf_merge is not None:
            cf_merge_chart = cf_merge.set_index("Année")
            st.line_chart(cf_merge_chart)

        # ---------------- Export Excel format banque ----------------
        st.subheader("📥 Exporter vers Excel (Assumptions, P&L, Bilan, Ratios, CF, DSCR, Detail)")

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            # Assumptions
            assumptions_rows = [
                ("Investissement total (CHF)", total_investment),
                ("Part dette (LTV)", debt_ratio),
                ("Montant dette (CHF)", debt_amount),
                ("Montant equity (CHF)", equity_amount),
                ("Taux d'intérêt", interest_rate),
                ("Durée du prêt (années)", loan_years),
                ("Horizon projection (années)", horizon_years),
                ("Croissance annuelle EBITDA", growth_rate),
                ("Taux d'impôt", tax_rate),
                ("Part amortissable comptablement", amortizable_share),
                ("Durée amortissement comptable", deprec_years),
                ("Charges fixes BASE (CHF/an)", base_fixed_costs),
                ("Taux charges variables", variable_cost_rate),
                ("Multiple de revente", exit_multiple),
                ("Frais de transaction revente", exit_cost_rate),
            ]
            df_assumptions = pd.DataFrame(assumptions_rows, columns=["Paramètre", "Valeur"])
            df_assumptions.to_excel(writer, sheet_name="Assumptions", index=False)

            scen_rows = []
            for name, p in scenario_params.items():
                scen_rows.append({
                    "Scénario": name,
                    "Facteur occupation": p["occ_factor"],
                    "Facteur prix": p["price_factor"],
                    "Facteur charges": p["cost_factor"],
                })
            df_scen = pd.DataFrame(scen_rows)
            df_scen.to_excel(
                writer, sheet_name="Assumptions", index=False,
                startrow=len(df_assumptions) + 2
            )

            ratios_rows = []

            for name, data in scenario_results.items():
                results = data["results"]
                revenue_year1 = data["revenue"]
                ebitda_year1 = data["ebitda_year1"]
                total_costs_year1 = data["total_costs"]
                irr = data["irr"]

                df_cf = scenario_cashflows[name]
                df_d = scenario_dscr[name].copy()

                # conversions numeric
                for col in ["EBITDA", "CFADS (approx)", "Debt service", "DSCR", "Intérêts", "Principal", "Dette restante"]:
                    if col in df_d.columns:
                        df_d[col] = pd.to_numeric(df_d[col], errors="coerce")

                # P&L simplifié
                margin = ebitda_year1 / revenue_year1 if revenue_year1 > 0 else 0.0
                pnl_rows = []

                for _, row in df_d.iterrows():
                    year = int(row["Année"])
                    ebitda_t = row["EBITDA"]
                    depreciation_t = annual_depreciation
                    ebit_t = ebitda_t - depreciation_t
                    interest_t = row["Intérêts"]
                    taxable_t = max(0.0, ebit_t - interest_t)
                    tax_t = taxable_t * tax_rate
                    net_income_t = ebit_t - interest_t - tax_t

                    if margin > 0:
                        revenue_t = ebitda_t / margin
                    else:
                        revenue_t = 0.0
                    costs_t = revenue_t - ebitda_t

                    pnl_rows.append({
                        "Année": year,
                        "Chiffre d'affaires (CHF)": revenue_t,
                        "Charges expl. (CHF)": costs_t,
                        "EBITDA (CHF)": ebitda_t,
                        "Amortiss. comptable (CHF)": depreciation_t,
                        "EBIT (CHF)": ebit_t,
                        "Intérêts (CHF)": interest_t,
                        "Impôt (CHF)": tax_t,
                        "Résultat net (CHF)": net_income_t,
                    })

                df_pnl = pd.DataFrame(pnl_rows)
                df_pnl.to_excel(writer, sheet_name=f"P&L_{name}", index=False)

                # Bilan simplifié
                bilan_rows = []
                non_depr_part = total_investment * (1 - amortizable_share)

                for _, row in df_d.iterrows():
                    year = int(row["Année"])
                    debt_remain = row["Dette restante"]

                    dep_accum = annual_depreciation * min(year, deprec_years)
                    net_amortizable = max(0.0, amortizable_base - dep_accum)
                    net_ppe = non_depr_part + net_amortizable

                    equity_theo = net_ppe - debt_remain
                    ltv = debt_remain / net_ppe if net_ppe > 0 else None

                    bilan_rows.append({
                        "Année": year,
                        "Immobilisations nettes (CHF)": net_ppe,
                        "Dette bancaire (CHF)": debt_remain,
                        "Equity théorique (CHF)": equity_theo,
                        "LTV (Dette / Actif)": ltv,
                    })

                df_bilan = pd.DataFrame(bilan_rows)
                df_bilan.to_excel(writer, sheet_name=f"Bilan_{name}", index=False)

                # CF & DSCR bruts
                df_cf.to_excel(writer, sheet_name=f"CF_{name}", index=False)
                df_d.to_excel(writer, sheet_name=f"DSCR_{name}", index=False)

                # Détail par saison / type
                rows_detail = []
                for season_name, sdata in results["per_season"].items():
                    for rt_name, rdata in sdata["by_room_type"].items():
                        rows_detail.append({
                            "Scénario": name,
                            "Saison": season_name,
                            "Type": rt_name,
                            "Revenu (CHF)": rdata["revenue"],
                            "Taux occupation": rdata["occupancy_rate"],
                            "Nuits occupées": rdata["occupied_nights"],
                            "Prix nuit équiv. (CHF)": rdata["equivalent_nightly_rate"],
                        })
                if rows_detail:
                    df_detail = pd.DataFrame(rows_detail)
                    df_detail.to_excel(writer, sheet_name=f"Detail_{name}", index=False)

                # Ratios
                min_dscr = df_d["DSCR"].min()
                avg_dscr = df_d["DSCR"].mean()
                ebitda_margin_year1 = ebitda_year1 / revenue_year1 if revenue_year1 > 0 else None
                last_row = df_bilan.iloc[-1]
                final_ltv = last_row["LTV (Dette / Actif)"]

                ratios_rows.append({
                    "Scénario": name,
                    "IRR (TRI) avec revente": irr,
                    "Marge EBITDA année 1": ebitda_margin_year1,
                    "DSCR min": min_dscr,
                    "DSCR moyen": avg_dscr,
                    "LTV initiale": debt_ratio,
                    "LTV finale": final_ltv,
                })

            df_ratios = pd.DataFrame(ratios_rows)
            for col in ["IRR (TRI) avec revente", "Marge EBITDA année 1", "DSCR min", "DSCR moyen", "LTV initiale", "LTV finale"]:
                if col in df_ratios.columns:
                    df_ratios[col] = pd.to_numeric(df_ratios[col], errors="coerce")

            df_ratios.to_excel(writer, sheet_name="Ratios", index=False)

        output.seek(0)
        st.download_button(
            label="📥 Télécharger coliving_modele_bancaire.xlsx",
            data=output,
            file_name="coliving_modele_bancaire.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


if __name__ == "__main__":
    main()
