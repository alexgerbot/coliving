# -*- coding: utf-8 -*-
"""
Spyder Editor

This is a temporary script file.
"""
from dataclasses import dataclass
from typing import Dict, List


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


def print_results(results: Dict) -> None:
    """
    Affiche les résultats de façon lisible dans le terminal.
    """
    print("=== Simulation de revenu annuel ===")
    for season_name, data in results["per_season"].items():
        print(f"\nSaison: {season_name}")
        print(f"  Revenu saison: {data['revenue']:.0f} CHF")
        for rt_name, rdata in data["by_room_type"].items():
            print(
                f"    - {rt_name}: {rdata['revenue']:.0f} CHF "
                f"(taux occ: {rdata['occupancy_rate']*100:.0f}%, "
                f"prix nuit eq.: {rdata['equivalent_nightly_rate']:.1f} CHF)"
            )
    print("\nRevenu annuel total:", f"{results['total_revenue']:.0f}", "CHF")


# ----------------------------
# Exemple d’utilisation
# ----------------------------

if __name__ == "__main__":
    # Tu peux adapter les types de chambres et leur nombre ici
    room_types = {
        "chambre_premium": RoomType(name="chambre_premium", count=6),
        "chambre_simple": RoomType(name="chambre_simple", count=5),
        "dortoir": RoomType(name="dortoir", count=2),
        "studio": RoomType(name="studio", count=2),
    }

    # Haute saison hiver (ex : 90 jours)
    haute_hiver = Season(
        name="Haute saison hiver",
        days=90,
        occupancy={
            "chambre_premium": 0.85,
            "chambre_simple": 0.80,
            "dortoir": 0.90,
            "studio": 0.85,
        },
        pricing={
            "chambre_premium": SeasonPricing(
                price_per_night=150,
                price_per_week=950,
                price_per_month=3200,
                share_nightly=0.6,
                share_weekly=0.3,
                share_monthly=0.1,
            ),
            "chambre_simple": SeasonPricing(
                price_per_night=110,
                price_per_week=700,
                price_per_month=2400,
                share_nightly=0.7,
                share_weekly=0.2,
                share_monthly=0.1,
            ),
            "dortoir": SeasonPricing(
                price_per_night=38,
                price_per_week=230,
                price_per_month=0,
                share_nightly=0.9,
                share_weekly=0.1,
                share_monthly=0.0,
            ),
            "studio": SeasonPricing(
                price_per_night=170,
                price_per_week=1100,
                price_per_month=3800,
                share_nightly=0.4,
                share_weekly=0.4,
                share_monthly=0.2,
            ),
        },
    )

    # Saison été (ex : 90 jours)
    ete = Season(
        name="Saison été",
        days=90,
        occupancy={
            "chambre_premium": 0.75,
            "chambre_simple": 0.65,
            "dortoir": 0.70,
            "studio": 0.80,
        },
        pricing={
            "chambre_premium": SeasonPricing(
                price_per_night=130,
                price_per_week=820,
                price_per_month=2800,
                share_nightly=0.5,
                share_weekly=0.3,
                share_monthly=0.2,
            ),
            "chambre_simple": SeasonPricing(
                price_per_night=95,
                price_per_week=610,
                price_per_month=2100,
                share_nightly=0.6,
                share_weekly=0.25,
                share_monthly=0.15,
            ),
            "dortoir": SeasonPricing(
                price_per_night=32,
                price_per_week=195,
                price_per_month=0,
                share_nightly=0.9,
                share_weekly=0.1,
                share_monthly=0.0,
            ),
            "studio": SeasonPricing(
                price_per_night=150,
                price_per_week=950,
                price_per_month=3400,
                share_nightly=0.3,
                share_weekly=0.4,
                share_monthly=0.3,
            ),
        },
    )

    # Basse saison (reste de l’année)
    basse = Season(
        name="Basse saison",
        days=185,
        occupancy={
            "chambre_premium": 0.45,
            "chambre_simple": 0.40,
            "dortoir": 0.35,
            "studio": 0.60,
        },
        pricing={
            "chambre_premium": SeasonPricing(
                price_per_night=100,
                price_per_week=650,
                price_per_month=2300,
                share_nightly=0.3,
                share_weekly=0.3,
                share_monthly=0.4,
            ),
            "chambre_simple": SeasonPricing(
                price_per_night=80,
                price_per_week=520,
                price_per_month=1900,
                share_nightly=0.3,
                share_weekly=0.3,
                share_monthly=0.4,
            ),
            "dortoir": SeasonPricing(
                price_per_night=26,
                price_per_week=160,
                price_per_month=0,
                share_nightly=0.85,
                share_weekly=0.15,
                share_monthly=0.0,
            ),
            "studio": SeasonPricing(
                price_per_night=120,
                price_per_week=780,
                price_per_month=2600,
                share_nightly=0.2,
                share_weekly=0.3,
                share_monthly=0.5,
            ),
        },
    )

    seasons = [haute_hiver, ete, basse]

    # Lancement de la simulation
    results = simulate_annual_revenue(room_types, seasons)
    print_results(results)
