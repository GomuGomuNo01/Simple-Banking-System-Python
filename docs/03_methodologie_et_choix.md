# 3. Méthodologie et choix techniques

## Point de départ

La consigne initiale (`docs/00_consigne_initiale.txt`) décrit un exercice de cours : un système bancaire en ligne de commande qui génère des numéros de carte valides selon l'algorithme de Luhn et les stocke dans une base de données.

Le projet a été étendu pour reproduire une situation professionnelle : **l'application devient le système opérationnel d'une néobanque**, et le travail de Data Analyst consiste à exploiter les données qu'elle produit pour répondre à des questions de la direction.

| Consigne initiale | Projet final |
|---|---|
| Menu en ligne de commande | Application conservée et enrichie (retrait, clôture sans perte d'historique) |
| Table `card` (id, number, pin, balance) | Modèle relationnel de 5 tables, staging, référentiels et vues |
| PIN stocké en clair | Empreinte PBKDF2-SHA256 salée |
| SQLite | MySQL (WampServer), transactions et verrous |
| Aucune donnée d'analyse | 18 mois d'activité simulée, export CRM à nettoyer |
| Aucune analyse | 12 questions métier, statistiques, segmentation, recommandations |

## Démarche suivie

La démarche reprend les étapes classiques d'un projet d'analyse (proches du cycle CRISP-DM) :

1. **Comprendre le besoin** : problématique, parties prenantes, questions, définitions des indicateurs (`docs/01_cadrage_metier.md`).
2. **Comprendre et modéliser les données** : modèle relationnel et contraintes d'intégrité (`sql/01_schema.sql`).
3. **Collecter et charger** : génération des données, chargement en base (`src/sbs_bank/pipeline.py`).
4. **Préparer** : nettoyage et dédoublonnage de l'export CRM en SQL (`sql/02_clean_customers.sql`).
5. **Contrôler la qualité** : contrôles bloquants avant toute analyse (`sql/03_data_quality_checks.sql`).
6. **Structurer pour l'analyse** : vues portant les définitions métier (`sql/04_analytics_views.sql`).
7. **Analyser** : requêtes métier (`sql/05_business_analysis.sql`) puis statistiques, segmentation et visualisation (notebook).
8. **Restituer** : interprétations, recommandations, listes d'actions, README.

## Pourquoi des données simulées, et comment

Les données bancaires réelles sont confidentielles. Plutôt que de tirer des lignes au hasard, `src/sbs_bank/simulation.py` modélise des **comportements** :

- 5 profils de clients : salarié, utilisateur occasionnel, épargnant, client qui décroche, client jamais activé ;
- des probabilités qui dépendent du canal d'acquisition et de l'âge ;
- de la saisonnalité (voyages en été, achats en décembre) et une campagne d'acquisition en septembre 2025 ;
- des erreurs humaines : chiffre mal saisi, chiffres inversés, oubli d'un chiffre, code PIN erroné, montant supérieur au solde.

Toutes les intentions sont ensuite **rejouées dans l'ordre chronologique à travers les règles métier de l'application** (`src/sbs_bank/rules.py`). Les refus, les soldes et les erreurs de saisie ne sont donc pas inventés : ils résultent des règles, exactement comme en production. La génération est reproductible (graine aléatoire fixe, `seed = 42`).

Les profils de clients ne sont **pas** stockés en base : l'analyse doit retrouver les comportements à partir des seules données observables, comme dans la réalité.

Une anomalie a été détectée pendant la phase d'exploration : les comptes « jamais alimentés » affichaient un solde moyen d'environ 3 000 €, car ils recevaient des virements d'autres clients. Ce résultat contredisait sa propre définition. La simulation a été corrigée (les clients n'envoient de l'argent qu'à des personnes qui utilisent réellement la banque). C'est l'illustration d'un réflexe essentiel : **confronter chaque chiffre à sa définition avant de le présenter**.

## Rôle de SQL et de Python

Le principe retenu : **chaque traitement est fait là où il est le plus simple, le plus fiable et le plus lisible.**

