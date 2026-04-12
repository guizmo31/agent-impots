"""
Moteur de calcul fiscal français.
Barème 2025 sur revenus 2024.
"""


# Barème progressif de l'impôt sur le revenu 2025 (revenus 2024)
BAREME_IR_2025 = [
    (11497, 0.00),    # Jusqu'à 11 497 € : 0%
    (29315, 0.11),    # De 11 497 € à 29 315 € : 11%
    (83823, 0.30),    # De 29 315 € à 83 823 € : 30%
    (180294, 0.41),   # De 83 823 € à 180 294 € : 41%
    (float("inf"), 0.45),  # Au-delà de 180 294 € : 45%
]

# Plafond du quotient familial par demi-part supplémentaire
PLAFOND_QF_DEMI_PART = 1759  # 2025

# Abattement forfaitaire de 10% sur salaires
ABATTEMENT_10_PERCENT_MIN = 495
ABATTEMENT_10_PERCENT_MAX = 14171

# Décote
DECOTE_SEUIL_CELIBATAIRE = 1929
DECOTE_SEUIL_COUPLE = 3191


class FiscalEngine:
    """Moteur de calcul de l'impôt sur le revenu."""

    def compute_from_documents(self, documents: list[dict], profile: dict) -> dict:
        """Calcul fiscal de base à partir des documents parsés et du profil."""
        # Extraire les montants des salaires depuis les documents
        salaires = self._extract_salaires(documents)
        parts = self._determine_parts(profile)
        situation = self._determine_situation(profile)

        # Revenu brut global
        revenu_brut = sum(salaires.values())

        # Abattement 10%
        abattement = max(
            ABATTEMENT_10_PERCENT_MIN,
            min(revenu_brut * 0.10, ABATTEMENT_10_PERCENT_MAX),
        )
        revenu_net_imposable = max(0, revenu_brut - abattement)

        # Calcul de l'impôt avec quotient familial
        impot_brut = self._calcul_bareme(revenu_net_imposable, parts)

        # Décote
        decote = self._calcul_decote(impot_brut, situation == "couple")

        impot_net = max(0, impot_brut - decote)

        # Cases à remplir
        cases = []
        for label, montant in salaires.items():
            case_num = "1AJ" if "déclarant 1" in label.lower() or len(salaires) == 1 else "1BJ"
            cases.append({
                "case": case_num,
                "libelle": f"Traitements et salaires - {label}",
                "montant": round(montant, 2),
                "justification": f"Cumul net imposable figurant sur les bulletins de paie ({label})",
                "source": "Bulletins de paie",
            })

        return {
            "situation": {
                "parts": parts,
                "situation_familiale": situation,
            },
            "cases": cases,
            "calcul_impot": {
                "revenu_brut_global": round(revenu_brut, 2),
                "abattement_10_pct": round(abattement, 2),
                "revenu_net_imposable": round(revenu_net_imposable, 2),
                "nombre_parts": parts,
                "quotient_familial": round(revenu_net_imposable / parts, 2) if parts else 0,
                "impot_brut": round(impot_brut, 2),
                "decote": round(decote, 2),
                "reductions": [],
                "credits": [],
                "impot_net": round(impot_net, 2),
                "prelev_source_deja_paye": 0,
                "solde": round(impot_net, 2),
                "detail_bareme": self._detail_bareme(revenu_net_imposable, parts),
            },
            "remarques": [
                "Ce calcul est une estimation basée sur les documents fournis.",
                "Le prélèvement à la source déjà payé n'a pas pu être déterminé automatiquement — vérifiez vos bulletins de paie.",
                "Les revenus fonciers, mobiliers et autres revenus complémentaires n'ont pas été détectés automatiquement.",
                "Consultez un professionnel pour valider votre déclaration.",
            ],
        }

    def _calcul_bareme(self, revenu_net: float, parts: float) -> float:
        """Calcule l'impôt brut selon le barème progressif avec quotient familial."""
        quotient = revenu_net / parts if parts else revenu_net
        impot_par_part = 0.0
        prev_limit = 0

        for limit, rate in BAREME_IR_2025:
            if quotient <= limit:
                impot_par_part += (quotient - prev_limit) * rate
                break
            else:
                impot_par_part += (limit - prev_limit) * rate
            prev_limit = limit

        return impot_par_part * parts

    def _calcul_decote(self, impot_brut: float, couple: bool) -> float:
        """Calcule la décote."""
        seuil = DECOTE_SEUIL_COUPLE if couple else DECOTE_SEUIL_CELIBATAIRE
        if impot_brut >= seuil:
            return 0
        decote = seuil - impot_brut * 0.4525
        return max(0, decote)

    def _detail_bareme(self, revenu_net: float, parts: float) -> str:
        """Génère le détail du calcul par tranche."""
        quotient = revenu_net / parts if parts else revenu_net
        details = []
        prev_limit = 0

        for limit, rate in BAREME_IR_2025:
            if quotient <= prev_limit:
                break
            tranche_max = min(quotient, limit)
            montant_tranche = tranche_max - prev_limit
            impot_tranche = montant_tranche * rate

            if montant_tranche > 0:
                pct = int(rate * 100)
                details.append(
                    f"De {prev_limit:,.0f}€ à {tranche_max:,.0f}€ : "
                    f"{montant_tranche:,.0f}€ × {pct}% = {impot_tranche:,.0f}€"
                )
            prev_limit = limit

        return " | ".join(details)

    def _extract_salaires(self, documents: list[dict]) -> dict[str, float]:
        """Tente d'extraire les montants de salaires des documents."""
        import re

        salaires = {}
        total = 0.0

        for doc in documents:
            content = doc.get("content", "")
            # Chercher des montants de type "net imposable" ou "cumul imposable"
            patterns = [
                r"(?:net\s+imposable|cumul\s+(?:net\s+)?imposable|net\s+fiscal)[\s:]*(\d[\d\s]*[,\.]\d{2})",
                r"(\d[\d\s]*[,\.]\d{2})\s*(?:net\s+imposable|cumul\s+imposable)",
                r"(?:revenu\s+net\s+imposable|total\s+net\s+imposable)[\s:]*(\d[\d\s]*[,\.]\d{2})",
            ]

            for pattern in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    for match in matches:
                        try:
                            value = float(match.replace(" ", "").replace(",", "."))
                            if value > total:
                                total = value
                        except ValueError:
                            continue

        if total > 0:
            salaires["Déclarant 1"] = total
        else:
            salaires["Déclarant 1"] = 0
            # Ajouter une remarque
        return salaires

    def _determine_parts(self, profile: dict) -> float:
        """Détermine le nombre de parts fiscales."""
        parts = 1.0

        for key, value in profile.items():
            if not key.startswith("q") or not isinstance(value, dict):
                continue

            answer = value.get("answer", "").lower()
            question = value.get("question", "").lower()

            # Situation familiale
            if "situation familiale" in question:
                if any(w in answer for w in ("marié", "marie", "pacsé", "pacse", "pacs")):
                    parts = 2.0
                elif any(w in answer for w in ("veuf", "veuve")):
                    parts = 1.0  # sauf si enfants

            # Enfants
            if "enfant" in question:
                import re
                nb_match = re.search(r"(\d+)", answer)
                if nb_match:
                    nb_enfants = int(nb_match.group(1))
                    if nb_enfants >= 1:
                        parts += 0.5
                    if nb_enfants >= 2:
                        parts += 0.5
                    if nb_enfants >= 3:
                        parts += (nb_enfants - 2) * 1.0

        return parts

    def _determine_situation(self, profile: dict) -> str:
        """Détermine si c'est un couple ou célibataire."""
        for key, value in profile.items():
            if not key.startswith("q") or not isinstance(value, dict):
                continue
            answer = value.get("answer", "").lower()
            question = value.get("question", "").lower()
            if "situation familiale" in question:
                if any(w in answer for w in ("marié", "marie", "pacsé", "pacse", "pacs")):
                    return "couple"
        return "célibataire"
