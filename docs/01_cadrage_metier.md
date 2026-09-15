# 1. Cadrage métier

Ce document formalise le besoin avant toute manipulation de données. Dans un projet réel, c'est la note validée avec le commanditaire : elle évite d'analyser « tout ce qui est disponible » sans savoir à quelle décision l'analyse doit servir.

## Contexte

SBS Bank est une néobanque fictive lancée en janvier 2025. Chaque client ouvre un compte associé à une carte de paiement (numéro à 16 chiffres commençant par `400000`, contrôlé par l'algorithme de Luhn) et le gère depuis l'application : consultation du solde, dépôts, virements vers d'autres clients, retraits, clôture.

Les clients arrivent par trois canaux : l'application mobile, le site web et des partenaires commerciaux (distributeurs, comparateurs) rémunérés à l'ouverture de compte.

Après 18 mois d'activité, le comité de direction constate une croissance du nombre de comptes, mais s'interroge sur la qualité de cette croissance.

## Problématique

> **La croissance de SBS Bank repose-t-elle sur des clients qui utilisent réellement leur compte, et quels leviers actionner en priorité pour améliorer l'activation, la rétention et la qualité de service ?**

## Parties prenantes

| Partie prenante | Attente |
|---|---|
| Direction générale | Vision globale de la santé du portefeuille |
| Marketing et acquisition | Performance des canaux, efficacité des campagnes |
| CRM et relation client | Listes de clients à contacter, segments à cibler |
| Produit et expérience client | Points de friction dans l'application |
| Risques et conformité | Comptes inactifs, tentatives de connexion suspectes |

## Questions métier

| # | Question | Décision éclairée |
|---|---|---|
| Q1 | Quelle est la situation du portefeuille au 30 juin 2026 ? | Priorités globales |
| Q2 | La banque grandit-elle, et l'activité suit-elle l'acquisition ? | Équilibre acquisition et rétention |
| Q3 | Quel canal amène des clients qui utilisent réellement leur compte ? | Budget et contrats partenaires |
| Q4 | L'engagement varie-t-il selon l'âge ? | Ciblage marketing |
| Q5 | Les clients restent-ils actifs dans les mois qui suivent l'ouverture ? | Actions de rétention |
| Q6 | Les encours sont-ils concentrés sur quelques clients ? | Suivi des clients à forte valeur |
| Q7 | Où les clients dépensent-ils avec leur carte ? | Offres partenaires, cashback |
| Q8 | Où les clients rencontrent-ils des échecs, et pourquoi ? | Feuille de route produit |
| Q9 | Le contrôle de Luhn est-il utile dans l'application ? | Choix techniques du parcours de saisie |
| Q10 | Les paiements refusés sont-ils concentrés sur quelques clients ? | Alertes, offre de découvert |
| Q11 | Quels clients actifs sont proches de la dormance ? | Campagne de relance |
| Q12 | Quels segments de clients distinguer ? | Plan d'action CRM |

## Indicateurs et définitions

Les définitions sont écrites une seule fois, dans les vues SQL (`sql/04_analytics_views.sql`), pour que tout le monde calcule les indicateurs de la même façon.

| Indicateur | Définition |
|---|---|
| Activité client | Opération réussie initiée par le client (application ou paiement carte), hors ouverture de compte |
| Compte activé | Compte ayant reçu au moins un dépôt réussi |
| Compte actif | Compte ouvert avec au moins une activité dans les 90 derniers jours de la période |
| Compte dormant | Compte alimenté mais sans activité depuis plus de 90 jours |
| Compte jamais alimenté | Compte ouvert n'ayant jamais reçu de dépôt |
| Taux d'activation à 7 ou 30 jours | Part des comptes alimentés dans les 7 ou 30 jours suivant l'ouverture |
| Rétention mensuelle | Part des comptes d'une cohorte d'ouverture actifs au cours du mois M |
| Taux d'échec | Opérations échouées divisées par tentatives, par type d'opération |
| Taux de refus carte | Paiements carte refusés divisés par tentatives de paiement |
| Encours | Somme des soldes à la date de fin de période |

## Périmètre

- **Période étudiée** : du 1er janvier 2025 au 30 juin 2026 (paramétrée dans `ref_analysis_period`).
- **Population** : l'ensemble des clients et des comptes ouverts sur la période.
- **Hors périmètre** : rentabilité (coûts d'acquisition et revenus non disponibles), détection de fraude avancée.

## Livrables

1. Base de données MySQL documentée et contrôlée
2. Requêtes SQL répondant aux questions métier
3. Notebook d'analyse avec interprétations et recommandations
4. Listes d'actions exploitables par le CRM (`reports/`)
5. README de synthèse