| Étape | Outil | Pourquoi |
|---|---|---|
| Modèle et contraintes | SQL | La base garantit elle-même l'intégrité : aucun script ne peut enregistrer un solde négatif ou un échec sans motif |
| Application bancaire | Python + SQL paramétré | Logique métier, interface, transactions ; requêtes paramétrées contre l'injection SQL |
| Génération des données | Python | Modélisation de comportements et de probabilités |
| Chargement des fichiers | Python | Lecture de fichiers, conversion des valeurs vides, insertion par lots |
| Nettoyage et dédoublonnage | SQL | Données déjà en base, traitements ensemblistes rapides et rejouables |
| Contrôles qualité | SQL | Vérifications au plus près des données (y compris l'algorithme de Luhn recalculé en SQL) |
| Définitions des indicateurs | SQL (vues) | Une seule définition partagée par toutes les analyses et outils |
| Agrégations métier | SQL | Fenêtres analytiques, cohortes, concentration : calcul là où sont les données |
| Tests statistiques | Python (SciPy) | Non disponibles en SQL |
| Segmentation RFM | Python (pandas) | Scoring par quantiles et règles plus lisibles et plus faciles à faire évoluer |
| Visualisation | Python (Matplotlib) | Graphiques exportés pour le notebook et le README |

Les requêtes SQL sont stockées dans des fichiers `.sql` avec un repère `-- name:`. Le notebook les exécute par leur nom (`run_query("q03_activation_by_channel")`) : **le SQL reste la source unique**, lisible et exécutable directement dans l'IDE.

## Choix techniques de l'application

| Choix | Problème résolu |
|---|---|
| Contrôle de Luhn avant la requête en base | Rejeter immédiatement une faute de frappe, sans solliciter la base |
| Règles métier dans un module partagé | Garantir que l'application et la simulation appliquent exactement les mêmes contrôles |
| Journal de toutes les tentatives | Mesurer les échecs, pas seulement les succès |
| Transaction unique (journal + solde + mouvement) | Pas d'état intermédiaire en cas d'erreur : tout ou rien |
| `SELECT ... FOR UPDATE` dans l'ordre des identifiants | Éviter qu'un double virement simultané ne corrompe les soldes ou ne bloque la base |
| Clôture logique (statut) au lieu d'une suppression | Conserver l'historique pour l'audit et l'analyse |
| PIN haché avec sel (PBKDF2, 600 000 itérations) | Un vol de la base ne révèle pas les codes PIN |
| Paramètres de connexion dans `.env` | Aucun mot de passe dans le code ni dans Git |
| Paramètres d'analyse en table (`ref_analysis_period`) | Résultats reproductibles même si l'application est utilisée ensuite |

## Choix de préparation des données

- **Rien n'est supprimé silencieusement.** Une valeur inexploitable (email invalide, date aberrante) devient NULL et l'anomalie est tracée dans `dq_flags`.
- **Dédoublonnage** : pour chaque client, la version la plus récente de l'export est conservée (`ROW_NUMBER() OVER (PARTITION BY ... ORDER BY updated_at DESC)`).
- **Normalisation** : casse, espaces, formats de date, 13 orthographes du canal ramenées à 3 valeurs, alias de villes.
- **Contrôles bloquants** : le pipeline s'arrête si un contrôle d'intégrité échoue, et le notebook vérifie de nouveau les contrôles avant d'analyser.

## Choix d'analyse

- **Seuil de dormance à 90 jours** : indicateur d'engagement usuel pour une application de paiement, distinct de la notion réglementaire de compte inactif (12 mois, loi Eckert).
- **Comparaison des canaux sur les comptes ouverts depuis au moins 30 jours** : un compte ouvert la veille n'a pas encore eu le temps d'être alimenté.
- **Test du khi-deux et V de Cramér** : vérifier qu'un écart entre canaux n'est pas dû au hasard, et mesurer la force du lien.
- **RFM avec seuils métier pour la récence** (7, 30, 60, 90 jours) plutôt que des quantiles : la moitié des comptes ayant une activité très récente, des quantiles produiraient des classes arbitraires.
- **Solde ajouté à la segmentation** : les épargnants ont une forte valeur malgré une faible activité et seraient mal classés par un RFM classique.

## Limites

- Données simulées : les tendances dépendent des hypothèses de simulation.
- Pas de coûts d'acquisition ni de revenus : la rentabilité par canal n'est pas mesurable.
- Le mois d'ouverture est incomplet dans l'analyse de cohortes (rétention M0 plus faible que M1).
- Les comptes simulés utilisent un facteur de hachage réduit (1 000 itérations) pour que la génération reste rapide ; l'application utilise 600 000 itérations.
- La normalisation des noms en SQL ne gère pas les noms composés ; la simulation n'en génère pas.
