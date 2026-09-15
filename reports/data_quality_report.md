# Rapport de qualité des données

Généré automatiquement par `python -m sbs_bank.pipeline` à partir de `sql/03_data_quality_checks.sql`.

## 1. Préparation de l'export CRM

| Indicateur | Valeur |
|---|---:|
| Lignes brutes dans l'export CRM | 1 884 |
| Identifiants clients distincts | 1 800 |
| Doublons écartés (anciennes versions ou copies) | 84 |
| Orthographes différentes du canal d'inscription | 13 |
| Dates de naissance au format JJ/MM/AAAA | 466 |
| Prénoms ou noms avec espaces ou casse incohérente | 380 |
| Emails non normalisés (majuscules ou espaces) | 167 |
| Villes non normalisées ou alias | 263 |
| Clients retenus dans la table customers | 1 800 |
| Clients avec email invalide (valeur mise à NULL) | 18 |
| Clients sans date de naissance | 45 |
| Clients avec date de naissance aberrante (mise à NULL) | 11 |
| Clients sans ville | 15 |

## 2. Contrôles d'intégrité des données opérationnelles

| Contrôle | Lignes en erreur | Statut |
|---|---:|:---:|
| Solde différent de la somme des transactions | 0 | OK |
| Numéro de carte invalide (algorithme de Luhn recalculé en SQL) | 0 | OK |
| Numéro de carte en double | 0 | OK |
| Solde négatif | 0 | OK |
| Transaction liée à une opération échouée, d'un autre type ou d'un autre montant | 0 | OK |
| Opération monétaire réussie sans transaction | 0 | OK |
| Opération antérieure à l'ouverture du compte | 0 | OK |
| Opération réussie après la clôture du compte | 0 | OK |
| Virement reçu par un compte clôturé | 0 | OK |
| Compte clôturé avec un solde restant | 0 | OK |

**Résultat global : tous les contrôles sont validés.**
