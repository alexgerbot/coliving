# app_coliving_simulation.py

from dataclasses import dataclass
from typing import Dict, List

import streamlit as st
import pandas as pd


# ----------------------------
# Modèles de données
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

        On utilise les 'share_*' comme pondérations.
        """
        total_share = self.share_nightly + self.share_weekly + self.share_monthly
        if total_share <= 0:
            return 0.0

        # Normalisation des parts
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
    days: int  # nombre de jours dans la saison
    occupancy: Dict[str, float]              # room_type_name -> taux d’occupation (0–1)
    pricing: Dict[str, SeasonPricing]        # room_type_name -> SeasonPricing


# ----------------------------
# Fonction de simulation
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
                # Pas de prix défini pour ce type dans cette saison
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
# UI Streamlit
# ----------------------------

def main():
    st.title("📊 Simulation de revenus – Coliving à la montagne")

    st.markdown(
        """
        Cette page te permet de simuler les revenus d’un projet de coliving :
        - nombre de chambres par type  
        - prix par saison (nuit / semaine / mois)  
        - taux de remplissage  
        - mix nuit / semaine / mois  

        Les valeurs par défaut correspondent au scénario que nous avons défini ensemble.
        """
    )

    st.sidebar.header("⚙️ Paramètres généraux")

    # ---- Types de chambres (avec valeurs par défaut) ----
    st.sidebar.subheader("Types de chambres")

    default_room_types = {
        "chambre_premium": 6,
        "chambre_simple": 5,
        "dortoir": 2,
        "studio": 2,
    }

    room_types: Dict[str, RoomType] = {}
    for rt_name, default_count in default_room_types.items():
        count = st.sidebar.number_input(
            f"Nombre de {rt_name}",
            min_value=0,
            value=default_count,
            step=1,
        )
        room_types[rt_name] = RoomType(name=rt_name, count=count)

    # ---- Définition des saisons et valeurs par défaut ----
    st.header("📅 Paramètres par saison")

    # Valeurs par défaut (identiques à ton script précédent)
    default_seasons = {
        "Haute saison hiver": {
            "days": 90,
            "occupancy": {
                "chambre_premium": 0.85,
                "chambre_simple": 0.80,
                "dortoir": 0.90,
                "studio": 0.85,
            },
            "pricing": {
                "chambre_premium": (150, 950, 3200, 0.6, 0.3, 0.1),
                "chambre_simple": (110, 700, 2400, 0.7, 0.2, 0.1),
                "dortoir": (38, 230, 0, 0.9, 0.1, 0.0),
                "studio": (170, 1100, 3800, 0.4, 0.4, 0.2),
            },
        },
        "Saison été": {
            "days": 90,
            "occupancy": {
                "chambre_premium": 0.75,
                "chambre_simple": 0.65,
                "dortoir": 0.70,
                "studio": 0.80,
            },
            "pricing": {
                "chambre_premium": (130, 820, 2800, 0.5, 0.3, 0.2),
                "chambre_simple": (95, 610, 2100, 0.6, 0.25, 0.15),
                "dortoir": (32, 195, 0, 0.9, 0.1, 0.0),
                "studio": (150, 950, 3400, 0.3, 0.4, 0.3),
            },
        },
        "Basse saison": {
            "days": 185,
            "occupancy": {
                "chambre_premium": 0.45,
                "chambre_simple": 0.40,
                "dortoir": 0.35,
                "studio": 0.60,
            },
            "pricing": {
                "chambre_premium": (100, 650, 2300, 0.3, 0.3, 0.4),
                "chambre_simple": (80, 520, 1900, 0.3, 0.3, 0.4),
                "dortoir": (26, 160, 0, 0.85, 0.15, 0.0),
                "studio": (120, 780, 2600, 0.2, 0.3, 0.5),
            },
        },
    }

    seasons: List[Season] = []

    # On propose un onglet par saison
    tabs = st.tabs(list(default_seasons.keys()))

    for tab, (season_name, season_data) in zip(tabs, default_seasons.items()):
        with tab:
            st.subheader(f"Saison : {season_name}")

            days = st.number_input(
                f"Nombre de jours pour {season_name}",
                min_value=1,
                max_value=366,
                value=season_data["days"],
                step=1,
                key=f"{season_name}_days",
            )

            st.markdown("### Taux d’occupation et prix par type de chambre")

            occupancy = {}
            pricing: Dict[str, SeasonPricing] = {}

            for rt_name in default_room_types.keys():
                col1, col2 = st.columns([1, 3])
                with col1:
                    occ_default = season_data["occupancy"].get(rt_name, 0.0)
                    occ_rate = st.slider(
                        f"Taux d’occupation {rt_name}",
                        min_value=0.0,
                        max_value=1.0,
                        value=float(occ_default),
                        step=0.05,
                        key=f"{season_name}_{rt_name}_occ",
                    )
                    occupancy[rt_name] = occ_rate

                with col2:
                    price_defaults = season_data["pricing"].get(
                        rt_name,
                        (0.0, 0.0, 0.0, 1/3, 1/3, 1/3),
                    )
                    p_night, p_week, p_month, s_n, s_w, s_m = price_defaults

                    st.markdown(f"**{rt_name} – Prix & mix des séjours**")

                    c1, c2, c3 = st.columns(3)
                    with c1:
                        price_per_night = st.number_input(
                            "Prix/nuit (CHF)",
                            min_value=0.0,
                            value=float(p_night),
                            step=5.0,
                            key=f"{season_name}_{rt_name}_pn",
                        )
                    with c2:
                        price_per_week = st.number_input(
                            "Prix/semaine (CHF)",
                            min_value=0.0,
                            value=float(p_week),
                            step=10.0,
                            key=f"{season_name}_{rt_name}_pw",
                        )
                    with c3:
                        price_per_month = st.number_input(
                            "Prix/mois (CHF)",
                            min_value=0.0,
                            value=float(p_month),
                            step=50.0,
                            key=f"{season_name}_{rt_name}_pm",
                        )

                    c4, c5, c6 = st.columns(3)
                    with c4:
                        share_nightly = st.number_input(
                            "Part séjours à la nuit",
                            min_value=0.0,
                            max_value=1.0,
                            value=float(s_n),
                            step=0.05,
                            key=f"{season_name}_{rt_name}_sn",
                        )
                    with c5:
                        share_weekly = st.number_input(
                            "Part séjours à la semaine",
                            min_value=0.0,
                            max_value=1.0,
                            value=float(s_w),
                            step=0.05,
                            key=f"{season_name}_{rt_name}_sw",
                        )
                    with c6:
                        share_monthly = st.number_input(
                            "Part séjours au mois",
                            min_value=0.0,
                            max_value=1.0,
                            value=float(s_m),
                            step=0.05,
                            key=f"{season_name}_{rt_name}_sm",
                        )

                    pricing[rt_name] = SeasonPricing(
                        price_per_night=price_per_night,
                        price_per_week=price_per_week,
                        price_per_month=price_per_month,
                        share_nightly=share_nightly,
                        share_weekly=share_weekly,
                        share_monthly=share_monthly,
                    )

            seasons.append(
                Season(
                    name=season_name,
                    days=days,
                    occupancy=occupancy,
                    pricing=pricing,
                )
            )

    # ---- Lancer la simulation ----
    if st.button("🚀 Lancer la simulation"):
        results = simulate_annual_revenue(room_types, seasons)

        st.header("📈 Résultats de la simulation")

        st.subheader("Vue globale")
        st.metric("Revenu annuel total (CHF)", f"{results['total_revenue']:.0f}")

        # Détail par saison / type de chambre dans un DataFrame pour analyse
        rows = []
        for season_name, data in results["per_season"].items():
            for rt_name, rdata in data["by_room_type"].items():
                rows.append({
                    "Saison": season_name,
                    "Type": rt_name,
                    "Revenu (CHF)": rdata["revenue"],
                    "Taux occupation": rdata["occupancy_rate"],
                    "Nuits occupées": rdata["occupied_nights"],
                    "Prix nuit équiv. (CHF)": rdata["equivalent_nightly_rate"],
                })

        df = pd.DataFrame(rows)
        if not df.empty:
            st.subheader("Détail par saison et par type de chambre")
            st.dataframe(
                df.style.format({
                    "Revenu (CHF)": "{:,.0f}",
                    "Taux occupation": "{:.0%}",
                    "Nuits occupées": "{:,.0f}",
                    "Prix nuit équiv. (CHF)": "{:,.1f}",
                })
            )

            st.subheader("Revenu par saison (tous types confondus)")
            df_season = df.groupby("Saison")["Revenu (CHF)"].sum().reset_index()
            st.bar_chart(
                df_season.set_index("Saison")["Revenu (CHF)"]
            )

        else:
            st.info("Aucun résultat à afficher : vérifie que tu as au moins une chambre et des prix > 0.")


if __name__ == "__main__":
    main()
